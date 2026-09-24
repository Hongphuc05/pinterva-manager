"""Support compute agent: device login, presence gating, leased job/search queue, pool sync."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import text

from app.adapters.db.models import (
    Order,
    Platform,
    SupportCompareItem,
    SupportCompareJob,
    SupportWorkerDevice,
    User,
)
from app.application import support_worker as sw
from app.application.auth import create_session_token, hash_password
from app.application.support_compare import (
    count_handleable_orders,
    count_support_unchecked_orders,
    create_support_compare_job,
)

DIM = 4
MODEL = "test-model"


@pytest.fixture()
def ctx(db_session):
    platform = Platform(
        name="Plat worker", account_username="w@print.com", is_active=True, team_outsource="thuyhuong"
    )
    db_session.add(platform)
    db_session.flush()
    support = User(
        username="sup-w", full_name="Support W", role="support",
        password_hash=hash_password("pass"), active=True, platform_id=platform.id,
    )
    admin = User(
        username="adm-w", full_name="Admin W", role="admin",
        password_hash=hash_password("pass"), active=True, platform_id=platform.id,
    )
    db_session.add_all([support, admin])
    db_session.commit()
    return SimpleNamespace(platform=platform, support=support, admin=admin)


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_session_token(str(user.id), user.role)}"}


def _agent(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _pair(client, user: User, name: str = "Mac A") -> str:
    """The user answered "Có" on the web: the machine is granted and the token returned."""
    granted = client.post("/api/support-worker/devices/grant", json={"machine_name": name}, headers=_auth(user))
    assert granted.status_code == 200, granted.text
    return granted.json()["token"]


def _review(client, user: User, password: str = "secret1") -> dict[str, str]:
    """Headers of a Support who opened the hidden review area (sets the password on first use)."""
    headers = _auth(user)
    state = client.get("/api/support-review/access", headers=headers).json()
    path = "unlock" if state["has_password"] else "setup"
    token = client.post(f"/api/support-review/access/{path}", json={"password": password}, headers=headers).json()["token"]
    return {**headers, "X-Review-Token": token}


def _order(db_session, ctx, code: str, *, state: str = "WAITING") -> Order:
    order = Order(
        external_order_id=code, platform_id=ctx.platform.id, state=state,
        duplicate_check_status="uncheck", work_domain="standard",
        thumbnail_url=f"https://example.test/{code}.png", product_name=f"Product {code}",
        custom_config={"text": "hello"},
    )
    db_session.add(order)
    db_session.commit()
    return order


def _queue_job(db_session, ctx, count: int = 1) -> SupportCompareJob:
    job = SupportCompareJob(
        platform_id=ctx.platform.id, requested_by_id=ctx.support.id, chat_id="1", requested_count=count
    )
    db_session.add(job)
    db_session.commit()
    return job


def _b64(values) -> str:
    return base64.b64encode(np.asarray(values, dtype="<f4").tobytes()).decode()


def _item_payload(order: Order, *, duplicate: bool = False, asset_id: uuid.UUID | None = None) -> dict:
    candidates = []
    if asset_id:
        candidates.append(
            {
                "historical_asset_id": str(asset_id),
                "matched_external_order_id": "OLD-1",
                "matched_product_name": "Old product",
                "matched_image_url": "https://example.test/old.png",
                "rank": 1, "visual_similarity": 0.97, "phash_distance": 1, "ssim": 0.9,
                "color_delta_e": 1.0, "classification": "TRUNG", "confidence": 0.9, "reasons": ["x"],
            }
        )
    return {
        "order_id": str(order.id), "status": "completed", "embedding_b64": _b64([1, 0, 0, 0]),
        "phash": "ab" * 8, "lab": [50.0, 1.0, 2.0],
        "classification": "TRUNG" if duplicate else "KHONG_TRUNG", "is_duplicate": duplicate,
        "candidates": candidates,
    }


def _claim(client, token: str) -> dict:
    resp = client.post(
        "/api/support-worker/claim", json={"model_version": MODEL, "embedding_dim": DIM}, headers=_agent(token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_granting_a_machine_returns_the_token_once_and_keeps_only_its_hash(client, ctx, db_session):
    token = _pair(client, ctx.support)
    assert token.startswith("sw_")
    device = db_session.query(SupportWorkerDevice).one()
    assert device.status == "approved" and device.token_hash != token and device.user_id == ctx.support.id
    assert _claim(client, token)["kind"] == "none"


def test_granting_again_replaces_the_previous_grant_of_the_same_machine(client, ctx, db_session):
    first = _pair(client, ctx.support, "Mac A")
    second = _pair(client, ctx.support, "Mac A")
    other = _pair(client, ctx.support, "Mac B")
    stale = client.post(
        "/api/support-worker/claim", json={"model_version": MODEL, "embedding_dim": DIM}, headers=_agent(first)
    )
    assert stale.status_code == 401
    assert _claim(client, second)["kind"] == "none" and _claim(client, other)["kind"] == "none"


def test_only_a_support_session_can_grant_and_an_unauthenticated_agent_is_rejected(client, ctx):
    assert client.post("/api/support-worker/devices/grant", json={}).status_code == 401
    assert client.post("/api/support-worker/devices/grant", json={}, headers=_auth(ctx.admin)).status_code == 403
    assert client.post("/api/support-worker/claim", json={"model_version": MODEL, "embedding_dim": DIM}).status_code == 401
    assert client.post("/api/support-worker/presence").status_code == 401
    assert client.post("/api/support-worker/presence", headers=_auth(ctx.admin)).status_code == 403


def test_agent_works_only_while_the_web_shows_presence(client, ctx, db_session):
    token = _pair(client, ctx.support)
    assert _claim(client, token)["kind"] == "none"

    device = db_session.query(SupportWorkerDevice).one()
    device.presence_at = datetime.now(UTC) - timedelta(minutes=5)
    db_session.commit()
    paused = client.post(
        "/api/support-worker/claim", json={"model_version": MODEL, "embedding_dim": DIM}, headers=_agent(token)
    )
    assert paused.status_code == 403
    assert paused.json()["detail"]["code"] == "presence_lost"

    assert client.post("/api/support-worker/presence", headers=_auth(ctx.support)).status_code == 200
    assert _claim(client, token)["kind"] == "none"


def test_logout_revokes_the_users_machines(client, ctx):
    token = _pair(client, ctx.support)
    assert client.post("/api/logout", headers=_auth(ctx.support)).status_code == 200
    resp = client.post(
        "/api/support-worker/claim", json={"model_version": MODEL, "embedding_dim": DIM}, headers=_agent(token)
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "revoked"


def test_job_round_trip_stores_items_and_promotes_the_batch_to_the_pool(client, ctx, db_session):
    first = _order(db_session, ctx, "DJ-1")
    second = _order(db_session, ctx, "DJ-2")
    job = _queue_job(db_session, ctx, 2)
    token = _pair(client, ctx.support)

    claimed = _claim(client, token)
    assert claimed["kind"] == "job"
    assert {o["external_order_id"] for o in claimed["job"]["orders"]} == {"DJ-1", "DJ-2"}
    job_id = claimed["job"]["id"]

    asset_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO support_compare_image.image_assets "
            "(id, source_system, url_sha256, raw_url, url, fetch_status) "
            "VALUES (:id, 'test', :sha, 'https://example.test/old.png', 'https://example.test/old.png', 'embedded')"
        ),
        {"id": asset_id, "sha": uuid.uuid4().hex + uuid.uuid4().hex},
    )
    db_session.commit()
    stored = client.post(
        f"/api/support-worker/jobs/{job_id}/items",
        json={"items": [_item_payload(first, duplicate=True, asset_id=asset_id), _item_payload(second)]},
        headers=_agent(token),
    )
    assert stored.status_code == 200, stored.text
    assert stored.json()["stored"] == 2

    items = {i.external_order_id: i for i in db_session.query(SupportCompareItem).all()}
    assert items["DJ-1"].review_status == "pending_review"
    assert items["DJ-2"].review_status == "no_match"
    # Nothing is in the pool until the whole batch is done (no cross-matching inside a batch).
    assert db_session.execute(text("SELECT count(*) FROM support_compare_image.image_embeddings")).scalar() == 0

    done = client.post(
        f"/api/support-worker/jobs/{job_id}/complete", json={"baseline_count": 10}, headers=_agent(token)
    )
    assert done.status_code == 200, done.text
    assert done.json()["processed_count"] == 2 and done.json()["duplicate_count"] == 1
    db_session.expire_all()
    assert db_session.get(SupportCompareJob, job.id).status == "completed"
    assert db_session.execute(text("SELECT count(*) FROM support_compare_image.image_embeddings")).scalar() == 2
    stored_job = db_session.execute(
        text(
            "SELECT custom_config, custom_config_synced_at, team_outsource, last_seen_run_id "
            "FROM support_compare_image.historical_jobs WHERE external_order_id = 'DJ-1'"
        )
    ).one()
    assert stored_job.custom_config == {"text": "hello"} and stored_job.custom_config_synced_at is not None
    assert stored_job.team_outsource == "thuyhuong" and stored_job.last_seen_run_id is None
    # Compared once: the orders leave the queue for good and wait for the review or /handle.
    assert sw.pending_job_orders(db_session, ctx.platform.id) == []
    assert count_handleable_orders(db_session, platform_id=ctx.platform.id) == 1  # DJ-2 (no match)

    pool = client.get(
        "/api/support-worker/pool",
        params={"model_version": MODEL, "embedding_dim": DIM, "limit": 1},
        headers=_agent(token),
    ).json()
    assert len(pool["items"]) == 1 and pool["next_cursor"]
    rest = client.get(
        "/api/support-worker/pool",
        params={"model_version": MODEL, "embedding_dim": DIM, "limit": 5, "after": pool["next_cursor"]},
        headers=_agent(token),
    ).json()
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None and rest["cursor"]
    delta = client.get(
        "/api/support-worker/pool",
        params={"model_version": MODEL, "embedding_dim": DIM, "after": rest["cursor"]},
        headers=_agent(token),
    ).json()
    assert delta["items"] == [] and delta["cursor"] is None
    seen = {pool["items"][0]["external_order_id"], rest["items"][0]["external_order_id"]}
    assert seen == {"DJ-1", "DJ-2"}
    assert np.frombuffer(base64.b64decode(rest["items"][0]["embedding"]), dtype="<f4").tolist() == [1, 0, 0, 0]


def test_resubmitting_a_completed_item_is_a_no_op(client, ctx, db_session):
    order = _order(db_session, ctx, "DJ-ONCE")
    _queue_job(db_session, ctx)
    token = _pair(client, ctx.support)
    job_id = _claim(client, token)["job"]["id"]
    body = {"items": [_item_payload(order)]}
    assert client.post(f"/api/support-worker/jobs/{job_id}/items", json=body, headers=_agent(token)).json()["stored"] == 1
    again = client.post(f"/api/support-worker/jobs/{job_id}/items", json=body, headers=_agent(token)).json()
    assert again == {"stored": 0, "failed": 0, "skipped": 1}


def test_bad_embedding_is_rejected(client, ctx, db_session):
    order = _order(db_session, ctx, "DJ-BAD")
    _queue_job(db_session, ctx)
    token = _pair(client, ctx.support)
    job_id = _claim(client, token)["job"]["id"]
    payload = _item_payload(order)
    payload["embedding_b64"] = _b64([1, 0])  # wrong dimension
    resp = client.post(
        f"/api/support-worker/jobs/{job_id}/items", json={"items": [payload]}, headers=_agent(token)
    )
    assert resp.status_code == 422


def test_expired_lease_lets_another_machine_resume_with_the_remaining_orders(client, ctx, db_session):
    first = _order(db_session, ctx, "DJ-A")
    _order(db_session, ctx, "DJ-B")
    job = _queue_job(db_session, ctx, 2)
    token_a = _pair(client, ctx.support, "Mac A")
    token_b = _pair(client, ctx.support, "Mac B")

    claimed = _claim(client, token_a)
    job_id = claimed["job"]["id"]
    run_id = claimed["job"]["run_id"]
    client.post(
        f"/api/support-worker/jobs/{job_id}/items", json={"items": [_item_payload(first)]}, headers=_agent(token_a)
    )
    # Mac A still holds the lease, so Mac B gets nothing.
    assert _claim(client, token_b)["kind"] == "none"

    db_session.expire_all()
    db_session.get(SupportCompareJob, job.id).heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
    db_session.commit()

    resumed = _claim(client, token_b)
    assert resumed["kind"] == "job"
    assert resumed["job"]["run_id"] == run_id  # same run: earlier items stay attached to the job
    assert [o["external_order_id"] for o in resumed["job"]["orders"]] == ["DJ-B"]

    lost = client.post(f"/api/support-worker/jobs/{job_id}/heartbeat", headers=_agent(token_a))
    assert lost.status_code == 409 and lost.json()["detail"]["code"] == "lease_lost"


def test_search_is_queued_and_answered_by_an_agent(client, ctx, db_session):
    created = client.post(
        "/api/support-review/search?top_k=5",
        files={"file": ("cat.png", b"\x89PNG-bytes", "image/png")},
        headers=_review(client, ctx.support),
    )
    assert created.status_code == 202
    search_id = created.json()["id"]
    assert client.get(f"/api/support-review/search/{search_id}", headers=_review(client, ctx.support)).json()["status"] == "queued"

    token = _pair(client, ctx.support)
    claimed = _claim(client, token)
    assert claimed["kind"] == "search" and claimed["search"]["top_k"] == 5
    image = client.get(f"/api/support-worker/search/{search_id}/image", headers=_agent(token))
    assert image.content == b"\x89PNG-bytes"

    hist = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO support_compare_image.historical_jobs "
            "(id, source_system, source_job_id, external_order_id, status, team_outsource, job_type, product_name, preview_missing, custom_config) "
            "VALUES (:id, 'test', 'S1', 'OLD-S1', 'doing', 't', 'all', 'P', false, CAST('{\"text\": \"hi\"}' AS jsonb))"
        ),
        {"id": hist},
    )
    db_session.commit()
    result = {
        "verdict": "KHONG_TRUNG", "is_duplicate": False,
        "candidates": [{"rank": 1, "historical_job_id": str(hist)}, {"rank": 2, "historical_job_id": None}],
    }
    assert client.post(
        f"/api/support-worker/search/{search_id}/result", json={"result": result}, headers=_agent(token)
    ).status_code == 200
    done = client.get(f"/api/support-review/search/{search_id}", headers=_review(client, ctx.support)).json()
    assert done["status"] == "completed" and done["result"]["verdict"] == "KHONG_TRUNG"
    assert [c["custom_config"] for c in done["result"]["candidates"]] == [{"text": "hi"}, None]
    assert db_session.execute(text("SELECT image FROM support_compare_image.search_jobs")).scalar() is None


def test_queue_counts_waiting_jobs_and_lists_the_orders_still_to_check(client, ctx, db_session):
    _order(db_session, ctx, "DJ-Q1")
    _order(db_session, ctx, "DJ-Q2")
    first = create_support_compare_job(db_session, platform_id=ctx.platform.id, requested_by_id=ctx.support.id, chat_id="1")
    db_session.commit()
    _order(db_session, ctx, "DJ-Q3")
    second = create_support_compare_job(db_session, platform_id=ctx.platform.id, requested_by_id=ctx.support.id, chat_id="1")
    db_session.commit()
    assert first.requested_count == 2 and second.requested_count == 1  # each "Có" freezes its own orders

    queue = client.get("/api/support-worker/queue", headers=_auth(ctx.support)).json()
    assert queue["waiting_jobs"] == 2 and queue["machines"]["ready"] == 0
    assert [(j["id"], j["remaining_count"], j["requested_by"]) for j in queue["jobs"]] == [
        (str(first.id), 2, "Support W"), (str(second.id), 1, "Support W"),
    ]
    detail = client.get(f"/api/support-worker/queue/jobs/{first.id}/orders", headers=_auth(ctx.support)).json()
    assert sorted(o["external_order_id"] for o in detail["orders"]) == ["DJ-Q1", "DJ-Q2"]
    assert detail["orders"][0]["thumbnail_url"].startswith("https://example.test/")

    # A machine works the oldest job first, and only on the orders frozen in it.
    token = _pair(client, ctx.support)
    claimed = _claim(client, token)
    assert claimed["job"]["id"] == str(first.id)
    assert {o["external_order_id"] for o in claimed["job"]["orders"]} == {"DJ-Q1", "DJ-Q2"}
    queue = client.get("/api/support-worker/queue", headers=_auth(ctx.support)).json()
    assert queue["waiting_jobs"] == 2 and queue["jobs"][0]["status"] == "running"
    assert queue["jobs"][0]["worker_name"] == "Mac A" and queue["machines"]["ready"] == 1
    # The same machine can also take the second job at once? No: it has to finish the first lease.
    assert _claim(client, _pair(client, ctx.support, "Mac B"))["job"]["id"] == str(second.id)


def test_queue_is_only_for_support_and_only_for_its_platform(client, ctx, db_session):
    _order(db_session, ctx, "DJ-P1")
    job = create_support_compare_job(db_session, platform_id=ctx.platform.id, requested_by_id=ctx.support.id, chat_id="1")
    db_session.commit()
    assert client.get("/api/support-worker/queue").status_code == 401
    assert client.get("/api/support-worker/queue", headers=_auth(ctx.admin)).status_code == 403
    other = Platform(name="Other Q", account_username="oq@print.com", is_active=True)
    db_session.add(other)
    db_session.flush()
    outsider = User(username="sup-q", full_name="Q", role="support", password_hash=hash_password("pass"), active=True, platform_id=other.id)
    db_session.add(outsider)
    db_session.commit()
    assert client.get("/api/support-worker/queue", headers=_auth(outsider)).json()["waiting_jobs"] == 0
    assert client.get(f"/api/support-worker/queue/jobs/{job.id}/orders", headers=_auth(outsider)).status_code == 404


def test_a_second_press_only_takes_orders_that_are_not_already_queued(db_session, ctx):
    _order(db_session, ctx, "DJ-N1")
    kwargs = {"platform_id": ctx.platform.id, "requested_by_id": ctx.support.id, "chat_id": "1"}
    assert count_support_unchecked_orders(db_session, platform_id=ctx.platform.id) == 1
    assert create_support_compare_job(db_session, **kwargs) is not None
    db_session.commit()
    assert count_support_unchecked_orders(db_session, platform_id=ctx.platform.id) == 0
    assert create_support_compare_job(db_session, **kwargs) is None  # nothing new: no empty job


def test_support_cancels_a_job_and_admin_has_no_access(client, db_session, ctx):
    job = _queue_job(db_session, ctx)
    review = _review(client, ctx.support)
    assert client.post(f"/api/support-review/jobs/{job.id}/cancel", headers=_auth(ctx.admin)).status_code == 403
    assert client.post(f"/api/support-review/jobs/{job.id}/cancel", headers=_auth(ctx.support)).status_code == 403  # locked
    assert client.post(f"/api/support-review/jobs/{job.id}/cancel", headers=review).status_code == 200
    db_session.expire_all()
    cancelled = db_session.get(SupportCompareJob, job.id)
    assert cancelled.status == "failed" and cancelled.notification_sent_at is not None


def test_review_select_and_reject_are_scoped_to_the_platform(client, ctx, db_session):
    order = _order(db_session, ctx, "DJ-R")
    _queue_job(db_session, ctx)
    token = _pair(client, ctx.support)
    claimed = _claim(client, token)
    asset = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO support_compare_image.image_assets (id, source_system, url_sha256, raw_url, url, fetch_status) "
            "VALUES (:id, 'test', :sha, 'https://e.test/o.png', 'https://e.test/o.png', 'embedded')"
        ),
        {"id": asset, "sha": uuid.uuid4().hex + uuid.uuid4().hex},
    )
    db_session.commit()
    client.post(
        f"/api/support-worker/jobs/{claimed['job']['id']}/items",
        json={"items": [_item_payload(order, duplicate=True, asset_id=asset)]},
        headers=_agent(token),
    )
    detail = client.get(f"/api/support-review/jobs/{claimed['job']['id']}", headers=_review(client, ctx.support)).json()
    item = detail["items"][0]
    assert item["order_code"] == "DJ-R" and item["candidates"][0]["order_code"] == "OLD-1"

    other = Platform(name="Other", account_username="o@print.com", is_active=True)
    db_session.add(other)
    db_session.flush()
    outsider = User(
        username="sup-other", full_name="Other", role="support",
        password_hash=hash_password("pass"), active=True, platform_id=other.id,
    )
    db_session.add(outsider)
    db_session.commit()
    assert client.post(f"/api/support-review/items/{item['id']}/reject", headers=_review(client, outsider)).status_code == 404

    picked = client.post(
        f"/api/support-review/items/{item['id']}/select",
        json={"candidate_id": item["candidates"][0]["id"]},
        headers=_review(client, ctx.support),
    )
    assert picked.status_code == 200 and picked.json()["review_status"] == "selected_duplicate"


def test_review_area_needs_its_password_first_set_on_first_use(client, ctx):
    headers = _auth(ctx.support)
    assert client.get("/api/support-review/access", headers=headers).json() == {"has_password": False, "unlocked": False}
    assert client.get("/api/support-review/jobs", headers=headers).status_code == 403  # locked, nothing set yet
    short = client.post("/api/support-review/access/setup", json={"password": "abc"}, headers=headers)
    assert short.status_code == 422 and short.json()["detail"]["code"] == "weak_password"

    token = client.post("/api/support-review/access/setup", json={"password": "secret1"}, headers=headers).json()["token"]
    unlocked = {**headers, "X-Review-Token": token}
    assert client.get("/api/support-review/access", headers=unlocked).json() == {"has_password": True, "unlocked": True}
    assert client.get("/api/support-review/jobs", headers=unlocked).status_code == 200
    # Without the token, or with the wrong one, it is locked again; a second setup is refused.
    assert client.get("/api/support-review/jobs", headers=headers).status_code == 403
    assert client.get("/api/support-review/jobs", headers={**headers, "X-Review-Token": "junk"}).status_code == 403
    assert client.post("/api/support-review/access/setup", json={"password": "other12"}, headers=headers).status_code == 409


def test_unlock_checks_the_password_and_locks_out_after_repeated_failures(client, ctx):
    headers = _auth(ctx.support)
    client.post("/api/support-review/access/setup", json={"password": "secret1"}, headers=headers)
    wrong = client.post("/api/support-review/access/unlock", json={"password": "nope"}, headers=headers)
    assert wrong.status_code == 403 and wrong.json()["detail"]["code"] == "wrong_password"
    assert client.post("/api/support-review/access/unlock", json={"password": "secret1"}, headers=headers).status_code == 200

    for _ in range(5):
        client.post("/api/support-review/access/unlock", json={"password": "nope"}, headers=headers)
    locked = client.post("/api/support-review/access/unlock", json={"password": "secret1"}, headers=headers)
    assert locked.status_code == 429 and locked.json()["detail"]["code"] == "locked_out"  # even the right one


def test_changing_the_password_needs_the_current_one_and_ends_older_sessions(client, ctx):
    old = _review(client, ctx.support, "secret1")
    assert client.post(
        "/api/support-review/access/change", json={"current_password": "wrong1", "new_password": "newpass2"}, headers=old
    ).status_code == 403
    changed = client.post(
        "/api/support-review/access/change", json={"current_password": "secret1", "new_password": "newpass2"}, headers=old
    )
    assert changed.status_code == 200
    fresh = {**_auth(ctx.support), "X-Review-Token": changed.json()["token"]}
    assert client.get("/api/support-review/jobs", headers=fresh).status_code == 200  # the session that changed it stays in
    assert client.get("/api/support-review/jobs", headers=old).status_code == 403  # older tokens are dead
    login = client.post("/api/support-review/access/unlock", json={"password": "secret1"}, headers=_auth(ctx.support))
    assert login.status_code == 403
    assert client.post("/api/support-review/access/unlock", json={"password": "newpass2"}, headers=_auth(ctx.support)).status_code == 200


def test_the_password_is_shared_by_the_platform_but_a_token_is_per_user(client, ctx, db_session):
    review = _review(client, ctx.support)
    mate = User(username="sup-mate", full_name="Mate", role="support", password_hash=hash_password("pass"), active=True, platform_id=ctx.platform.id)
    db_session.add(mate)
    db_session.commit()
    stolen = {**_auth(mate), "X-Review-Token": review["X-Review-Token"]}
    assert client.get("/api/support-review/jobs", headers=stolen).status_code == 403  # another user's token
    assert client.post("/api/support-review/access/unlock", json={"password": "secret1"}, headers=_auth(mate)).status_code == 200

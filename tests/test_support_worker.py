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
    """Run the whole device login and return the agent token."""
    start = client.post("/api/support-worker/device/start", json={"machine_name": name}).json()
    approved = client.post(
        "/api/support-worker/devices/approve",
        json={"user_code": start["user_code"].lower()},
        headers=_auth(user),
    )
    assert approved.status_code == 200, approved.text
    poll = client.post("/api/support-worker/device/poll", json={"device_code": start["device_code"]}).json()
    assert poll["status"] == "approved"
    return poll["token"]


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


def test_device_login_token_is_delivered_once(client, ctx, db_session):
    token = _pair(client, ctx.support)
    assert token.startswith("sw_")
    device = db_session.query(SupportWorkerDevice).one()
    assert device.token_delivery is None and device.token_hash != token  # only the hash is kept

    again = client.post("/api/support-worker/device/poll", json={"device_code": "x" * 20}).json()
    assert again["status"] == "expired"


def test_wrong_code_and_unauthenticated_agent_are_rejected(client, ctx):
    assert (
        client.post("/api/support-worker/devices/approve", json={"user_code": "ZZZZ-9999"}, headers=_auth(ctx.support))
    ).status_code == 404
    assert client.post("/api/support-worker/claim", json={"model_version": MODEL, "embedding_dim": DIM}).status_code == 401
    designer = client.post("/api/support-worker/presence")
    assert designer.status_code == 401


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
        headers=_auth(ctx.support),
    )
    assert created.status_code == 202
    search_id = created.json()["id"]
    assert client.get(f"/api/support-review/search/{search_id}", headers=_auth(ctx.support)).json()["status"] == "queued"

    token = _pair(client, ctx.support)
    claimed = _claim(client, token)
    assert claimed["kind"] == "search" and claimed["search"]["top_k"] == 5
    image = client.get(f"/api/support-worker/search/{search_id}/image", headers=_agent(token))
    assert image.content == b"\x89PNG-bytes"

    hist = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO support_compare_image.historical_jobs "
            "(id, source_system, source_job_id, external_order_id, status, team_outsource, job_type, preview_missing, custom_config) "
            "VALUES (:id, 'test', 'S1', 'OLD-S1', 'doing', 't', 'all', false, CAST('{\"text\": \"hi\"}' AS jsonb))"
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
    done = client.get(f"/api/support-review/search/{search_id}", headers=_auth(ctx.support)).json()
    assert done["status"] == "completed" and done["result"]["verdict"] == "KHONG_TRUNG"
    assert [c["custom_config"] for c in done["result"]["candidates"]] == [{"text": "hi"}, None]
    assert db_session.execute(text("SELECT image FROM support_compare_image.search_jobs")).scalar() is None


def test_queue_lists_running_queued_workers_and_recent(client, ctx, db_session):
    _order(db_session, ctx, "DJ-Q")
    job = _queue_job(db_session, ctx, 1)
    resp = client.get("/api/support-review/queue", headers=_auth(ctx.support)).json()
    assert [q["id"] for q in resp["queued"]] == [str(job.id)] and resp["queued"][0]["position"] == 1
    assert resp["workers"]["ready"] == 0

    token = _pair(client, ctx.support)
    _claim(client, token)
    resp = client.get("/api/support-review/queue", headers=_auth(ctx.support)).json()
    assert [r["id"] for r in resp["running"]] == [str(job.id)]
    assert resp["running"][0]["worker_name"] == "Mac A"
    assert resp["workers"]["ready"] == 1 and resp["workers"]["devices"][0]["state"] == "busy"


def test_only_admin_cancels_a_job(client, ctx, db_session):
    job = _queue_job(db_session, ctx)
    assert client.post(f"/api/support-review/jobs/{job.id}/cancel", headers=_auth(ctx.support)).status_code == 403
    assert client.post(f"/api/support-review/jobs/{job.id}/cancel", headers=_auth(ctx.admin)).status_code == 200
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
    detail = client.get(f"/api/support-review/jobs/{claimed['job']['id']}", headers=_auth(ctx.support)).json()
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
    assert client.post(f"/api/support-review/items/{item['id']}/reject", headers=_auth(outsider)).status_code == 404

    picked = client.post(
        f"/api/support-review/items/{item['id']}/select",
        json={"candidate_id": item["candidates"][0]["id"]},
        headers=_auth(ctx.support),
    )
    assert picked.status_code == 200 and picked.json()["review_status"] == "selected_duplicate"


def test_pending_login_cap_and_expiry(db_session):
    for _ in range(sw.MAX_PENDING_DEVICES):
        sw.start_device_login(db_session, machine_name="m")
    db_session.commit()
    with pytest.raises(sw.WorkerAuthError):
        sw.start_device_login(db_session, machine_name="m")
    db_session.query(SupportWorkerDevice).update({"expires_at": datetime.now(UTC) - timedelta(minutes=1)})
    db_session.commit()
    sw.start_device_login(db_session, machine_name="m")  # expired rows are purged first

"""A brand-new Platform (a new "Acc Mẹ") alongside an existing one: does every subsystem stay
scoped to its own platform, and is anything still shared/leaking across them?

Each test below creates platform A (stands in for an existing, already-onboarded platform) and
platform B (stands in for a freshly created one, with nothing special done to it beyond what the
UI lets an Admin do: create platform, set credentials/team_outsource, create one user per role).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.adapters.db.models import Order, Platform, User
from app.application.auth import create_session_token, hash_password
from app.domain.models import OrderState


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_session_token(str(user.id), user.role)}"}


def _platform(db_session, suffix: str, **over) -> Platform:
    p = Platform(
        name=f"Plat {suffix}", account_username=f"{suffix}@print.com", is_active=True,
        team_outsource=f"team-{suffix}", **over,
    )
    db_session.add(p)
    db_session.flush()
    return p


def _user(db_session, platform: Platform, suffix: str, role: str, **over) -> User:
    u = User(
        username=f"{role}-{suffix}", full_name=f"{role.title()} {suffix}", role=role,
        password_hash=hash_password("pass"), active=True, platform_id=platform.id, **over,
    )
    db_session.add(u)
    return u


@pytest.fixture()
def two_platforms(db_session):
    """A = existing platform, B = freshly onboarded one. One of every role on each."""
    a = _platform(db_session, "a", standard_order_rate=40000, duplicate_order_rate=30000)
    b = _platform(db_session, "b", standard_order_rate=50000, duplicate_order_rate=20000)
    users = {}
    for key, plat in (("a", a), ("b", b)):
        users[f"admin_{key}"] = _user(db_session, plat, key, "admin")
        users[f"support_{key}"] = _user(db_session, plat, key, "support")
        users[f"designer_{key}"] = _user(db_session, plat, key, "designer")
        users[f"accountant_{key}"] = _user(db_session, plat, key, "accountant")
    db_session.commit()
    return SimpleNamespace(a=a, b=b, **users)


def _order(db_session, platform: Platform, code: str, **over) -> Order:
    over.setdefault("state", OrderState.WAITING.value)
    o = Order(external_order_id=code, platform_id=platform.id, **over)
    db_session.add(o)
    return o


# ---------------------------------------------------------------------------
# Orders, users: the basics every role touches
# ---------------------------------------------------------------------------

def test_orders_list_is_scoped_per_platform(client, two_platforms, db_session):
    _order(db_session, two_platforms.a, "A-ORD-1")
    _order(db_session, two_platforms.b, "B-ORD-1")
    db_session.commit()

    for key, plat in (("a", two_platforms.a), ("b", two_platforms.b)):
        admin = getattr(two_platforms, f"admin_{key}")
        res = client.get("/api/orders", headers={**_auth(admin), "X-Platform-Id": str(plat.id)})
        assert res.status_code == 200
        codes = {o["external_order_id"] for o in res.json()["orders"]}
        assert codes == {f"{key.upper()}-ORD-1"}


def test_an_admin_cannot_widen_scope_to_the_other_platform_via_header(client, two_platforms, db_session):
    _order(db_session, two_platforms.b, "B-ONLY")
    db_session.commit()
    # Admin A explicitly asks for platform B's data via the header: allowed for admin by design
    # (get_current_platform_id trusts the header only for role==admin) — this is the one
    # deliberate cross-platform door, used by the UI's platform switcher. Confirm it still
    # requires the header, i.e. without it Admin A is NOT silently shown B's data.
    admin_a = two_platforms.admin_a
    res_without_header = client.get("/api/orders", headers=_auth(admin_a))
    assert "B-ONLY" not in {o["external_order_id"] for o in res_without_header.json()["orders"]}


def test_users_list_never_leaks_the_other_platforms_accounts(client, two_platforms):
    res = client.get("/api/users", headers={**_auth(two_platforms.admin_a), "X-Platform-Id": str(two_platforms.a.id)})
    names = {u["username"] for u in res.json()}
    assert "admin-b" not in names and "support-b" not in names


# ---------------------------------------------------------------------------
# Finance / Accountant — paying real money must never cross platforms
# ---------------------------------------------------------------------------

def test_finance_and_accountant_totals_use_each_platforms_own_rates_and_designers(client, two_platforms, db_session):
    from app.adapters.db.models import Assignment

    des_a, des_b = two_platforms.designer_a, two_platforms.designer_b
    order_a = _order(db_session, two_platforms.a, "A-PAY", state=OrderState.QC_PENDING.value, note_outsource="https://drive.google.com/x")
    order_b = _order(db_session, two_platforms.b, "B-PAY", state=OrderState.QC_PENDING.value, note_outsource="https://drive.google.com/y")
    db_session.flush()
    db_session.add_all([
        Assignment(order_id=order_a.id, designer_id=des_a.id, status="approved"),
        Assignment(order_id=order_b.id, designer_id=des_b.id, status="approved"),
    ])
    db_session.commit()

    stats_a = client.get("/api/finance/stats", headers={**_auth(two_platforms.admin_a), "X-Platform-Id": str(two_platforms.a.id)}).json()
    stats_b = client.get("/api/finance/stats", headers={**_auth(two_platforms.admin_b), "X-Platform-Id": str(two_platforms.b.id)}).json()
    # Each platform's own rate (A=40000, B=50000) applies, and neither sees the other's order.
    assert [t["external_order_id"] for t in stats_a["tasks"]] == ["A-PAY"] and stats_a["tasks"][0]["rate"] == 40000
    assert [t["external_order_id"] for t in stats_b["tasks"]] == ["B-PAY"] and stats_b["tasks"][0]["rate"] == 50000

    # The Accountant of platform B must not see platform A's designer/amount, even though both
    # are "pending payment" at the same time.
    pending_b = client.get("/api/accountant/designers", headers=_auth(two_platforms.accountant_b)).json()
    assert [r["designer_name"] for r in pending_b] == ["Designer b"]
    assert pending_b[0]["pending_amount"] == 50000

    pending_a = client.get("/api/accountant/designers", headers=_auth(two_platforms.accountant_a)).json()
    assert [r["designer_name"] for r in pending_a] == ["Designer a"]

    # Accountant B paying never touches platform A's order or its history.
    detail = client.get(f"/api/accountant/designers/{des_b.id}", headers=_auth(two_platforms.accountant_b)).json()
    pay = client.post(
        f"/api/accountant/designers/{des_b.id}/pay", headers=_auth(two_platforms.accountant_b),
        json={"order_ids": [o["order_id"] for o in detail["orders"]], "expected_total": detail["pending_amount"]},
    )
    assert pay.status_code == 200
    db_session.expire_all()
    assert db_session.get(Order, order_a.id).is_paid is False
    history_a = client.get("/api/finance/payment-history", headers={**_auth(two_platforms.admin_a), "X-Platform-Id": str(two_platforms.a.id)}).json()
    assert history_a["total"] == 0  # B's payment did not leak into A's history


def test_an_accountant_cannot_switch_platform_with_the_header(client, two_platforms, db_session):
    _order(db_session, two_platforms.b, "B-SNEAK", state=OrderState.QC_PENDING.value, note_outsource="https://drive.google.com/z")
    db_session.commit()
    # Accountant A tries the same header trick an Admin could use — must be ignored for this role.
    res = client.get(
        "/api/accountant/designers",
        headers={**_auth(two_platforms.accountant_a), "X-Platform-Id": str(two_platforms.b.id)},
    )
    assert res.json() == []


# ---------------------------------------------------------------------------
# Support duplicate-review: password, job queue
# ---------------------------------------------------------------------------

def test_support_review_password_and_queue_are_per_platform(client, two_platforms):
    hdr_a = _auth(two_platforms.support_a)
    hdr_b = _auth(two_platforms.support_b)

    assert client.post("/api/support-review/access/setup", json={"password": "secretA1"}, headers=hdr_a).status_code == 200
    # Platform B still has no password set — its own first-use flow, unaffected by A's.
    status_b = client.get("/api/support-review/access", headers=hdr_b).json()
    assert status_b["has_password"] is False

    # A's password does not unlock B's area even if somehow tried — B has no password of its own
    # yet (409, "set one first"), which on its own proves the two platforms' access rows are
    # separate: if they shared one, B would already see has_password=True from A's setup above.
    assert client.post("/api/support-review/access/unlock", json={"password": "secretA1"}, headers=hdr_b).status_code == 409

    queue_a = client.get("/api/support-worker/queue", headers=hdr_a).json()
    queue_b = client.get("/api/support-worker/queue", headers=hdr_b).json()
    assert queue_a == {"waiting_jobs": 0, "jobs": [], "machines": {"ready": 0, "paused": 0, "offline": 0}}
    assert queue_b == queue_a  # both empty and independent, not shared state


# ---------------------------------------------------------------------------
# Telegram admin overview: recipient list per platform
# ---------------------------------------------------------------------------

def test_telegram_admin_overview_only_lists_its_own_platforms_designers(client, two_platforms):
    res_a = client.get("/api/telegram/admin/overview", headers={**_auth(two_platforms.admin_a), "X-Platform-Id": str(two_platforms.a.id)})
    assert res_a.status_code == 200
    usernames = {d["username"] for d in res_a.json()["designers"]}
    assert "designer-b" not in usernames and "designer-a" in usernames


# ---------------------------------------------------------------------------
# FINDING: the duplicate-detection historical pool is NOT scoped per platform.
# ---------------------------------------------------------------------------

def test_FINDING_the_duplicate_detection_pool_is_shared_across_all_platforms(client, two_platforms, db_session):
    """Documents a real gap, not a crash: a design promoted to the pool from Platform A's own
    order comparisons is visible to Platform B's agent too. `GET /support-worker/pool` takes no
    platform filter at all (see app/application/support_worker.py::pool_page), and
    `support_compare_image.historical_jobs`/`image_embeddings` have no `platform_id` column.

    Practically: once Support on Platform A confirms two orders "Trùng lặp" (and the run
    promotes them), Platform B's comparisons will be run against A's designs too — a brand-new,
    unrelated client's historical images can be offered to Support as a duplicate match for a
    totally different client's order, and vice versa.
    """
    asset_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO support_compare_image.image_assets "
            "(id, source_system, url_sha256, raw_url, url, fetch_status) "
            "VALUES (:id, 'test', :sha, 'https://example.test/a.png', 'https://example.test/a.png', 'embedded')"
        ),
        {"id": asset_id, "sha": uuid.uuid4().hex + uuid.uuid4().hex},
    )
    embedding = (b"\x00\x00\x80?" + b"\x00" * 4 * 3)  # a 4-float little-endian vector [1,0,0,0]
    db_session.execute(
        text(
            "INSERT INTO support_compare_image.image_embeddings "
            "(asset_id, model_version, embedding_dim, embedding, phash, color_l, color_a, color_b) "
            "VALUES (:asset_id, 'test-model', 4, :emb, 'ff00', 0, 0, 0)"
        ),
        {"asset_id": asset_id, "emb": embedding},
    )
    job_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO support_compare_image.historical_jobs "
            "(id, source_system, source_job_id, external_order_id, status, team_outsource, job_type, product_name) "
            "VALUES (:id, 'test', :sjid, 'A-HISTORICAL', 'done', :team, 'standard', 'Product from Platform A')"
        ),
        {"id": job_id, "sjid": uuid.uuid4().hex, "team": two_platforms.a.team_outsource},
    )
    db_session.execute(
        text(
            "INSERT INTO support_compare_image.job_images (id, job_id, asset_id, role, position, is_primary) "
            "VALUES (gen_random_uuid(), :job_id, :asset_id, 'primary', 0, true)"
        ),
        {"job_id": job_id, "asset_id": asset_id},
    )
    db_session.commit()

    # Platform B's agent asks for the pool — it was never told anything about Platform A.
    pool = client.get(
        "/api/support-worker/pool",
        params={"model_version": "test-model", "embedding_dim": 4, "limit": 10},
        headers=_agent_token_for(client, two_platforms.support_b),
    ).json()

    leaked = {item["external_order_id"] for item in pool["items"]}
    assert "A-HISTORICAL" in leaked, (
        "if this now fails, the pool has become platform-scoped and this test (and the finding "
        "in architecture.md) should be updated, not just skipped"
    )


def _agent_token_for(client, support_user: User) -> dict[str, str]:
    grant = client.post(
        "/api/support-worker/devices/grant", json={"machine_name": "isolation-test-machine"}, headers=_auth(support_user),
    ).json()
    client.post("/api/support-worker/presence", headers=_auth(support_user))
    return {"Authorization": f"Bearer {grant['token']}"}

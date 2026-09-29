from datetime import UTC, datetime
from unittest.mock import patch

from app.adapters.db.models import Assignment, Order, Platform, User, WorkflowEvent
from app.api.routes.finance_api import (
    get_task_submission_timestamp,
    parse_date_to_utc_timestamp,
)
from app.application.auth import create_session_token, hash_password
from app.domain.models import OrderState


def test_parse_date_to_utc_timestamp():
    # Test start of day 14/09/2026 in UTC+7
    ts_start = parse_date_to_utc_timestamp("2026-09-14", is_end_of_day=False)
    assert ts_start is not None
    # 2026-09-14 00:00:00+07:00 is 2026-09-13 17:00:00 UTC
    dt_start = datetime.fromtimestamp(ts_start, tz=UTC)
    assert dt_start.day == 13
    assert dt_start.hour == 17

    # Test end of day 18/09/2026 in UTC+7
    ts_end = parse_date_to_utc_timestamp("2026-09-18", is_end_of_day=True)
    assert ts_end is not None
    # 2026-09-18 23:59:59.999999+07:00 is 2026-09-18 16:59:59.999999 UTC
    dt_end = datetime.fromtimestamp(ts_end, tz=UTC)
    assert dt_end.day == 18
    assert dt_end.hour == 16


def test_get_task_submission_timestamp():
    dt_utc = datetime(2026, 9, 20, 16, 37, 48, tzinfo=UTC)
    dt_first = datetime(2026, 9, 18, 10, 0, 0, tzinfo=UTC)
    task = {
        "review_submitted_at": dt_utc,
        "first_submitted_at": dt_first,
    }
    ts = get_task_submission_timestamp(task)
    assert ts == dt_first.timestamp()

def test_normalize_text():
    from app.api.routes.finance_api import normalize_text
    assert normalize_text("Tài") == "tai"
    assert normalize_text("tai") == "tai"
    assert normalize_text("Tài ") == "tai"
    assert normalize_text("Đức Phúc") == "duc phuc"


def test_support_finance_is_scoped_to_own_classification_count(client, db_session):
    platform = Platform(name="Support finance platform", account_username="support-finance@example.com")
    other_platform = Platform(name="Other finance platform", account_username="other-finance@example.com")
    db_session.add_all([platform, other_platform])
    db_session.flush()
    support = User(
        username="support_finance_owner",
        full_name="Support Owner",
        role="support",
        password_hash=hash_password("pass"),
        platform_id=platform.id,
    )
    another_support = User(
        username="support_finance_other",
        full_name="Other Support",
        role="support",
        password_hash=hash_password("pass"),
        platform_id=platform.id,
    )
    db_session.add_all([support, another_support])
    db_session.flush()
    classified_at = datetime.now(UTC)
    own_order = Order(
        external_order_id="SUPPORT-FIN-OWN",
        platform_id=platform.id,
        state=OrderState.IN_PROGRESS.value,
        duplicate_check_status="duplicate",
        support_classified_by_id=support.id,
        support_classified_at=classified_at,
    )
    other_support_order = Order(
        external_order_id="SUPPORT-FIN-OTHER",
        platform_id=platform.id,
        state=OrderState.IN_PROGRESS.value,
        duplicate_check_status="duplicate",
        support_classified_by_id=another_support.id,
        support_classified_at=classified_at,
    )
    foreign_order = Order(
        external_order_id="SUPPORT-FIN-FOREIGN",
        platform_id=other_platform.id,
        state=OrderState.IN_PROGRESS.value,
        duplicate_check_status="duplicate",
        support_classified_by_id=support.id,
        support_classified_at=classified_at,
    )
    stale_non_duplicate = Order(
        external_order_id="SUPPORT-FIN-NON-DUPLICATE",
        platform_id=platform.id,
        state=OrderState.WAITING.value,
        duplicate_check_status="non_duplicate",
        support_classified_by_id=support.id,
        support_classified_at=classified_at,
    )
    db_session.add_all([own_order, other_support_order, foreign_order, stale_non_duplicate])
    db_session.commit()

    support_token = create_session_token(str(support.id), support.role)
    response = client.get(
        "/api/finance/stats",
        headers={
            "Authorization": f"Bearer {support_token}",
            # A Support account must not be able to widen its scope with this header.
            "X-Platform-Id": str(other_platform.id),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["support_classified_count"] == 1
    assert payload["tasks"] == []
    assert payload["total_tasks_count"] == 0
    assert [item["support_name"] for item in payload["support_summary"]] == ["Support Owner"]
    assert payload["support_summary"][0]["classified_tasks"] == 1
    # The detail behind the count: exactly the orders this Support tagged duplicate.
    assert [item["external_order_id"] for item in payload["support_orders"]] == ["SUPPORT-FIN-OWN"]
    assert payload["support_orders"][0]["classified_at"] is not None

    admin = User(
        username="support_finance_admin",
        full_name="Finance Admin",
        role="admin",
        password_hash=hash_password("pass"),
    )
    db_session.add(admin)
    db_session.commit()
    admin_token = create_session_token(str(admin.id), admin.role)
    admin_response = client.get(
        "/api/finance/stats",
        headers={
            "Authorization": f"Bearer {admin_token}",
            "X-Platform-Id": str(platform.id),
        },
    )

    assert admin_response.status_code == 200
    admin_payload = admin_response.json()
    assert admin_payload["support_classified_count"] == 2
    assert admin_payload["support_orders"] == []  # Admin sees the per-Support totals only
    assert {
        (item["support_name"], item["classified_tasks"])
        for item in admin_payload["support_summary"]
    } == {("Support Owner", 1), ("Other Support", 1)}


def _rate_setup(db_session, suffix):
    platform = Platform(name=f"Rate plat {suffix}", account_username=f"rate-{suffix}@example.com",
                        standard_order_rate=40000, duplicate_order_rate=30000)
    other = Platform(name=f"Rate other {suffix}", account_username=f"rate-other-{suffix}@example.com")
    db_session.add_all([platform, other])
    db_session.flush()
    admin = User(username=f"rate_admin_{suffix}", full_name="Rate Admin", role="admin", password_hash=hash_password("pass"))
    des = User(username=f"rate_des_{suffix}", full_name="Rate Des", role="designer", password_hash=hash_password("pass"),
               platform_id=platform.id)
    order = Order(external_order_id=f"RATE-{suffix}", platform_id=platform.id, state=OrderState.QC_PENDING.value)
    foreign = Order(external_order_id=f"RATE-F-{suffix}", platform_id=other.id, state=OrderState.QC_PENDING.value)
    db_session.add_all([admin, des, order, foreign])
    db_session.commit()
    hdr = {"Authorization": f"Bearer {create_session_token(str(admin.id), admin.role)}", "X-Platform-Id": str(platform.id)}
    return platform, admin, des, order, foreign, hdr


def test_admin_sets_single_order_rate_and_it_persists(client, db_session):
    platform, admin, des, order, foreign, hdr = _rate_setup(db_session, "ok")
    url = f"/api/finance/orders/{order.id}/rate"

    res = client.put(url, json={"rate": 55000}, headers=hdr)
    assert res.status_code == 200
    assert res.json()["rate"] == 55000 and res.json()["custom_rate"] == 55000
    db_session.expire_all()
    assert db_session.get(Order, order.id).custom_rate == 55000
    # A second, independent request (what a re-opened tab does) still sees it in the stats.
    stats = client.get("/api/finance/stats", headers=hdr).json()
    assert next(t for t in stats["tasks"] if t["order_id"] == str(order.id))["rate"] == 55000

    # Back to the platform default: stored as NULL so it follows the default again.
    res = client.put(url, json={"rate": 40000}, headers=hdr)
    assert res.json()["custom_rate"] is None and res.json()["rate"] == 40000
    db_session.expire_all()
    assert db_session.get(Order, order.id).custom_rate is None


def test_order_rate_is_admin_only_platform_scoped_validated_and_locked_when_paid(client, db_session):
    platform, admin, des, order, foreign, hdr = _rate_setup(db_session, "rules")
    des_hdr = {"Authorization": f"Bearer {create_session_token(str(des.id), des.role)}"}
    assert client.put(f"/api/finance/orders/{order.id}/rate", json={"rate": 1}, headers=des_hdr).status_code == 403
    assert client.put(f"/api/finance/orders/{foreign.id}/rate", json={"rate": 1}, headers=hdr).status_code == 404
    assert client.put(f"/api/finance/orders/{order.id}/rate", json={"rate": -5}, headers=hdr).status_code == 422
    assert client.put(f"/api/finance/orders/{order.id}/rate", json={"rate": 10_000_001}, headers=hdr).status_code == 422

    order.is_paid = True
    db_session.commit()
    assert client.put(f"/api/finance/orders/{order.id}/rate", json={"rate": 50000}, headers=hdr).status_code == 409
    db_session.expire_all()
    assert db_session.get(Order, order.id).custom_rate is None


def test_payment_telegram_notification_credits_latest_submitter_not_current_assignee(client, db_session):
    """An order that changed hands: A was assigned, but B is the one who actually
    submitted it (the finance page credits B). Paying it must notify B, not A."""
    platform = Platform(name="Payment handoff plat", account_username="pay-handoff@example.com",
                        standard_order_rate=40000, duplicate_order_rate=30000)
    db_session.add(platform)
    db_session.flush()
    admin = User(username="pay_handoff_admin", full_name="Pay Admin", role="admin", password_hash=hash_password("pass"))
    designer_a = User(username="pay_handoff_a", full_name="Designer A", role="designer",
                       password_hash=hash_password("pass"), platform_id=platform.id,
                       telegram_chat_id="111", telegram_notifications_enabled=True)
    designer_b = User(username="pay_handoff_b", full_name="Designer B", role="designer",
                       password_hash=hash_password("pass"), platform_id=platform.id,
                       telegram_chat_id="222", telegram_notifications_enabled=True)
    order = Order(external_order_id="PAY-HANDOFF", platform_id=platform.id, state=OrderState.QC_PENDING.value)
    db_session.add_all([admin, designer_a, designer_b, order])
    db_session.flush()
    # Current Assignment still points at A (never updated after the handoff).
    db_session.add(Assignment(order_id=order.id, designer_id=designer_a.id, status="approved"))
    # But B is the one who actually submitted the order — the finance page credits B for it.
    db_session.add(WorkflowEvent(
        order_id=order.id, from_state=OrderState.IN_PROGRESS.value, to_state=OrderState.QC_PENDING.value,
        actor_id=designer_b.id, evidence={"actor_role": "designer"},
    ))
    db_session.commit()

    hdr = {"Authorization": f"Bearer {create_session_token(str(admin.id), admin.role)}", "X-Platform-Id": str(platform.id)}
    with patch("app.workers.telegram_tasks.safe_dispatch_telegram_task") as dispatch:
        res = client.post("/api/finance/mark-paid", json={"order_ids": [str(order.id)]}, headers=hdr)
    assert res.status_code == 200 and res.json()["updated_count"] == 1

    assert dispatch.call_count == 1
    args = dispatch.call_args.args
    assert args[1] == str(designer_b.id)  # notified: the credited submitter B
    assert args[1] != str(designer_a.id)  # not: the stale current assignee A
    assert args[2] == 1 and args[3] == 40000

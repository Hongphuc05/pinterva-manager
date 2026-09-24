from datetime import UTC, datetime

from app.adapters.db.models import Order, Platform, User
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

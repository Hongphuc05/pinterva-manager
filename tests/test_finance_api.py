from datetime import UTC, datetime, timedelta, timezone

from app.adapters.db.models import Assignment, Order, Platform, User
from app.api.deps import DEFAULT_PLATFORM_ID
from app.api.routes.finance_api import (
    get_task_submission_timestamp,
    parse_date_to_utc_timestamp,
)
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
    task = {
        "review_submitted_at": dt_utc,
        "first_submitted_at": datetime(2026, 9, 18, 10, 0, 0, tzinfo=UTC),
    }
    ts = get_task_submission_timestamp(task)
    assert ts == dt_utc.timestamp()

def test_normalize_text():
    from app.api.routes.finance_api import normalize_text
    assert normalize_text("Tài") == "tai"
    assert normalize_text("tai") == "tai"
    assert normalize_text("Tài ") == "tai"
    assert normalize_text("Đức Phúc") == "duc phuc"


from app.config import Settings
from app.workers.celery_app import build_beat_schedule, celery_app


def test_order_sheet_backup_is_not_scheduled_when_disabled():
    schedule = build_beat_schedule(
        Settings(secret_key="test", cookie_secure=False, order_sheet_backup_enabled=False)
    )
    assert "export-order-sheet-backup" not in schedule


def test_recent_status_sync_runs_twice_per_hour_and_nightly_at_two():
    schedule = build_beat_schedule(Settings(secret_key="test", cookie_secure=False))

    recent = schedule["sync-recent-order-statuses"]
    assert recent["task"] == "app.workers.status_sync_tasks.sync_recent_order_statuses"
    assert recent["schedule"]._orig_minute == "2,32"
    nightly = schedule["sync-nightly-order-statuses"]
    assert nightly["task"] == "app.workers.status_sync_tasks.sync_nightly_order_statuses"
    assert (nightly["schedule"]._orig_hour, nightly["schedule"]._orig_minute) == (2, 0)
    assert "sync-full-database-order-statuses" not in schedule


def test_order_sheet_backup_uses_configured_vietnam_schedule():
    schedule = build_beat_schedule(
        Settings(
            secret_key="test",
            cookie_secure=False,
            order_sheet_backup_enabled=True,
            google_service_account_file="/run/secrets/google.json",
            google_sheets_order_backup_url="https://docs.google.com/spreadsheets/d/sheet-id/edit",
            order_sheet_backup_hour=1,
            order_sheet_backup_minute=23,
            celery_timezone="Asia/Ho_Chi_Minh",
        )
    )
    entry = schedule["export-order-sheet-backup"]
    assert entry["task"] == "app.workers.order_sheet_backup_tasks.export_order_sheet_backup"
    assert entry["schedule"]._orig_hour == 1
    assert entry["schedule"]._orig_minute == 23
    assert (
        celery_app.conf.task_routes[
            "app.workers.order_sheet_backup_tasks.export_order_sheet_backup"
        ]["queue"]
        == "celery"
    )

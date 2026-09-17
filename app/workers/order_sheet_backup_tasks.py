from __future__ import annotations

import logging

from app.adapters.db.session import SessionLocal
from app.adapters.google.sheets_adapter import GoogleSheetsAdapter
from app.application.order_sheet_backup import (
    OrderSheetExportError,
    export_order_sheet_snapshot,
)
from app.config import get_settings
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.order_sheet_backup_tasks.export_order_sheet_backup",
    max_retries=5,
)
def export_order_sheet_backup_task(self) -> dict:
    """Scheduled one-way report export. It never imports or mutates order state."""
    settings = get_settings()
    if not settings.order_sheet_backup_enabled:
        logger.info("order sheet backup skipped because it is disabled")
        return {"status": "skipped", "reason": "disabled"}

    session = SessionLocal()
    try:
        result = export_order_sheet_snapshot(
            session,
            lambda: GoogleSheetsAdapter(credentials_path=settings.google_service_account_file),
            sheet_url=settings.google_sheets_order_backup_url,
            tab_name=settings.google_sheets_order_backup_tab,
            timezone_name=settings.celery_timezone,
        )
        logger.info("order sheet backup completed: rows_written=%s", result["rows_written"])
        return result
    except OrderSheetExportError as exc:
        if exc.retryable:
            countdown = min(60 * (2 ** self.request.retries), 30 * 60)
            logger.warning(
                "order sheet backup transient failure (%s), retrying in %ss",
                exc.error_class.value,
                countdown,
            )
            raise self.retry(exc=exc, countdown=countdown) from exc
        logger.error("order sheet backup permanently failed: %s", exc.error_class.value)
        raise
    finally:
        session.close()

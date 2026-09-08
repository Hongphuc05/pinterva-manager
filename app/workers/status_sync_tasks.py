from __future__ import annotations

import logging

from app.adapters.db.session import SessionLocal
from app.application.status_sync import sync_all_platforms
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.status_sync_tasks.sync_order_statuses")
def sync_order_statuses() -> None:
    """Celery Beat entry point for the read-only Printerval-status mirror. Pure HTTP
    (no Playwright/browser) — every active, credentialed platform, one at a time, so
    one platform's failure never blocks the others (see sync_all_platforms)."""
    logger.disabled = False  # see crawl_tasks.crawl_and_claim's identical ponytail note
    session = SessionLocal()
    try:
        results = sync_all_platforms(session)
        logger.info("sync_order_statuses cycle results: %s", results)
    except Exception:
        logger.exception("sync_order_statuses: unexpected exception mid-run")
    finally:
        session.close()

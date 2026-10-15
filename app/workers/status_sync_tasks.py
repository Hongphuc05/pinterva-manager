from __future__ import annotations

import logging

from app.adapters.db.session import SessionLocal
from app.application.status_sync import (
    NIGHTLY_SYNC_WINDOW,
    RECENT_SYNC_WINDOW,
    reclaim_stale_platform_sync_leases,
    sync_all_platforms,
    sync_all_platforms_created_since,
)
from app.application.sync_jobs import (
    reclaim_stale_sync_jobs as reclaim_stale_sync_job_records,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="app.workers.status_sync_tasks.sync_order_statuses")
def sync_order_statuses(self) -> None:
    """Celery Beat entry point for the read-only Printerval-status mirror. Pure HTTP
    (no Playwright/browser) — every active, credentialed platform, one at a time, so
    one platform's failure never blocks the others (see sync_all_platforms)."""
    logger.disabled = False  # see crawl_tasks.crawl_and_claim's identical ponytail note
    session = SessionLocal()
    try:
        results = sync_all_platforms(session, worker_task_id=self.request.id)
        logger.info("sync_order_statuses cycle results: %s", results)
    except Exception:
        logger.exception("sync_order_statuses: unexpected exception mid-run")
    finally:
        session.close()


def _sync_created_within(task_id: str, window, label: str) -> None:
    logger.disabled = False
    session = SessionLocal()
    try:
        results = sync_all_platforms_created_since(session, window=window, worker_task_id=task_id)
        logger.info("%s cycle results: %s", label, results)
    except Exception:
        logger.exception("%s: unexpected exception mid-run", label)
    finally:
        session.close()


@celery_app.task(bind=True, name="app.workers.status_sync_tasks.sync_recent_order_statuses")
def sync_recent_order_statuses(self) -> None:
    """Half-hourly read-only refresh of orders created in the last 7 days."""
    _sync_created_within(self.request.id, RECENT_SYNC_WINDOW, "sync_recent_order_statuses")


@celery_app.task(bind=True, name="app.workers.status_sync_tasks.sync_nightly_order_statuses")
def sync_nightly_order_statuses(self) -> None:
    """02:00 read-only refresh of orders created in the last 60 days."""
    _sync_created_within(self.request.id, NIGHTLY_SYNC_WINDOW, "sync_nightly_order_statuses")


@celery_app.task(name="app.workers.status_sync_tasks.reclaim_stale_sync_jobs")
def reclaim_stale_sync_jobs_task() -> None:
    """Close durable manual sync jobs whose worker stopped heartbeating."""
    session = SessionLocal()
    try:
        reclaimed_jobs = reclaim_stale_sync_job_records(session)
        reclaimed_leases = reclaim_stale_platform_sync_leases(session)
        from app.application.printerval_assignment_requests import fail_stuck_requests

        stuck_requests = fail_stuck_requests(session)
        if stuck_requests:
            logger.warning("Ended %s stuck Printerval assignment request(s) as failed", stuck_requests)
        if reclaimed_jobs or reclaimed_leases:
            logger.warning(
                "Reclaimed %s stale sync job(s) and %s stale platform lease(s)",
                reclaimed_jobs,
                reclaimed_leases,
            )
    except Exception:
        logger.exception("reclaim_stale_sync_jobs: unexpected exception")
    finally:
        session.close()

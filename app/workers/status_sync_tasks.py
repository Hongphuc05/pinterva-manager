from __future__ import annotations

import logging

from app.adapters.db.session import SessionLocal
from app.application.status_sync import (
    reclaim_stale_platform_sync_leases,
    sync_all_platforms,
    sync_all_platforms_full_database,
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


@celery_app.task(bind=True, name="app.workers.status_sync_tasks.sync_full_database_order_statuses")
def sync_full_database_order_statuses(self) -> None:
    """Thirty-minute read-only reconciliation of all orders already in our database."""
    logger.disabled = False
    session = SessionLocal()
    try:
        results = sync_all_platforms_full_database(session, worker_task_id=self.request.id)
        logger.info("sync_full_database_order_statuses cycle results: %s", results)
    except Exception:
        logger.exception("sync_full_database_order_statuses: unexpected exception mid-run")
    finally:
        session.close()


@celery_app.task(name="app.workers.status_sync_tasks.reclaim_stale_sync_jobs")
def reclaim_stale_sync_jobs_task() -> None:
    """Close durable manual sync jobs whose worker stopped heartbeating."""
    session = SessionLocal()
    try:
        reclaimed_jobs = reclaim_stale_sync_job_records(session)
        reclaimed_leases = reclaim_stale_platform_sync_leases(session)
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

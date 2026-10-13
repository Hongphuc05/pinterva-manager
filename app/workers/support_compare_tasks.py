from __future__ import annotations

import logging

from app.adapters.db.session import SessionLocal
from app.application.support_compare import notify_completed_support_compare_jobs
from app.config import get_settings
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.support_compare_tasks.notify_support_duplicate_candidates")
def notify_support_duplicate_candidates() -> int:
    """Deliver local-worker completion reports via Telegram.

    Duplicate pairs are no longer pushed from here: Support sends a lot's chosen pairs on demand
    from the web (``POST /support-review/jobs/{id}/send``).
    """
    settings = get_settings()
    if not settings.support_compare_enabled:
        return 0
    session = SessionLocal()
    try:
        job_count = notify_completed_support_compare_jobs(
            session,
            limit=settings.support_compare_batch_limit,
        )
        logger.info("notified %s local comparison reports", job_count)
        return job_count
    except Exception:
        session.rollback()
        logger.exception("support comparison Telegram notification failed")
        return 0
    finally:
        session.close()

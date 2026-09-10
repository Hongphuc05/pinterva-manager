from __future__ import annotations

import uuid

from app.adapters.db.session import SessionLocal
from app.application.sync_jobs import run_status_sync_job
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.sync_job_tasks.run_status_sync_job")
def run_status_sync_job_task(job_id: str) -> None:
    session = SessionLocal()
    try:
        run_status_sync_job(session, uuid.UUID(job_id))
    finally:
        session.close()

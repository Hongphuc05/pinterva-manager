from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.db.models import Order, Platform, SyncJob, User
from app.adapters.db.session import SessionLocal
from app.api.deps import get_current_platform_id, get_current_user, get_db, require_role
from app.application.sync_jobs import (
    ACTIVE_STATUSES,
    create_or_get_status_sync_job,
    run_status_sync_job,
)

router = APIRouter(prefix="/sync-jobs", tags=["sync-jobs"])


class CreateSyncJobRequest(BaseModel):
    type: Literal["status_sync"]
    # The browser resolves the current tab/filter to an immutable order-ID snapshot
    # before submitting. This avoids a job unexpectedly touching orders that move
    # into or out of a mutable filter while it is queued.
    order_ids: list[str] | None = Field(default=None, max_length=500)


class SyncJobOut(BaseModel):
    id: uuid.UUID
    type: str
    status: str
    total: int
    processed: int
    updated: int
    failed: int
    message: str | None
    error_summary: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


def _out(job: SyncJob) -> SyncJobOut:
    return SyncJobOut(
        id=job.id,
        type=job.job_type,
        status=job.status,
        total=job.total,
        processed=job.processed,
        updated=job.updated,
        failed=job.failed,
        message=job.message,
        error_summary=job.error_summary,
        started_at=job.started_at,
        finished_at=job.finished_at,
        created_at=job.created_at,
    )


def _dispatch_status_job(job_id: uuid.UUID) -> None:
    try:
        from app.workers.sync_job_tasks import run_status_sync_job_task

        run_status_sync_job_task.delay(str(job_id))
    except Exception:
        # Local development remains usable without a Celery worker. Production uses
        # the queue and never depends on this fallback for durability.
        def run_local() -> None:
            session = SessionLocal()
            try:
                run_status_sync_job(session, job_id)
            finally:
                session.close()

        threading.Thread(target=run_local, daemon=True).start()


@router.post("", response_model=SyncJobOut, status_code=status.HTTP_202_ACCEPTED)
def create_sync_job(
    payload: CreateSyncJobRequest,
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    platform = db.get(Platform, platform_id)
    if platform is None or not (platform.account_password or platform.session_cookie):
        raise HTTPException(status.HTTP_409_CONFLICT, "Platform chưa có thông tin xác thực Printerval.")
    if not platform.team_outsource:
        raise HTTPException(status.HTTP_409_CONFLICT, "Platform chưa có Team Outsource Printerval.")

    requested_order_ids = payload.order_ids or []
    try:
        parsed_ids = [uuid.UUID(value) for value in requested_order_ids]
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Order ID không hợp lệ.") from exc
    if len(set(parsed_ids)) != len(parsed_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Danh sách order bị trùng.")
    if parsed_ids:
        owned_count = (
            db.query(Order)
            .filter(Order.platform_id == platform_id, Order.id.in_(parsed_ids))
            .count()
        )
        if owned_count != len(parsed_ids):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Có order không thuộc platform đang chọn.")

    job, created = create_or_get_status_sync_job(
        db,
        platform=platform,
        actor=user,
        order_ids=[str(value) for value in parsed_ids],
        filters=None,
    )
    if created:
        _dispatch_status_job(job.id)
    return _out(job)


@router.get("/current", response_model=SyncJobOut | None)
def get_current_sync_job(
    user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    job = (
        db.query(SyncJob)
        .filter(SyncJob.platform_id == platform_id)
        .order_by(
            SyncJob.status.in_(ACTIVE_STATUSES).desc(),
            SyncJob.created_at.desc(),
        )
        .first()
    )
    return _out(job) if job else None


@router.get("/{job_id}", response_model=SyncJobOut)
def get_sync_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    job = db.get(SyncJob, job_id)
    if job is None or job.platform_id != platform_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy sync job.")
    return _out(job)

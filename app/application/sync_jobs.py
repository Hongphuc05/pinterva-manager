from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.adapters.db.models import Order, Platform, SyncJob, User
from app.application.status_sync import sync_selected_order_statuses

STATUS_SYNC = "status_sync"
ACTIVE_STATUSES = ("queued", "running")


def scope_fingerprint(job_type: str, order_ids: list[str], filters: dict | None) -> str:
    payload = {"type": job_type, "order_ids": sorted(order_ids), "filters": filters or {}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def create_or_get_status_sync_job(
    session: Session,
    *,
    platform: Platform,
    actor: User,
    order_ids: list[str] | None,
    filters: dict | None,
) -> tuple[SyncJob, bool]:
    normalized_ids = sorted(set(order_ids or []))
    fingerprint = scope_fingerprint(STATUS_SYNC, normalized_ids, filters)
    existing = (
        session.query(SyncJob)
        .filter(
            SyncJob.platform_id == platform.id,
            SyncJob.job_type == STATUS_SYNC,
            SyncJob.scope_fingerprint == fingerprint,
            SyncJob.status.in_(ACTIVE_STATUSES),
        )
        .order_by(SyncJob.created_at.desc())
        .first()
    )
    if existing is not None:
        return existing, False

    job = SyncJob(
        platform_id=platform.id,
        created_by_id=actor.id,
        job_type=STATUS_SYNC,
        scope_fingerprint=fingerprint,
        order_ids=normalized_ids or None,
        filters=filters or None,
        message="Đang chờ đồng bộ trạng thái Printerval.",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job, True


def run_status_sync_job(session: Session, job_id: uuid.UUID) -> SyncJob:
    job = session.get(SyncJob, job_id)
    if job is None:
        raise ValueError("Không tìm thấy sync job")
    if job.status not in ACTIVE_STATUSES:
        return job
    platform = session.get(Platform, job.platform_id)
    if platform is None:
        job.status = "failed"
        job.error_summary = "Platform không còn tồn tại."
        job.finished_at = datetime.now(UTC)
        session.commit()
        return job

    job.status = "running"
    job.started_at = job.started_at or datetime.now(UTC)
    session.commit()
    try:
        query = session.query(Order).filter(Order.platform_id == platform.id)
        if job.order_ids:
            ids = [uuid.UUID(value) for value in job.order_ids]
            query = query.filter(Order.id.in_(ids))
        orders = query.all()
        job.total = len(orders)
        session.commit()
        result = sync_selected_order_statuses(session, platform, orders, actor_id=job.created_by_id)
        job.processed = result["checked"]
        job.updated = result["updated"]
        job.failed = result["failed"]
        job.status = "succeeded"
        job.message = f"Đã kiểm tra {job.processed}/{job.total} đơn; cập nhật {job.updated}."
        job.finished_at = datetime.now(UTC)
        session.commit()
    except Exception as exc:
        session.rollback()
        job = session.get(SyncJob, job_id)
        assert job is not None
        job.status = "failed"
        job.error_summary = str(exc)[:1024]
        job.finished_at = datetime.now(UTC)
        session.commit()
    return job

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from datetime import UTC, datetime, timedelta
from time import monotonic

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.db.models import Order, Platform, SyncJob, User
from app.adapters.db.session import SessionLocal
from app.adapters.printerval.api_adapter import PrintervalApiAdapter
from app.adapters.printerval.api_client import PrintervalApiClient
from app.application.status_sync import (
    SyncLeaseLost,
    reconcile_active_platform_orders,
    sync_selected_order_statuses,
)
from app.config import get_settings

STATUS_SYNC = "status_sync"
ACTIVE_STATUSES = ("queued", "running")
logger = logging.getLogger(__name__)


def scope_fingerprint(job_type: str, order_ids: list[str] | None, filters: dict | None) -> str:
    ids_part = sorted(order_ids) if order_ids is not None else "ALL"
    payload = {"type": job_type, "order_ids": ids_part, "filters": filters or {}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def create_or_get_status_sync_job(
    session: Session,
    *,
    platform: Platform,
    actor: User,
    order_ids: list[str] | None,
    filters: dict | None,
) -> tuple[SyncJob, bool]:
    normalized_ids = sorted(set(order_ids)) if order_ids is not None else None
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
        order_ids=normalized_ids,
        filters=filters or None,
        message="Đang chờ đồng bộ trạng thái Printerval.",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job, True


def _job_progress_message(progress: dict, *, total: int | None) -> str:
    phase = str(progress.get("phase") or "processing")
    processed = int(progress.get("processed") or 0)
    if total:
        return f"Đang {phase}: {processed}/{total} đơn."
    return f"Đang {phase}: đã xử lý {processed} đơn."


class _SyncJobProgressReporter:
    """Persist job progress and keep it alive while an external request is pending."""

    def __init__(self, job_id: uuid.UUID, worker_task_id: str) -> None:
        self.job_id = job_id
        self.worker_task_id = worker_task_id
        self._progress: dict = {"phase": "starting", "processed": 0, "updated": 0, "failed": 0}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._lease_lost = False
        self._thread: threading.Thread | None = None
        self._last_sent_at = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"sync-job-heartbeat-{self.job_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1, get_settings().status_sync_heartbeat_interval_seconds + 1))

    def _heartbeat_loop(self) -> None:
        interval = get_settings().status_sync_heartbeat_interval_seconds
        while not self._stop_event.wait(interval):
            if not self.report(force=True):
                return

    def __call__(self, progress: dict) -> bool:
        return self.report(progress)

    def report(self, progress: dict, *, force: bool = False) -> bool:
        with self._lock:
            if self._lease_lost:
                return False
            self._progress = dict(progress)
        now_monotonic = monotonic()
        interval = get_settings().status_sync_heartbeat_interval_seconds
        if not force and now_monotonic - self._last_sent_at < interval:
            return True
        self._last_sent_at = now_monotonic
        return self._persist(force=force)

    def _persist(self, *, force: bool = False) -> bool:
        # ``force`` is kept in the signature so the heartbeat loop and progress
        # callbacks have the same interface. Every callback is cheap enough to
        # persist; the loop is what matters for an HTTP call with no result yet.
        del force
        with self._lock:
            if self._lease_lost:
                return False
            progress = dict(self._progress)
        heartbeat_session = SessionLocal()
        try:
            job = heartbeat_session.get(SyncJob, self.job_id)
            if (
                job is None
                or job.status not in ACTIVE_STATUSES
                or job.worker_task_id != self.worker_task_id
            ):
                heartbeat_session.rollback()
                with self._lock:
                    self._lease_lost = True
                return False
            raw_total = progress.get("total")
            total = int(raw_total) if isinstance(raw_total, int) and raw_total >= 0 else job.total
            job.total = total
            job.processed = int(progress.get("processed") or 0)
            job.updated = int(progress.get("updated") or 0)
            job.failed = int(progress.get("failed") or 0)
            job.progress_phase = str(progress.get("phase") or "processing")
            current_order_code = progress.get("current_order_code")
            job.current_order_code = str(current_order_code)[:64] if current_order_code else None
            job.last_heartbeat_at = datetime.now(UTC)
            job.message = _job_progress_message(progress, total=total or None)
            heartbeat_session.commit()
            return True
        except Exception:
            heartbeat_session.rollback()
            logger.exception("Unable to persist sync-job heartbeat for %s", self.job_id)
            return True
        finally:
            heartbeat_session.close()


def reclaim_stale_sync_jobs(session: Session) -> int:
    """Mark queued/running jobs failed only after their heartbeat is stale.

    A worker replacement during deploy must not leave a job in ``running`` forever.
    This watchdog is intentionally separate from the read-only status API: polling
    the dashboard never mutates job state.
    """
    now = datetime.now(UTC)
    stale_before = now - timedelta(seconds=get_settings().status_sync_heartbeat_stale_seconds)
    jobs = session.execute(
        select(SyncJob)
        .where(SyncJob.status.in_(ACTIVE_STATUSES))
        .with_for_update()
    ).scalars().all()
    reclaimed = 0
    for job in jobs:
        liveness_at = job.last_heartbeat_at or job.started_at or job.created_at
        if liveness_at is None or liveness_at >= stale_before:
            continue
        job.status = "failed"
        job.finished_at = now
        job.last_heartbeat_at = now
        job.progress_phase = "failed"
        job.error_summary = (
            "Worker không còn heartbeat; tác vụ đã được đánh dấu thất bại để không bị kẹt."
        )
        job.message = (
            f"Đã dừng tác vụ từ worker {job.worker_task_id or 'không xác định'} "
            "do mất heartbeat."
        )
        reclaimed += 1
    if reclaimed:
        session.commit()
    return reclaimed


def run_status_sync_job(
    session: Session,
    job_id: uuid.UUID,
    *,
    worker_task_id: str | None = None,
) -> SyncJob:
    job = session.execute(
        select(SyncJob).where(SyncJob.id == job_id).with_for_update()
    ).scalar_one_or_none()
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

    effective_task_id = worker_task_id or f"local:{uuid.uuid4()}"
    job.status = "running"
    job.started_at = job.started_at or datetime.now(UTC)
    job.worker_task_id = effective_task_id
    job.last_heartbeat_at = datetime.now(UTC)
    job.progress_phase = "starting"
    job.current_order_code = None
    job.message = "Đang khởi động đồng bộ trạng thái Printerval."
    session.commit()

    reporter = _SyncJobProgressReporter(job_id, effective_task_id)
    if not reporter.report(
        {
            "phase": "starting",
            "processed": 0,
            "total": job.total or None,
            "updated": 0,
            "failed": 0,
        },
        force=True,
    ):
        raise SyncLeaseLost("Sync job lease was reclaimed before work started.")
    reporter.start()

    try:
        if job.order_ids is not None:
            ids = [uuid.UUID(value) for value in job.order_ids]
            query = session.query(Order).filter(Order.platform_id == platform.id, Order.id.in_(ids))
            orders = query.all()
            job.total = len(orders)
            session.commit()
            result = sync_selected_order_statuses(
                session,
                platform,
                orders,
                actor_id=job.created_by_id,
                progress_callback=reporter,
            )
            job.processed = result["checked"]
            job.updated = result["updated"]
            job.failed = result.get("failed", 0)
        else:
            client = PrintervalApiClient(
                base_url="https://printerval.com",
                username=platform.account_username,
                password=platform.account_password,
                team_outsource=platform.team_outsource,
                session_cookie=platform.session_cookie,
            )
            try:
                result = reconcile_active_platform_orders(
                    session,
                    platform,
                    adapter=PrintervalApiAdapter(api_client=client, download_images=False),
                    actor_id=job.created_by_id,
                    progress_callback=reporter,
                )
            finally:
                client.close()
            job.processed = result.get("checked", 0)
            job.total = result.get("checked", 0)
            job.updated = result.get("updated", 0)
            job.failed = 0

        job.status = "succeeded"
        job.message = f"Đã kiểm tra {job.processed}/{job.total} đơn; cập nhật {job.updated}."
        job.progress_phase = "completed"
        job.current_order_code = None
        job.last_heartbeat_at = datetime.now(UTC)
        job.finished_at = datetime.now(UTC)
        reporter.stop()
        session.commit()
    except Exception as exc:
        reporter.stop()
        session.rollback()
        job = session.get(SyncJob, job_id)
        assert job is not None
        # A watchdog may already have reclaimed this row. The old worker must not
        # turn that terminal record back into a success/failure from stale state.
        if job.status in ACTIVE_STATUSES and job.worker_task_id == effective_task_id:
            job.status = "failed"
            job.error_summary = str(exc)[:1024]
            job.progress_phase = "failed"
            job.last_heartbeat_at = datetime.now(UTC)
            job.finished_at = datetime.now(UTC)
            session.commit()
    finally:
        reporter.stop()
    return job

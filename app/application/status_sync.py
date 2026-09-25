"""Read-only mirror of Printerval's own order status into Order.printerval_status.

This is deliberately one-directional (Printerval -> us) and never writes anything back
to the site — per claude.md §2 invariant #5 and §3 C5, only a QC Approve decision's own
job is ever allowed to write order state to Printerval. This sync exists purely so the
web dashboard can show an accurate "what does Printerval currently say" column without
an operator having to open the site themselves.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.adapters.db.models import Order, Platform, PlatformSyncState, WorkflowEvent
from app.adapters.db.session import SessionLocal
from app.adapters.printerval.api_adapter import PrintervalApiAdapter
from app.adapters.printerval.api_client import PrintervalApiClient
from app.adapters.printerval.interface import ALL_JOB_TYPES, PrintervalAdapter
from app.adapters.printerval.row_mapper import parse_order_detail_from_row
from app.application.crawl import (
    _apply_order_detail_result,
    apply_crawled_product_gallery,
    export_platform_orders_csv,
)
from app.config import get_settings
from app.domain.models import OrderState

# Printerval's HTTP endpoint does not support the UI's combined
# ``waiting+doing+fix`` label: it silently returns an empty page.  The scheduled
# mirror therefore reads these two real source filters independently.  Waiting
# is discovered only through Admin's explicit crawl, never by auto-sync.
ACTIVE_PRINTERVAL_STATUS_FILTERS = ("doing", "fix")

ProgressCallback = Callable[[dict[str, Any]], object]


class SyncLeaseLost(RuntimeError):
    """The worker no longer owns the platform sync run it started."""


def _emit_progress(callback: ProgressCallback | None, progress: dict[str, Any]) -> None:
    if callback is None:
        return
    if callback(progress) is False:
        raise SyncLeaseLost("Platform sync lease was reclaimed by another worker.")


class _PlatformSyncProgressReporter:
    """Persist throttled heartbeats in an independent DB session.

    The sync worker's main SQLAlchemy session may be inside a per-order transaction
    or waiting on the external HTTP API. A separate short-lived session makes the
    heartbeat durable in both cases and prevents a rollback in order processing from
    erasing liveness information.
    """

    def __init__(self, platform_id: UUID, run_token: UUID) -> None:
        self.platform_id = platform_id
        self.run_token = run_token
        self._last_sent_at = 0.0
        self._progress: dict[str, Any] = {
            "phase": "starting",
            "processed": 0,
            "total": None,
            "updated": 0,
            "failed": 0,
        }
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._lease_lost = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"status-sync-heartbeat-{self.platform_id}",
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

    def __call__(self, progress: dict[str, Any]) -> bool:
        return self.report(progress)

    def report(self, progress: dict[str, Any], *, force: bool = False) -> bool:
        with self._lock:
            if self._lease_lost:
                return False
            self._progress = dict(progress)

        now_monotonic = monotonic()
        interval = get_settings().status_sync_heartbeat_interval_seconds
        if not force and now_monotonic - self._last_sent_at < interval:
            return True
        self._last_sent_at = now_monotonic
        return self._persist_heartbeat()

    def _persist_heartbeat(self) -> bool:
        with self._lock:
            if self._lease_lost:
                return False
            progress = dict(self._progress)
        heartbeat_session = SessionLocal()
        try:
            state = heartbeat_session.execute(
                select(PlatformSyncState)
                .where(
                    PlatformSyncState.platform_id == self.platform_id,
                    PlatformSyncState.run_token == self.run_token,
                    PlatformSyncState.is_running.is_(True),
                )
            ).scalar_one_or_none()
            if state is None:
                heartbeat_session.rollback()
                with self._lock:
                    self._lease_lost = True
                return False
            state.last_heartbeat_at = datetime.now(UTC)
            state.progress = progress
            heartbeat_session.commit()
            return True
        except Exception:
            heartbeat_session.rollback()
            logger.exception("Unable to persist status-sync heartbeat for platform %s", self.platform_id)
            # A transient heartbeat write failure must not abort a healthy external
            # read. The next progress callback will retry; only a confirmed missing
            # run token means that another worker reclaimed this run.
            return True
        finally:
            heartbeat_session.close()


def _platform_sync_heartbeat_stale_after() -> timedelta:
    return timedelta(seconds=get_settings().status_sync_heartbeat_stale_seconds)


def reclaim_stale_platform_sync_leases(session: Session) -> int:
    """Close platform leases whose worker stopped renewing its heartbeat."""
    now_utc = datetime.now(UTC)
    stale_before = now_utc - _platform_sync_heartbeat_stale_after()
    states = session.execute(
        select(PlatformSyncState)
        .where(PlatformSyncState.is_running.is_(True))
        .with_for_update()
    ).scalars().all()
    reclaimed = 0
    for state in states:
        liveness_at = state.last_heartbeat_at or state.last_started_at
        if liveness_at is None or liveness_at >= stale_before:
            continue
        state.is_running = False
        state.last_finished_at = now_utc
        state.last_heartbeat_at = now_utc
        state.last_error = (
            "Worker không còn heartbeat; tác vụ đồng bộ đã được đánh dấu thất bại "
            "để có thể chạy lại."
        )
        state.progress = {
            **(state.progress or {}),
            "phase": "failed",
        }
        reclaimed += 1
    if reclaimed:
        session.commit()
    return reclaimed


def _status_guess_order(last_known: str | None) -> tuple[str, ...]:
    """find_order tries statuses in turn until one matches — trying the order's own
    last-known status first resolves in a single HTTP call in the common case (an
    order rarely jumps status between two syncs) instead of always walking the full
    default order."""
    if last_known and last_known in PrintervalApiClient.ORDER_STATUSES:
        rest = [s for s in PrintervalApiClient.ORDER_STATUSES if s != last_known]
        return (last_known, *rest)
    return PrintervalApiClient.ORDER_STATUSES


def _row_designer(row: dict, designer_map: dict[str, str] | None = None) -> str | None:
    """Extract a visible Designer label for display, mapping designer_email when available."""
    attributes = row.get("attributes")
    if isinstance(attributes, dict) and designer_map:
        email = str(attributes.get("designer_email") or "").strip().lower()
        if email in designer_map:
            return designer_map[email]

    for key in ("designer", "designer_name"):
        value = row.get(key)
        if isinstance(value, str) and value.strip() and "@" not in value:
            return value.strip()
    if isinstance(attributes, dict):
        for key in ("designer", "designer_name"):
            value = attributes.get(key)
            if isinstance(value, str) and value.strip() and "@" not in value:
                return value.strip()
    return None


logger = logging.getLogger(__name__)


def _transition_to_fix_from_observation(
    session: Session,
    order: Order,
    *,
    note: str,
    actor_id: object | None,
) -> bool:
    """Apply the existing external-Fix policy while preserving payment state."""
    if order.state == OrderState.REVISION.value:
        if note and note != order.note_outsource:
            order.previous_note_outsource = order.note_outsource
            order.note_outsource = note
            order.fix_approved_by_admin = False
            order.fix_rejected_by_admin = False
            order.designer_note = ""
            order.designer_note_released_for_fix = False
            order.suppress_note_outsource_for_designer = True
            return True
        return False

    old_state = order.state
    order.state = OrderState.REVISION.value
    order.status_changed_at = datetime.now(UTC)
    order.fix_return_count += 1
    order.previous_note_outsource = order.note_outsource
    if note:
        order.note_outsource = note
    order.fix_approved_by_admin = False
    order.fix_rejected_by_admin = False
    order.fix_deadline_at = None
    order.designer_note = ""
    order.designer_note_released_for_fix = False
    order.suppress_note_outsource_for_designer = True
    session.add(
        WorkflowEvent(
            order_id=order.id,
            from_state=old_state,
            to_state=OrderState.REVISION.value,
            actor_id=actor_id,
            evidence={
                "action": "REQUEST_FIX",
                "actor_name": "Printerval",
                "description": f"Printerval trả về Fix với note: {note or 'Không có note'}",
                "note_outsource": note,
            },
        )
    )
    return True


def reconcile_active_platform_orders(
    session: Session,
    platform: Platform,
    *,
    adapter: PrintervalAdapter,
    actor_id: object | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, int]:
    """Mirror tracked Printerval Doing and Fix cards from independent filters.

    Waiting is intentionally excluded: Admin's manual crawl is the only source
    allowed to create new Tacahu orders. Unknown Doing/Fix cards are skipped, so a
    historical Printerval backlog cannot become Tacahu work. Absence from either
    feed never implies cancellation because Review and Done are not queried here.
    """
    seen: set[str] = set()
    checked = added = updated = skipped_untracked = failed = 0
    _emit_progress(
        progress_callback,
        {
            "phase": "discovering",
            "processed": 0,
            "total": None,
            "updated": 0,
            "failed": 0,
        },
    )

    def active_summaries():
        for source_status in ACTIVE_PRINTERVAL_STATUS_FILTERS:
            cursor: str | None = None
            page = 0
            while True:
                discovered = adapter.discover_orders(
                    status=source_status,
                    job_type=ALL_JOB_TYPES,
                    limit=100,
                    cursor=cursor,
                    platform_id=str(platform.id),
                )
                if not discovered.success:
                    raise RuntimeError(
                        discovered.error_class or f"Không thể đọc queue {source_status} từ Printerval."
                    )
                yield from discovered.orders
                page += 1
                _emit_progress(
                    progress_callback,
                    {
                        "phase": "discovering",
                        "source_status": source_status,
                        "page": page,
                        "processed": checked,
                        "total": None,
                        "updated": updated,
                        "failed": failed,
                    },
                )
                if not discovered.cursor:
                    break
                cursor = discovered.cursor

    for summary in active_summaries():
        external_order_id = summary.external_order_id
        if external_order_id in seen:
            continue
        seen.add(external_order_id)
        checked += 1
        incoming_status = (summary.status or "").strip().lower()
        if incoming_status not in ACTIVE_PRINTERVAL_STATUS_FILTERS:
            failed += 1
            logger.warning("Ignoring unexpected active-feed status %r for %s", incoming_status, external_order_id)
            continue

        try:
            order = (
                session.query(Order)
                .filter(Order.platform_id == platform.id, Order.external_order_id == external_order_id)
                .one_or_none()
            )
            now_utc = datetime.now(UTC)
            if order is None:
                skipped_untracked += 1
                continue

            changed = False
            for field, value in (
                    ("product_name", summary.product_name),
                    ("thumbnail_url", summary.thumbnail_url),
                    ("sku", summary.sku),
                    ("product_category", summary.product_category),
                    ("product_skus", summary.product_skus),
            ):
                if value is not None and value != getattr(order, field):
                    setattr(order, field, value)
                    changed = True
            if summary.product_image_urls:
                previous_images = list(order.product_image_urls or [])
                apply_crawled_product_gallery(order, summary.product_image_urls)
                changed = changed or previous_images != list(order.product_image_urls or [])
            if summary.designer != order.printerval_designer:
                order.printerval_designer = summary.designer
                order.printerval_designer_synced_at = now_utc
                changed = True
            if incoming_status != (order.printerval_status or "").lower():
                order.printerval_status = incoming_status
                changed = True

            entered_fix = incoming_status == "fix" and order.state != OrderState.REVISION.value
            if incoming_status == "fix":
                # ApiAdapter resolves this from its active-feed cache, so a
                # changed Fix does not add a per-order source lookup.
                detail = adapter.get_order_detail(external_order_id, platform_id=str(platform.id))
                note = detail.note_outsource.strip() if detail.success else ""
                changed = _transition_to_fix_from_observation(
                    session, order, note=note, actor_id=actor_id
                ) or changed

            if changed:
                order.printerval_status_synced_at = now_utc
                session.commit()
                updated += 1
                if entered_fix:
                    _dispatch_admin_fix_notifications(session, order)
            else:
                session.rollback()
            _emit_progress(
                progress_callback,
                {
                    "phase": "saving",
                    "processed": checked,
                    "total": None,
                    "updated": updated,
                    "failed": failed,
                    "current_order_code": external_order_id,
                },
            )
        except SyncLeaseLost:
            raise
        except Exception as exc:
            session.rollback()
            failed += 1
            logger.warning("Active Printerval reconciliation failed for %s: %s", external_order_id, exc)

    if updated:
        export_platform_orders_csv(session, platform.id)
    result = {
        "checked": checked,
        "added": added,
        "updated": updated,
        "skipped_untracked": skipped_untracked,
        "failed": failed,
    }
    _emit_progress(
        progress_callback,
        {
            "phase": "completed",
            "processed": checked,
            "total": checked,
            "updated": updated,
            "failed": failed,
        },
    )
    return result


def _dispatch_admin_fix_notifications(session: Session, order: Order) -> None:
    """Dispatch Fix notifications after the order transition is committed."""
    try:
        from app.application.telegram_service import resolve_tacahu_designer_name
        from app.workers.telegram_tasks import (
            async_notify_admin_excessive_fix,
            async_notify_admin_new_fix,
            safe_dispatch_telegram_task,
        )

        safe_dispatch_telegram_task(async_notify_admin_new_fix, str(order.id))
        if order.fix_return_count >= 3:
            designer_label = resolve_tacahu_designer_name(session, order)
            safe_dispatch_telegram_task(
                async_notify_admin_excessive_fix,
                str(order.id),
                designer_label,
                order.fix_return_count,
            )
    except Exception:
        logger.exception("Failed to dispatch Telegram Fix notification for order %s", order.id)


def sync_selected_order_statuses(
    session: Session,
    platform: Platform,
    orders: list[Order],
    *,
    actor_id: object | None = None,
    api_client: PrintervalApiClient | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, int]:
    """Fast, manually requested status mirror for one visible UI tab.

    This deliberately does *not* re-crawl source/SKU/detail. Each chosen order
    is looked up by its own DJ code, first using its last observed Printerval state.
    Reads run with a small, configurable concurrency cap; ORM writes remain on this
    caller thread and commit per order with optimistic-lock retry.
    """
    if not orders:
        return {"checked": 0, "updated": 0, "not_found": 0, "failed": 0}

    owns_client = api_client is None
    client = api_client or PrintervalApiClient(
        base_url="https://printerval.com",
        username=platform.account_username,
        password=platform.account_password,
        team_outsource=platform.team_outsource,
        session_cookie=platform.session_cookie,
    )
    rows_by_order_id: dict[object, dict[str, Any] | None] = {}
    failed_order_ids: set[object] = set()
    failed = 0
    try:
        # A single designer-options fetch is cached on the client, before its HTTP
        # connection is used concurrently for read-only order searches.
        designer_map = client.get_designer_map()
        worker_count = min(max(1, get_settings().printerval_manual_sync_concurrency), len(orders))
        _emit_progress(
            progress_callback,
            {
                "phase": "fetching",
                "processed": 0,
                "total": len(orders),
                "updated": 0,
                "failed": 0,
            },
        )

        # Never let worker threads touch ORM state.  Their only job is HTTP
        # lookup; all database reads/writes stay on this caller thread.
        lookups = [
            (order.id, order.external_order_id, order.printerval_status)
            for order in orders
        ]

        def find(
            order_id: object, external_order_id: str, printerval_status: str | None
        ) -> tuple[object, dict[str, Any] | None]:
            return order_id, client.find_order(
                external_order_id,
                statuses=_status_guess_order(printerval_status),
            )

        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="printerval-status") as pool:
            futures = {
                pool.submit(find, order_id, external_order_id, printerval_status): (
                    order_id,
                    external_order_id,
                )
                for order_id, external_order_id, printerval_status in lookups
            }
            for future in as_completed(futures):
                order_id, external_order_id = futures[future]
                try:
                    result_order_id, row = future.result()
                    rows_by_order_id[result_order_id] = row
                except Exception as exc:
                    failed += 1
                    failed_order_ids.add(order_id)
                    logger.warning("Manual status sync failed for %s: %s", external_order_id, exc)
                _emit_progress(
                    progress_callback,
                    {
                        "phase": "fetching",
                        "processed": len(rows_by_order_id) + len(failed_order_ids),
                        "total": len(orders),
                        "updated": 0,
                        "failed": failed,
                        "current_order_code": external_order_id,
                    },
                )

        updated = 0
        not_found = 0
        for original_order in orders:
            order_id = original_order.id
            row = rows_by_order_id.get(order_id)
            if row is None and order_id not in failed_order_ids:
                not_found += 1

            # Commit each card independently. A concurrent drag, Fix decision or
            # scheduled sync can then only retry this one row, never abort a whole
            # board/tab sync due to SQLAlchemy's Order.version optimistic lock.
            for attempt in range(3):
                try:
                    notify_admin_fix = False
                    session.expire_all()
                    order = session.get(Order, order_id)
                    if order is None:
                        break
                    changed = False
                    now_utc = datetime.now(UTC)

                    if row is None:
                        if order_id not in failed_order_ids and order.printerval_status != "cancelled":
                            order.printerval_status = "cancelled"
                            order.printerval_status_synced_at = now_utc
                            changed = True
                    else:
                        found_status = str(row.get("status") or "").strip()
                        norm_status = found_status.upper()
                        attributes = row.get("attributes") or {}
                        note = str(attributes.get("outsource_note") or row.get("note") or "").strip()
                        old_state = order.state

                        if order.state not in ("WAITING", "OPEN_FOR_ALLOCATION", "DISCOVERED", "PENDING"):
                            # Printerval Done is an external observation, not a payment
                            # decision. A Review card remains in Review until Admin marks
                            # its designer payment, which is the only automatic path to
                            # our internal Done tab.
                            if norm_status == "FIX" and order.state != "REVISION":
                                order.state = "REVISION"
                                order.status_changed_at = now_utc
                                order.fix_return_count += 1
                                order.previous_note_outsource = order.note_outsource
                                if note:
                                    order.note_outsource = note
                                order.fix_approved_by_admin = False
                                order.fix_rejected_by_admin = False
                                order.designer_note = ""
                                order.designer_note_released_for_fix = False
                                order.suppress_note_outsource_for_designer = True
                                session.add(
                                    WorkflowEvent(
                                        order_id=order.id,
                                        from_state=old_state,
                                        to_state="REVISION",
                                        actor_id=actor_id,
                                        evidence={
                                            "action": "REQUEST_FIX",
                                            "actor_name": "Printerval",
                                            "description": f"Printerval trả về Fix với note: {note or 'Không có note'}",
                                            "note_outsource": note,
                                        },
                                    )
                                )
                                changed = True
                                notify_admin_fix = True
                            elif (
                                norm_status == "REVIEW"
                                and order.state == "REVISION"
                                and order.fix_rejected_by_admin
                            ):
                                # Reconcile legacy rows rejected before the local
                                # transition was corrected. Printerval is already
                                # Review, so the Tacahu card must leave Fix too.
                                order.state = "QC_PENDING"
                                order.status_changed_at = now_utc
                                session.add(
                                    WorkflowEvent(
                                        order_id=order.id,
                                        from_state=old_state,
                                        to_state="QC_PENDING",
                                        actor_id=actor_id,
                                        evidence={
                                            "action": "RECONCILE_REJECTED_FIX_TO_REVIEW",
                                            "actor_name": "Printerval",
                                            "description": "Đồng bộ xác nhận đơn đã được trả về Review sau khi Admin từ chối Fix",
                                        },
                                    )
                                )
                                changed = True
                            elif note and norm_status == "FIX" and note != order.note_outsource:
                                # A changed upstream Fix note invalidates any
                                # previously approved local release. Admin must
                                # review it and explicitly write a new note.
                                order.previous_note_outsource = order.note_outsource
                                order.note_outsource = note
                                order.fix_approved_by_admin = False
                                order.fix_rejected_by_admin = False
                                order.designer_note = ""
                                order.designer_note_released_for_fix = False
                                order.suppress_note_outsource_for_designer = True
                                changed = True

                        if found_status and found_status.lower() != (order.printerval_status or "").lower():
                            order.printerval_status = found_status.lower()
                            changed = True
                        elif not found_status and order.printerval_status == "cancelled":
                            order.printerval_status = None
                            changed = True

                        designer = _row_designer(row, designer_map=designer_map)
                        if designer and designer != order.printerval_designer:
                            order.printerval_designer = designer
                            order.printerval_designer_synced_at = now_utc
                            changed = True

                        # Do not turn a read-only observation into a business
                        # revision.  Updating this timestamp on every scan used
                        # to invalidate an operator's just-read order version.
                        if changed:
                            order.printerval_status_synced_at = now_utc

                    session.commit()
                    if notify_admin_fix:
                        _dispatch_admin_fix_notifications(session, order)
                    if changed:
                        updated += 1
                    _emit_progress(
                        progress_callback,
                        {
                            "phase": "saving",
                            "processed": len(orders),
                            "total": len(orders),
                            "updated": updated,
                            "failed": failed,
                            "current_order_code": original_order.external_order_id,
                        },
                    )
                    break
                except SyncLeaseLost:
                    raise
                except StaleDataError:
                    session.rollback()
                    logger.info(
                        "stale_sync_retry order_id=%s attempt=%s",
                        order_id,
                        attempt + 1,
                    )
                    if attempt == 2:
                        failed += 1
                        logger.warning("Manual status sync exhausted concurrent-update retries for %s", order_id)
                except Exception as exc:
                    session.rollback()
                    failed += 1
                    logger.warning("Manual status sync failed while saving %s: %s", order_id, exc)
                    break

        result = {"checked": len(orders), "updated": updated, "not_found": not_found, "failed": failed}
        _emit_progress(
            progress_callback,
            {
                "phase": "completed",
                "processed": len(orders),
                "total": len(orders),
                "updated": updated,
                "failed": failed,
            },
        )
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_client:
            client.close()


def sync_platform_order_statuses(
    session: Session, platform: Platform, api_client: PrintervalApiClient | None = None
) -> dict:
    """Look up each Order we already track for this platform (one find_order call
    each, hinted by its last-known status) and update Order.printerval_status,
    printerval_designer, and full order details (source, SKU data, notes, etc.).

    Deliberately scoped to OUR orders, not a bulk page-through of Printerval's full
    history. Updates are committed per-order with StaleDataError handling so concurrent
    modifications by workers/users do not crash or abort the entire platform sync.
    """
    owns_client = api_client is None
    client = api_client or PrintervalApiClient(
        base_url="https://printerval.com",
        username=platform.account_username,
        password=platform.account_password,
        team_outsource=platform.team_outsource,
        session_cookie=platform.session_cookie,
    )
    try:
        designer_map = client.get_designer_map()
        orders = (
            session.query(Order)
            .filter(Order.platform_id == platform.id)
            .order_by(Order.created_at.desc())
            .all()
        )
        updated = 0
        not_found = 0
        for order in orders:
            try:
                notify_admin_fix = False
                row = client.find_order(
                    order.external_order_id, statuses=_status_guess_order(order.printerval_status)
                )
                if row is None:
                    not_found += 1
                    if order.printerval_status != "cancelled":
                        order.printerval_status = "cancelled"
                        order.printerval_status_synced_at = datetime.now(UTC)
                        session.commit()
                        updated += 1
                    continue
                order_changed = False
                found_status = row.get("status")
                if found_status and found_status != order.printerval_status:
                    order.printerval_status = found_status
                    order_changed = True
                elif not found_status and order.printerval_status == "cancelled":
                    order.printerval_status = None
                    order_changed = True

                norm_st = (found_status or "").upper()
                old_state = order.state
                if norm_st == "FIX" and order.state in (
                    "QC_PENDING", "REVIEW", "RESULT_SUBMITTED", "SUBMITTING_TO_SITE",
                    "IN_PROGRESS", "DOING", "ASSIGNED", "DONE", "CLAIMED_IMPORTED", "COMPLETED",
                ):
                    order.state = "REVISION"
                    order.status_changed_at = datetime.now(UTC)
                    order.fix_return_count += 1
                    order.previous_note_outsource = order.note_outsource
                    attrs = row.get("attributes") or {}
                    found_note = str(attrs.get("outsource_note") or row.get("note") or "").strip()
                    if found_note:
                        order.note_outsource = found_note
                    order.fix_approved_by_admin = False
                    order.fix_rejected_by_admin = False
                    order.designer_note = ""
                    order.designer_note_released_for_fix = False
                    order.suppress_note_outsource_for_designer = True
                    session.add(
                        WorkflowEvent(
                            order_id=order.id,
                            from_state=old_state,
                            to_state="REVISION",
                            evidence={
                                "action": "REQUEST_FIX",
                                "actor_name": "Printerval",
                                "description": "Printerval trả về Fix khi đồng bộ trạng thái",
                                "note_outsource": found_note,
                            },
                        )
                    )
                    notify_admin_fix = True
                    order_changed = True
                elif (
                    norm_st == "REVIEW"
                    and order.state == "REVISION"
                    and order.fix_rejected_by_admin
                ):
                    order.state = "QC_PENDING"
                    order.status_changed_at = datetime.now(UTC)
                    order_changed = True
                # A Printerval Done remains a read-only platform observation.
                # Finance is the only automatic owner of the internal Done state.

                found_designer = _row_designer(row, designer_map=designer_map)
                if found_designer and found_designer != order.printerval_designer:
                    order.printerval_designer = found_designer
                    order.printerval_designer_synced_at = datetime.now(UTC)
                    order_changed = True
                elif not found_designer and order.printerval_designer and "@" in order.printerval_designer:
                    order.printerval_designer = None
                    order.printerval_designer_synced_at = datetime.now(UTC)
                    order_changed = True
                # Re-apply full detail metadata (source files, SKU data, custom config, notes, deadlines).
                detail_result = parse_order_detail_from_row(
                    row, order.external_order_id, platform_id=str(platform.id), download_images=False
                )
                if detail_result.success:
                    _apply_order_detail_result(order, detail_result)
                    order_changed = order_changed or session.is_modified(order, include_collections=False)

                if order_changed:
                    order.printerval_status_synced_at = datetime.now(UTC)
                    updated += 1
                session.commit()
                if notify_admin_fix:
                    _dispatch_admin_fix_notifications(session, order)
            except StaleDataError:
                # Concurrent transaction modified this order; rollback this order and continue
                session.rollback()
                logger.info("stale_sync_skipped order_id=%s", order.id)
                continue
            except Exception as e:
                session.rollback()
                logger.warning("Error syncing order %s: %s", order.external_order_id, e)
                continue

        return {"checked": len(orders), "updated": updated, "not_found": not_found}
    finally:
        if owns_client:
            client.close()


def sync_full_database_platform_orders(
    session: Session,
    platform: Platform,
    *,
    api_client: PrintervalApiClient | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, int]:
    """Refresh Printerval status for every order already tracked for one platform.

    This intentionally reuses the per-order read-only mirror used by tab syncs:
    it does not discover external history or write back to Printerval.  It does,
    however, see a Print Fix for paid Done orders and returns those cards to Fix
    while retaining their payment tag.
    """
    orders = (
        session.query(Order)
        .filter(Order.platform_id == platform.id)
        .order_by(Order.created_at.asc(), Order.id.asc())
        .all()
    )
    return sync_selected_order_statuses(
        session,
        platform,
        orders,
        api_client=api_client,
        progress_callback=progress_callback,
    )


def _claim_platform_sync_lease(
    session: Session,
    platform_id: object,
    *,
    worker_task_id: str,
) -> UUID | None:
    """Atomically claim a per-platform lease, reclaiming only stale heartbeats."""
    now_utc = datetime.now(UTC)
    state = session.execute(
        select(PlatformSyncState)
        .where(PlatformSyncState.platform_id == platform_id)
        .with_for_update()
    ).scalar_one_or_none()
    if state is None:
        state = PlatformSyncState(platform_id=platform_id)
        session.add(state)
        session.flush()

    heartbeat_at = state.last_heartbeat_at or state.last_started_at
    if state.is_running and heartbeat_at and heartbeat_at >= now_utc - _platform_sync_heartbeat_stale_after():
        session.rollback()
        return None

    if state.is_running:
        logger.warning(
            "Reclaiming stale platform sync lease platform=%s task=%s heartbeat_at=%s",
            platform_id,
            state.worker_task_id,
            heartbeat_at,
        )

    run_token = uuid4()
    state.is_running = True
    state.last_started_at = now_utc
    state.worker_task_id = worker_task_id
    state.run_token = run_token
    state.last_heartbeat_at = now_utc
    state.progress = {
        "phase": "starting",
        "processed": 0,
        "total": None,
        "updated": 0,
        "failed": 0,
    }
    state.last_error = None
    session.commit()
    return run_token


def _finish_platform_sync_lease(
    session: Session,
    platform_id: object,
    *,
    run_token: UUID,
    result: dict | None = None,
    error: Exception | None = None,
) -> None:
    state = session.execute(
        select(PlatformSyncState).where(
            PlatformSyncState.platform_id == platform_id,
            PlatformSyncState.run_token == run_token,
            PlatformSyncState.is_running.is_(True),
        )
    ).scalar_one_or_none()
    if state is None:
        session.rollback()
        return
    now_utc = datetime.now(UTC)
    if error is None:
        state.last_result = result
        state.last_error = None
        state.progress = {
            "phase": "completed",
            "processed": (result or {}).get("checked", 0),
            "total": (result or {}).get("checked", 0),
            "updated": (result or {}).get("updated", 0),
            "failed": (result or {}).get("failed", 0),
        }
    else:
        state.last_error = str(error)[:1024]
        state.progress = {
            **(state.progress or {}),
            "phase": "failed",
        }
    state.is_running = False
    state.last_heartbeat_at = now_utc
    state.last_finished_at = now_utc
    session.commit()


def _credentialed_platforms(session: Session) -> list[Platform]:
    return (
        session.query(Platform)
        .filter(
            Platform.is_active.is_(True),
            or_(Platform.account_password.isnot(None), Platform.session_cookie.isnot(None)),
        )
        .all()
    )


def _run_platform_syncs(
    session: Session,
    *,
    run_platform: Callable[[Platform, ProgressCallback], dict],
    worker_task_id: str | None = None,
) -> dict[str, dict]:
    """Run one read-only status operation per credentialed platform, without overlap."""
    results: dict[str, dict] = {}
    effective_task_id = worker_task_id or f"local:{uuid4()}"
    for platform in _credentialed_platforms(session):
        if not platform.team_outsource:
            continue
        run_token = _claim_platform_sync_lease(
            session,
            platform.id,
            worker_task_id=effective_task_id,
        )
        if run_token is None:
            results[str(platform.id)] = {"skipped": 1, "reason": "another_sync_running"}
            continue

        reporter = _PlatformSyncProgressReporter(platform.id, run_token)
        try:
            if not reporter.report(
                {
                    "phase": "starting",
                    "processed": 0,
                    "total": None,
                    "updated": 0,
                    "failed": 0,
                },
                force=True,
            ):
                raise SyncLeaseLost("Platform sync lease was reclaimed before work started.")
            reporter.start()
            result = run_platform(platform, reporter)
            reporter.stop()
            results[str(platform.id)] = result
            _finish_platform_sync_lease(session, platform.id, run_token=run_token, result=result)
        except Exception as exc:
            reporter.stop()
            session.rollback()
            results[str(platform.id)] = {"error": str(exc)}
            try:
                _finish_platform_sync_lease(session, platform.id, run_token=run_token, error=exc)
            except Exception:
                session.rollback()
                logger.exception("Unable to release sync lease for platform %s", platform.id)
        finally:
            reporter.stop()
    return results


def sync_all_platforms(session: Session, *, worker_task_id: str | None = None) -> dict[str, dict]:
    """Reconcile each credentialed platform's compact active Printerval queue."""
    def run_platform(platform: Platform, progress_callback: ProgressCallback) -> dict:
        client = PrintervalApiClient(
            base_url="https://printerval.com",
            username=platform.account_username,
            password=platform.account_password,
            team_outsource=platform.team_outsource,
            session_cookie=platform.session_cookie,
        )
        try:
            return reconcile_active_platform_orders(
                session,
                platform,
                adapter=PrintervalApiAdapter(api_client=client, download_images=False),
                progress_callback=progress_callback,
            )
        finally:
            client.close()

    return _run_platform_syncs(session, run_platform=run_platform, worker_task_id=worker_task_id)


def sync_all_platforms_full_database(
    session: Session,
    *,
    worker_task_id: str | None = None,
) -> dict[str, dict]:
    """Refresh the Printerval status of every tracked order for every platform."""
    def run_platform(platform: Platform, progress_callback: ProgressCallback) -> dict:
        client = PrintervalApiClient(
            base_url="https://printerval.com",
            username=platform.account_username,
            password=platform.account_password,
            team_outsource=platform.team_outsource,
            session_cookie=platform.session_cookie,
        )
        try:
            return sync_full_database_platform_orders(
                session,
                platform,
                api_client=client,
                progress_callback=progress_callback,
            )
        finally:
            client.close()

    return _run_platform_syncs(session, run_platform=run_platform, worker_task_id=worker_task_id)

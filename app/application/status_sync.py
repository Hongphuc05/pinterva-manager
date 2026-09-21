"""Read-only mirror of Printerval's own order status into Order.printerval_status.

This is deliberately one-directional (Printerval -> us) and never writes anything back
to the site — per claude.md §2 invariant #5 and §3 C5, only a QC Approve decision's own
job is ever allowed to write order state to Printerval. This sync exists purely so the
web dashboard can show an accurate "what does Printerval currently say" column without
an operator having to open the site themselves.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.adapters.db.models import Order, Platform, PlatformSyncState, WorkflowEvent
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

# Exact active-queue option exposed by Printerval. It intentionally excludes
# review/done history, so scheduled reconciliation stays bounded as our DB grows.
ACTIVE_PRINTERVAL_STATUS_FILTER = "waiting+doing+fix"


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
) -> dict[str, int]:
    """Mirror only Printerval's active Waiting + Doing + Fix source queue.

    Unknown Waiting cards are imported. Unknown Doing/Fix cards are intentionally
    skipped, preventing historical work from becoming a Tacahu backlog. Absence from
    the active feed never implies cancellation because Review and Done are excluded.
    """
    cursor: str | None = None
    seen: set[str] = set()
    checked = added = updated = skipped_untracked = failed = 0

    while True:
        discovered = adapter.discover_orders(
            status=ACTIVE_PRINTERVAL_STATUS_FILTER,
            job_type=ALL_JOB_TYPES,
            limit=100,
            cursor=cursor,
            platform_id=str(platform.id),
        )
        if not discovered.success:
            raise RuntimeError(discovered.error_class or "Không thể đọc active queue từ Printerval.")

        for summary in discovered.orders:
            external_order_id = summary.external_order_id
            if external_order_id in seen:
                continue
            seen.add(external_order_id)
            checked += 1
            incoming_status = (summary.status or "").strip().lower()
            if incoming_status not in {"waiting", "doing", "fix"}:
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
                    if incoming_status != "waiting":
                        skipped_untracked += 1
                        continue
                    order = Order(
                        external_order_id=external_order_id,
                        platform_id=platform.id,
                        state=OrderState.OPEN.value,
                        product_name=summary.product_name,
                        thumbnail_url=summary.thumbnail_url,
                        sku=summary.sku,
                        product_category=summary.product_category,
                        product_skus=summary.product_skus,
                        printerval_designer=summary.designer,
                        printerval_designer_synced_at=now_utc if summary.designer else None,
                        printerval_status=incoming_status,
                        printerval_status_synced_at=now_utc,
                        status_changed_at=now_utc,
                        product_image_urls=summary.product_image_urls,
                    )
                    session.add(order)
                    session.flush()
                    detail = adapter.get_order_detail(external_order_id, platform_id=str(platform.id))
                    if detail.success:
                        _apply_order_detail_result(order, detail)
                    session.commit()
                    added += 1
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
            except Exception as exc:
                session.rollback()
                failed += 1
                logger.warning("Active Printerval reconciliation failed for %s: %s", external_order_id, exc)

        if not discovered.cursor:
            break
        cursor = discovered.cursor

    if added or updated:
        export_platform_orders_csv(session, platform.id)
    return {
        "checked": checked,
        "added": added,
        "updated": updated,
        "skipped_untracked": skipped_untracked,
        "failed": failed,
    }


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
                    break
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

        return {"checked": len(orders), "updated": updated, "not_found": not_found, "failed": failed}
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


def sync_all_platforms(session: Session) -> dict[str, dict]:
    """Sync every platform that has credentials configured, tracking per-platform
    is_running/last_result in PlatformSyncState so the web dashboard can show a
    live "syncing" indicator. One platform's failure doesn't stop the others."""
    results: dict[str, dict] = {}
    platforms = (
        session.query(Platform)
        .filter(
            Platform.is_active.is_(True),
            or_(Platform.account_password.isnot(None), Platform.session_cookie.isnot(None)),
        )
        .all()
    )
    for platform in platforms:
        if not platform.team_outsource:
            continue
        state = session.get(PlatformSyncState, platform.id)
        if state is None:
            state = PlatformSyncState(platform_id=platform.id)
            session.add(state)
        state.is_running = True
        state.last_started_at = datetime.now(UTC)
        session.commit()

        try:
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
                )
            finally:
                client.close()
            state = session.get(PlatformSyncState, platform.id)
            if state:
                state.last_result = result
                state.last_error = None
            results[str(platform.id)] = result
        except Exception as exc:
            session.rollback()
            state = session.get(PlatformSyncState, platform.id)
            if state:
                state.last_error = str(exc)
            results[str(platform.id)] = {"error": str(exc)}
        finally:
            state = session.get(PlatformSyncState, platform.id)
            if state:
                state.is_running = False
                state.last_finished_at = datetime.now(UTC)
                session.commit()

    return results

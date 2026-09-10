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
from app.adapters.printerval.api_client import PrintervalApiClient
from app.adapters.printerval.row_mapper import parse_order_detail_from_row
from app.application.crawl import _apply_order_detail_result
from app.config import get_settings


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
    caller thread and are committed once, avoiding a SQLAlchemy session race.
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

        def find(order: Order) -> tuple[object, dict[str, Any] | None]:
            return order.id, client.find_order(
                order.external_order_id,
                statuses=_status_guess_order(order.printerval_status),
            )

        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="printerval-status") as pool:
            futures = {pool.submit(find, order): order for order in orders}
            for future in as_completed(futures):
                order = futures[future]
                try:
                    order_id, row = future.result()
                    rows_by_order_id[order_id] = row
                except Exception as exc:
                    failed += 1
                    failed_order_ids.add(order.id)
                    logger.warning("Manual status sync failed for %s: %s", order.external_order_id, exc)

        updated = 0
        not_found = 0
        now_utc = datetime.now(UTC)
        for order in orders:
            row = rows_by_order_id.get(order.id)
            if row is None:
                if order.id not in failed_order_ids:
                    not_found += 1
                    if order.printerval_status != "cancelled":
                        order.printerval_status = "cancelled"
                        order.printerval_status_synced_at = now_utc
                        changed = True
                        updated += 1
                continue

            found_status = str(row.get("status") or "").strip()
            norm_status = found_status.upper()
            attributes = row.get("attributes") or {}
            note = str(attributes.get("outsource_note") or row.get("note") or "").strip()
            old_state = order.state
            changed = False

            if norm_status == "DONE" and order.state != "DONE":
                order.state = "DONE"
                session.add(
                    WorkflowEvent(
                        order_id=order.id,
                        from_state=old_state,
                        to_state="DONE",
                        actor_id=actor_id,
                        evidence={
                            "action": "APPROVE_DONE",
                            "actor_name": "Printerval",
                            "description": "Printerval đã duyệt hoàn thành đơn hàng (Done)",
                        },
                    )
                )
                changed = True
            elif norm_status == "FIX" and order.state != "REVISION":
                order.state = "REVISION"
                order.previous_note_outsource = order.note_outsource
                if note:
                    order.note_outsource = note
                order.fix_approved_by_admin = False
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
            elif note and norm_status == "FIX" and note != order.note_outsource:
                order.previous_note_outsource = order.note_outsource
                order.note_outsource = note
                changed = True

            if found_status and found_status.lower() != (order.printerval_status or "").lower():
                order.printerval_status = found_status.lower()
                changed = True

            designer = _row_designer(row, designer_map=designer_map)
            if designer and designer != order.printerval_designer:
                order.printerval_designer = designer
                order.printerval_designer_synced_at = now_utc
                changed = True

            order.printerval_status_synced_at = now_utc
            if changed:
                updated += 1

        session.commit()
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
                found_status = row.get("status")
                if found_status and found_status != order.printerval_status:
                    order.printerval_status = found_status
                    updated += 1

                norm_st = (found_status or "").upper()
                if norm_st == "FIX" and order.state in ("QC_PENDING", "REVIEW", "IN_PROGRESS"):
                    order.state = "REVISION"
                    order.previous_note_outsource = order.note_outsource
                    attrs = row.get("attributes") or {}
                    found_note = str(attrs.get("outsource_note") or row.get("note") or "").strip()
                    if found_note:
                        order.note_outsource = found_note
                    order.fix_approved_by_admin = False
                    updated += 1
                elif norm_st == "DONE" and order.state != "DONE":
                    order.state = "DONE"
                    updated += 1

                found_designer = _row_designer(row, designer_map=designer_map)
                if found_designer and found_designer != order.printerval_designer:
                    order.printerval_designer = found_designer
                    order.printerval_designer_synced_at = datetime.now(UTC)
                elif not found_designer and order.printerval_designer and "@" in order.printerval_designer:
                    order.printerval_designer = None
                    order.printerval_designer_synced_at = datetime.now(UTC)
                order.printerval_status_synced_at = datetime.now(UTC)

                # Re-apply full detail metadata (source files, SKU data, custom config, notes, deadlines).
                detail_result = parse_order_detail_from_row(
                    row, order.external_order_id, platform_id=str(platform.id), download_images=False
                )
                if detail_result.success:
                    _apply_order_detail_result(order, detail_result)

                session.commit()
            except StaleDataError:
                # Concurrent transaction modified this order; rollback this order and continue
                session.rollback()
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
            result = sync_platform_order_statuses(session, platform)
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

"""Read-only mirror of Printerval's own order status into Order.printerval_status.

This is deliberately one-directional (Printerval -> us) and never writes anything back
to the site — per claude.md §2 invariant #5 and §3 C5, only a QC Approve decision's own
job is ever allowed to write order state to Printerval. This sync exists purely so the
web dashboard can show an accurate "what does Printerval currently say" column without
an operator having to open the site themselves.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.adapters.db.models import Order, Platform, PlatformSyncState
from app.adapters.printerval.api_client import PrintervalApiClient
from app.adapters.printerval.row_mapper import parse_order_detail_from_row
from app.application.crawl import _apply_order_detail_result


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


def sync_platform_order_statuses(
    session: Session, platform: Platform, api_client: PrintervalApiClient | None = None
) -> dict:
    """Look up each Order we already track for this platform (one find_order call
    each, hinted by its last-known status) and update Order.printerval_status,
    printerval_designer, and full order details (source, template, notes, etc.).

    Deliberately scoped to OUR orders, not a bulk page-through of Printerval's full
    history: an established account can have thousands of "done" orders alone — a
    live incident here paged 30+ pages (~3000 rows) of "done" for one account before
    even finishing, taking minutes for a sync meant to run every 5. Cost now scales
    with how many orders we track, not with the site's total history. Never creates
    an Order row — discovering new orders is C1's job, not this one.
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
        orders = session.query(Order).filter(Order.platform_id == platform.id).all()
        updated = 0
        not_found = 0
        for order in orders:
            row = client.find_order(
                order.external_order_id, statuses=_status_guess_order(order.printerval_status)
            )
            if row is None:
                not_found += 1
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
                # Repair values written by the former designer_email mapping.  Do
                # not erase real labels when this lightweight list endpoint simply
                # omits the dropdown value.
                order.printerval_designer = None
                order.printerval_designer_synced_at = datetime.now(UTC)
            order.printerval_status_synced_at = datetime.now(UTC)

            # Re-apply full detail metadata (source files, template jobs, custom config, notes, deadlines)
            detail_result = parse_order_detail_from_row(
                row, order.external_order_id, platform_id=str(platform.id), download_images=False
            )
            if detail_result.success:
                _apply_order_detail_result(order, detail_result)

        session.commit()
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
            state.last_result = result
            state.last_error = None
            results[str(platform.id)] = result
        except Exception as exc:
            # Deliberately broad, not just PrintervalApiError/ConfigurationError: a
            # live incident hit sqlalchemy.orm.exc.StaleDataError here (this task's
            # manual trigger overlapped a scheduled run, both updating the same Order
            # rows' optimistic-lock version) — an uncaught type below this except
            # clause propagated straight out of the loop, silently skipping every
            # platform after the failing one instead of just this one, contradicting
            # this function's own "one platform's failure doesn't stop the others."
            session.rollback()
            state = session.get(PlatformSyncState, platform.id)
            state.last_error = str(exc)
            results[str(platform.id)] = {"error": str(exc)}
        finally:
            state.is_running = False
            state.last_finished_at = datetime.now(UTC)
            session.commit()

    return results

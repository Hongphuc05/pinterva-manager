"""Read-only mirror of Printerval's own order status into Order.printerval_status.

This is deliberately one-directional (Printerval -> us) and never writes anything back
to the site — per claude.md §2 invariant #5 and §3 C5, only a QC Approve decision's own
job is ever allowed to write order state to Printerval. This sync exists purely so the
web dashboard can show an accurate "what does Printerval currently say" column without
an operator having to open the site themselves.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.adapters.db.models import Order, Platform, PlatformSyncState
from app.adapters.printerval.api_client import (
    PrintervalApiClient,
    PrintervalApiConfigurationError,
    PrintervalApiError,
)

#: Safety bound on pages read per status per platform — a real backlog has been
# observed up to ~529 orders at once (claude.md §16); 30 pages * 100 = 3000 covers that
# with headroom without risking an unbounded scan against a live site.
MAX_PAGES_PER_STATUS = 30


def _external_id_to_numeric(external_order_id: str) -> int | None:
    """"DJ3971347" -> 3971347. Returns None for anything that doesn't parse (never
    guess — just skip matching that order)."""
    code = external_order_id[2:] if external_order_id.upper().startswith("DJ") else external_order_id
    return int(code) if code.isdigit() else None


def sync_platform_order_statuses(
    session: Session, platform: Platform, api_client: PrintervalApiClient | None = None
) -> dict:
    """Fetch every order across all 6 known statuses for this platform's team scope
    and update Order.printerval_status for the orders we already have. Never creates
    an Order row — discovering new orders is C1's job, not this one.
    """
    owns_client = api_client is None
    client = api_client or PrintervalApiClient(
        base_url="https://printerval.com",
        username=platform.account_username,
        password=platform.account_password,
        team_outsource=platform.team_outsource,
    )
    try:
        status_by_numeric_id: dict[int, str] = {}
        pages_per_status: dict[str, int] = {}
        for status in PrintervalApiClient.ORDER_STATUSES:
            page_id = 0
            for _ in range(MAX_PAGES_PER_STATUS):
                page = client.list_status_page(status, page_size=100, page_id=page_id)
                for row in page.orders:
                    numeric_id = row.get("id")
                    if isinstance(numeric_id, int):
                        status_by_numeric_id[numeric_id] = status
                pages_per_status[status] = page_id + 1
                if len(page.orders) < 100:
                    break
                page_id += 1

        orders = session.query(Order).filter(Order.platform_id == platform.id).all()
        updated = 0
        for order in orders:
            numeric_id = _external_id_to_numeric(order.external_order_id)
            if numeric_id is None:
                continue
            found_status = status_by_numeric_id.get(numeric_id)
            if found_status and found_status != order.printerval_status:
                order.printerval_status = found_status
                updated += 1
            if found_status:
                order.printerval_status_synced_at = datetime.now(UTC)

        return {
            "checked": len(orders),
            "updated": updated,
            "rows_seen": len(status_by_numeric_id),
            "pages_per_status": pages_per_status,
        }
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
        .filter(Platform.is_active.is_(True), Platform.account_password.isnot(None))
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
        except (PrintervalApiError, PrintervalApiConfigurationError) as exc:
            session.rollback()
            state = session.get(PlatformSyncState, platform.id)
            state.last_error = str(exc)
            results[str(platform.id)] = {"error": str(exc)}
        finally:
            state.is_running = False
            state.last_finished_at = datetime.now(UTC)
            session.commit()

    return results

from __future__ import annotations

import csv
import hashlib
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.adapters.db.models import Batch, DeadLetter, ExternalObservation, Order, OrderAsset
from app.adapters.playwright_support import with_retry
from app.adapters.printerval.interface import ALL_JOB_TYPES, NTTH_DESIGNER_OPTION, PrintervalAdapter
from app.adapters.printerval.models import OrderSummary
from app.application.operations import OperationInProgressError, run_idempotent
from app.application.order_transitions import apply_transition
from app.domain.models import OrderState

logger = logging.getLogger(__name__)


class DiscoverFailedError(Exception):
    """Raised by discover_waiting_orders when the adapter call itself failed (already
    dead-lettered before this raises) — distinct from the site genuinely having zero
    new orders right now, which returns an empty list normally. Callers (the Celery
    task, the web dashboard's manual Refresh) must not treat this the same as "0 new
    orders" — a real incident showed a live "Waiting" order sitting on the site while
    the crawl silently reported success with 0 results, because a filter-option
    mismatch was swallowed into an empty list instead of surfacing as a visible error.
    """

    def __init__(self, error_class: str):
        super().__init__(f"discover_waiting_orders failed: {error_class}")
        self.error_class = error_class


def apply_crawled_product_gallery(order: Order, incoming: list[str] | None) -> None:
    """Apply a server-crawled gallery without discarding a richer browser capture.

    Server requests can legitimately be reduced to one thumbnail by Cloudflare.
    Once CopyImage has stored a multi-image gallery, that fallback must never erase
    it on later status/detail crawls.
    """
    candidates = [
        url.strip() for url in (incoming or []) if isinstance(url, str) and url.strip()
    ]
    if not candidates:
        return
    current = [
        url.strip()
        for url in (order.product_image_urls or [])
        if isinstance(url, str) and url.strip()
    ]
    if len(current) > 1 and len(candidates) <= 1:
        return
    chosen = candidates if len(candidates) > 1 else [*current, *candidates]
    order.product_image_urls = list(dict.fromkeys(chosen))


def discover_waiting_orders_with_summaries(
    session: Session,
    adapter: PrintervalAdapter,
    limit: int = 40,
    job_type: str = ALL_JOB_TYPES,
    platform_id: uuid.UUID | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[list[str], list[OrderSummary]]:
    """Return new external_order_ids + OrderSummary objects from adapter's Waiting queue."""
    platform_str = str(platform_id) if platform_id else None
    kwargs = {"status": "Waiting", "job_type": job_type, "limit": limit}
    if platform_str:
        kwargs["platform_id"] = platform_str
    if date_from:
        kwargs["date_from"] = date_from
    if date_to:
        kwargs["date_to"] = date_to
    result = with_retry(lambda: adapter.discover_orders(**kwargs))
    if not result.success:
        session.add(
            DeadLetter(
                source="crawl.discover_waiting_orders",
                payload={"status": "Waiting", "job_type": job_type, "limit": limit},
                error_class=result.error_class or "BUG",
            )
        )
        session.commit()
        raise DiscoverFailedError(result.error_class or "BUG")
    discovered_ids = [o.external_order_id for o in result.orders]
    if not discovered_ids:
        return [], []

    candidate_ids = set(discovered_ids)
    for oid in list(candidate_ids):
        if oid.startswith("DJ"):
            candidate_ids.add(oid[2:])
        else:
            candidate_ids.add(f"DJ{oid}")

    query = session.query(Order).filter(Order.external_order_id.in_(list(candidate_ids)))
    if platform_id:
        query = query.filter(Order.platform_id == platform_id)
    existing_orders = query.all()
    existing_map = {o.external_order_id: o for o in existing_orders}

    summary_map = {}
    for s in result.orders:
        summary_map[s.external_order_id] = s
        if s.external_order_id.startswith("DJ"):
            summary_map[s.external_order_id[2:]] = s
        else:
            summary_map[f"DJ{s.external_order_id}"] = s

    for oid, existing_order in existing_map.items():
        summary = summary_map.get(oid)
        if summary:
            if not existing_order.thumbnail_url and summary.thumbnail_url:
                existing_order.thumbnail_url = summary.thumbnail_url
            if not existing_order.product_name and summary.product_name:
                existing_order.product_name = summary.product_name
            if not existing_order.sku and summary.sku:
                existing_order.sku = summary.sku
            if not existing_order.product_category and summary.product_category:
                existing_order.product_category = summary.product_category
            if summary.product_skus:
                existing_order.product_skus = summary.product_skus
            if summary.sku_image_url:
                existing_order.sku_image_url = summary.sku_image_url
            if summary.external_order_url:
                existing_order.external_order_url = summary.external_order_url
            if summary.source_files:
                existing_order.source_files = summary.source_files
            if summary.source_download_all_url:
                existing_order.source_download_all_url = summary.source_download_all_url
            apply_crawled_product_gallery(existing_order, summary.product_image_urls)

    new_ids = [oid for oid in discovered_ids if oid not in existing_map and f"DJ{oid}" not in existing_map and (oid[2:] if oid.startswith("DJ") else oid) not in existing_map]
    new_summaries = [o for o in result.orders if o.external_order_id in new_ids]
    return new_ids, new_summaries


def discover_waiting_orders(
    session: Session,
    adapter: PrintervalAdapter,
    limit: int = 40,
    job_type: str = ALL_JOB_TYPES,
    platform_id: uuid.UUID | None = None,
) -> list[str]:
    """Return external_order_ids from the adapter's Waiting queue that don't already
    have an `Order` row — safe to call repeatedly. Defaults to every job type (claude.md
    §16, changed 2026-09-07 — job type is a customer-facing label, not a processing
    constraint); pass a specific type (e.g. "2D") to narrow it.

    Raises DiscoverFailedError (after dead-lettering) on an exhausted-retry adapter
    failure — never silently returns an empty list for that case, so a prolonged
    failure (login/session expired, site markup/filter text changed) can never look
    identical to "nothing new right now" to a caller.
    """
    new_ids, _ = discover_waiting_orders_with_summaries(
        session, adapter, limit=limit, job_type=job_type, platform_id=platform_id
    )
    return new_ids


def scan_orders_fast(
    session: Session,
    adapter: PrintervalAdapter,
    *,
    platform_id: uuid.UUID,
    status: str,
    designer: str | None = None,
    job_type: str = ALL_JOB_TYPES,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Read-only API scan: upsert the selected site queue without claiming jobs."""
    cursor: str | None = None
    seen: set[str] = set()
    added = 0
    updated = 0
    while True:
        result = adapter.discover_orders(
            status=status,
            job_type=job_type,
            limit=100,
            cursor=cursor,
            platform_id=str(platform_id),
            date_from=date_from,
            date_to=date_to,
        )
        if not result.success:
            raise DiscoverFailedError(result.error_class or "BUG")
        for summary in result.orders:
            if designer and summary.designer != designer:
                continue
            if summary.external_order_id in seen:
                continue
            seen.add(summary.external_order_id)
            order = (
                session.query(Order)
                .filter(Order.external_order_id == summary.external_order_id, Order.platform_id == platform_id)
                .one_or_none()
            )
            if order is None:
                order = Order(
                    external_order_id=summary.external_order_id,
                    platform_id=platform_id,
                    state=OrderState.OPEN.value,
                    product_name=summary.product_name,
                    thumbnail_url=summary.thumbnail_url,
                    sku=summary.sku,
                    product_category=summary.product_category,
                    product_skus=summary.product_skus,
                    printerval_designer=summary.designer,
                    printerval_designer_synced_at=datetime.now(UTC) if summary.designer else None,
                    printerval_status=summary.status.lower(),
                    product_image_urls=summary.product_image_urls,
                )
                session.add(order)
                added += 1
            else:
                if summary.designer:
                    order.printerval_designer = summary.designer
                    order.printerval_designer_synced_at = datetime.now(UTC)
                elif order.printerval_designer and "@" in order.printerval_designer:
                    order.printerval_designer = None
                order.printerval_status = summary.status.lower()
                order.thumbnail_url = summary.thumbnail_url or order.thumbnail_url
                apply_crawled_product_gallery(order, summary.product_image_urls)
                updated += 1

            # The fast list endpoint already contains the complete order payload.
            # Parse it from the adapter cache to persist resource files, custom
            # configuration, dates and source images in this same HTTP crawl.
            detail = adapter.get_order_detail(summary.external_order_id, platform_id=str(platform_id))
            if detail.success:
                if detail.product_name:
                    order.product_name = detail.product_name
                if detail.thumbnail_url:
                    order.thumbnail_url = detail.thumbnail_url
                if detail.sku:
                    order.sku = detail.sku
                if detail.product_category:
                    order.product_category = detail.product_category
                # [] is a meaningful persisted value: it records that this order's
                # detail was fetched and genuinely had no variants.  Leaving NULL
                # made import_claimed_orders select the order again forever.
                order.product_variants = [variant.model_dump() for variant in detail.product_variants]
                if detail.product_skus:
                    order.product_skus = [product_sku.model_dump() for product_sku in detail.product_skus]
                order.multiple_design = detail.multiple_design
                order.double_sided = detail.double_sided
                order.created_at_ext = detail.created_at
                order.order_created_at_ext = detail.order_created_at
                order.deadline_at_ext = detail.deadline_at
                order.note_outsource = detail.note_outsource
                order.order_note = detail.order_note
                order.custom_config = detail.custom_config.model_dump() if detail.custom_config else None
                order.design_tool_url = detail.design_tool_url
                if detail.sku_image_url:
                    order.sku_image_url = detail.sku_image_url
                if detail.external_order_url:
                    order.external_order_url = detail.external_order_url
                if detail.source_files:
                    order.source_files = detail.source_files
                apply_crawled_product_gallery(order, detail.product_image_urls)
        if not result.cursor:
            break
        cursor = result.cursor
    session.commit()
    export_platform_orders_csv(session, platform_id)
    return {"scanned": len(seen), "added": added, "updated": updated}


def find_unclaimed_order_ids(session: Session, platform_id: uuid.UUID | None) -> list[str]:
    """Orders sitting at DISCOVERED with no confirmed printerval claim — a prior
    claim_batch attempt failed (dead-lettered) for them, and the normal discover step
    will never resurface them on its own (they already have an Order row, so they're
    never "new" again). Merged into the next crawl cycle's claim_batch call alongside
    genuinely new orders, so a failed claim actually gets retried instead of sitting
    stuck forever."""
    query = (
        session.query(Order)
        .outerjoin(
            ExternalObservation,
            (ExternalObservation.order_id == Order.id) & (ExternalObservation.source == "printerval"),
        )
        .filter(Order.state == OrderState.OPEN.value, ExternalObservation.id.is_(None))
    )
    if platform_id:
        query = query.filter(Order.platform_id == platform_id)
    return [o.external_order_id for o in query.all()]


def _claim_one_order(
    session: Session,
    adapter: PrintervalAdapter,
    batch: Batch,
    order_id: str,
    owner: str,
    summaries_map: dict[str, OrderSummary],
    dead_letter_source: str,
) -> bool:
    """Ensure an Order row exists for order_id, then claim it on the site via
    `adapter.set_designer`. Returns True/claimed, False/dead-lettered. Commits once,
    itself — shared by claim_batch (new orders) and retry_failed_claims (orders a
    prior claim_batch already dead-lettered)."""
    order = session.query(Order).filter_by(external_order_id=order_id).one_or_none()
    if order is None:
        summary = summaries_map.get(order_id)
        order = Order(
            external_order_id=order_id,
            batch_id=batch.id,
            platform_id=batch.platform_id,
            state=OrderState.OPEN.value,
            product_name=summary.product_name if summary else None,
            thumbnail_url=summary.thumbnail_url if summary else None,
            sku=summary.sku if summary else None,
            product_category=summary.product_category if summary else None,
            product_skus=summary.product_skus if summary else None,
            sku_image_url=summary.sku_image_url if summary else None,
            external_order_url=summary.external_order_url if summary else None,
            source_files=summary.source_files if summary else None,
            source_download_all_url=summary.source_download_all_url if summary else None,
            product_image_urls=summary.product_image_urls if summary else None,
        )
        session.add(order)
        session.flush()

    result = with_retry(lambda: adapter.set_designer(order_id, owner))
    if result.success:
        session.add(
            ExternalObservation(
                order_id=order.id,
                source="printerval",
                external_id=order_id,
                observed_state=str(result.observed_state.get("designer")),
                evidence=result.evidence,
            )
        )
        claimed = True
    else:
        session.add(
            DeadLetter(
                source=dead_letter_source,
                payload={"order_id": order_id, "batch_id": str(batch.id)},
                error_class=result.error_class or "BUG",
            )
        )
        claimed = False

    # Commit after every single order, not once at the very end of the whole batch.
    # Each set_designer call is a real Playwright round-trip (seconds, sometimes much
    # more) — a batch of dozens of new orders previously stayed one giant uncommitted
    # transaction the entire time, so nothing about its progress was ever visible from
    # outside, and one slow/stuck order made the whole request look identically "hung"
    # whether it truly was or was just working through a long backlog. A crash/retry
    # after this point re-walks order_ids and skips orders that already have a row
    # (the `order is None` check above) — the one known cost is a retried batch
    # re-issuing set_designer for already-claimed orders (harmless: it's already
    # idempotent against "already the target value") and a duplicate ExternalObservation
    # row for those, not a duplicate claim.
    session.commit()
    return claimed


def claim_batch(
    session: Session,
    adapter: PrintervalAdapter,
    order_ids: list[str],
    owner: str = NTTH_DESIGNER_OPTION,
    order_summaries: list[OrderSummary] | None = None,
    platform_id: uuid.UUID | None = None,
) -> dict:
    """Create a Batch + Order rows for order_ids (skipping any that already have an
    Order row — defensive re-entrancy if a prior crash happened between discover and
    claim), then claim each on the site via `adapter.set_designer`. One order's claim
    failure dead-letters that order and continues the rest of the batch.

    Idempotent per exact order_ids set (protects a genuine double-submit of the same
    request from creating two Batches/duplicate claims) — callers that need a *failed*
    claim retried on a later, separate attempt must use `retry_failed_claims` instead,
    not call this again with the same set (see its docstring for why).
    """
    # ponytail: hashed, not the raw joined IDs — `operations.idempotency_key` is
    # VARCHAR(255), and a real crawl can discover far more than ~20 new orders in one
    # batch (claude.md §16: up to 529 observed backlogged at once), which overflows a
    # raw "claim_batch:DJ1,DJ2,DJ3,..." key and crashes the whole request. A SHA-256
    # hex digest is fixed-length (64 chars) and still deterministic per exact
    # order_ids set, preserving the idempotency guarantee.
    ids_key = hashlib.sha256(",".join(sorted(order_ids)).encode("utf-8")).hexdigest()
    idempotency_key = f"claim_batch:{ids_key}"
    summaries_map = {s.external_order_id: s for s in (order_summaries or [])}

    def _do() -> dict:
        batch = Batch(source="printerval_crawl", owner=owner, count=len(order_ids), platform_id=platform_id)
        session.add(batch)
        session.flush()  # populate batch.id before it's referenced below

        claimed: list[str] = []
        failed: list[str] = []
        for order_id in order_ids:
            if _claim_one_order(session, adapter, batch, order_id, owner, summaries_map, "crawl.claim_batch"):
                claimed.append(order_id)
            else:
                failed.append(order_id)

        return {"batch_id": str(batch.id), "claimed": claimed, "failed": failed}

    return run_idempotent(session, idempotency_key, "claim_batch", _do)


def retry_failed_claims(
    session: Session,
    adapter: PrintervalAdapter,
    order_ids: list[str],
    owner: str = NTTH_DESIGNER_OPTION,
    platform_id: uuid.UUID | None = None,
) -> dict:
    """Re-attempt claiming orders a *previous* claim_batch already dead-lettered
    (order_ids must come from find_unclaimed_order_ids — each already has an Order
    row and no confirmed printerval claim yet).

    Deliberately NOT wrapped in run_idempotent, unlike claim_batch: this same set of
    still-unclaimed order_ids is exactly what a *new* crawl cycle re-submits every
    single time nothing new gets discovered in between (claude.md §16 backlog can sit
    for many cycles). claim_batch's own idempotency key is a hash of the order_ids
    set, so wrapping this in it too would key every single retry cycle to the same
    operation row — the very first failure would be cached as "completed" forever,
    and the order would never actually be retried against the site again (confirmed
    live 2026-09-08: 3 orders stuck at DISCOVERED, repeatedly reported as errors by
    every crawl, with zero new dead_letters or set_designer attempts after the first).
    Safe to skip idempotency here because `adapter.set_designer` is itself idempotent
    (a no-op read-after-write check if already the target value) and the only entries
    fed in are ones with no confirmed claim yet, so nothing here can double-claim an
    order that already succeeded.
    """
    if not order_ids:
        return {"claimed": [], "failed": []}
    batch = Batch(source="printerval_crawl_retry", owner=owner, count=len(order_ids), platform_id=platform_id)
    session.add(batch)
    session.flush()

    claimed: list[str] = []
    failed: list[str] = []
    for order_id in order_ids:
        if _claim_one_order(session, adapter, batch, order_id, owner, {}, "crawl.retry_failed_claims"):
            claimed.append(order_id)
        else:
            failed.append(order_id)

    return {"batch_id": str(batch.id), "claimed": claimed, "failed": failed}


def _apply_order_detail_result(order: Order, detail_result) -> None:
    """Copy a successful get_order_detail result onto an Order — shared by
    import_claimed_orders (first import) and refresh_order_detail (re-fetch for an
    order already past that point, e.g. product SKU data changed later).
    Only overwrite what discover-time already captured (from the list API response)
    when the detail scrape actually found a value — Playwright's DOM extraction can
    legitimately come back empty for a field (selector didn't match this row's
    layout) and must not blank out a value we already have, just because it ran
    second."""
    if detail_result.status:
        order.printerval_status = detail_result.status.lower()
        order.printerval_status_synced_at = datetime.now(UTC)
    if detail_result.designer:
        order.printerval_designer = detail_result.designer
        order.printerval_designer_synced_at = datetime.now(UTC)
    if detail_result.product_name:
        order.product_name = detail_result.product_name
    if detail_result.thumbnail_url:
        order.thumbnail_url = detail_result.thumbnail_url
    if detail_result.sku:
        order.sku = detail_result.sku
    if detail_result.product_category:
        order.product_category = detail_result.product_category
    # Preserve an empty list as the "detail fetched" marker.  See the import query
    # in import_claimed_orders, which uses NULL to identify orders still awaiting a
    # first detail fetch.
    order.product_variants = [v.model_dump() for v in detail_result.product_variants]
    if detail_result.product_skus:
        order.product_skus = [product_sku.model_dump() for product_sku in detail_result.product_skus]
    order.multiple_design = detail_result.multiple_design
    order.double_sided = detail_result.double_sided
    order.priority_label = detail_result.priority_label
    order.created_at_ext = detail_result.created_at
    order.order_created_at_ext = detail_result.order_created_at
    order.deadline_at_ext = detail_result.deadline_at
    order.note_outsource = detail_result.note_outsource
    order.order_note = detail_result.order_note
    order.custom_config = (
        detail_result.custom_config.model_dump() if detail_result.custom_config else None
    )
    order.design_tool_url = detail_result.design_tool_url
    if detail_result.sku_image_url:
        order.sku_image_url = detail_result.sku_image_url
    if detail_result.external_order_url:
        order.external_order_url = detail_result.external_order_url
    if detail_result.source_files:
        order.source_files = detail_result.source_files
    if detail_result.source_download_all_url:
        order.source_download_all_url = detail_result.source_download_all_url
    apply_crawled_product_gallery(order, detail_result.product_image_urls)


def refresh_order_detail(session: Session, adapter: PrintervalAdapter, order: Order) -> dict:
    """Re-fetch and overwrite an order's full detail (SKU data, source files, images,
    deadline, product info...) from Printerval, regardless of its current internal
    state. Unlike import_claimed_orders (first import, gated on state, transitions
    OPEN -> OPEN via apply_transition), this never touches Order.state — it's a pure
    metadata refresh for an order the mother site changed *after* the one-time import
    (e.g. a SKU changed later), triggered on demand from the "Trạng Thái Đơn" tab.

    Not idempotency-key-gated: like retry_failed_claims, a manual "refresh now" click
    is a genuinely new request each time, and re-running this is always safe — it only
    overwrites fields with fresh reads, never creates a duplicate side effect (the one
    OrderAsset row is only added when the checksum actually changed, see below).
    """
    order_platform_id = str(order.platform_id) if order.platform_id else None
    detail_result = with_retry(
        lambda: adapter.get_order_detail(order.external_order_id, platform_id=order_platform_id)
    )
    if not detail_result.success:
        session.add(
            DeadLetter(
                source="crawl.refresh_order_detail",
                payload={"order_id": order.external_order_id, "stage": "get_order_detail"},
                error_class=detail_result.error_class or "BUG",
            )
        )
        return {"success": False, "stage": "get_order_detail"}

    _apply_order_detail_result(order, detail_result)

    # Asset image downloading is best-effort during a metadata refresh — an un-downloadable
    # source image or transient 404 on an asset URL must not fail the overall order update.
    try:
        asset_result = adapter.download_asset(order.external_order_id, platform_id=order_platform_id)
        if asset_result and asset_result.success and asset_result.local_path:
            latest_asset = (
                session.query(OrderAsset)
                .filter_by(order_id=order.id)
                .order_by(OrderAsset.id.desc())
                .first()
            )
            if latest_asset is None or latest_asset.checksum != asset_result.checksum:
                session.add(
                    OrderAsset(
                        order_id=order.id,
                        source_image_ref=asset_result.local_path,
                        checksum=asset_result.checksum,
                        storage_location=asset_result.local_path,
                    )
                )
    except Exception as exc:
        logger.warning(
            "download_asset non-fatal exception during refresh_order_detail for %s: %s",
            order.external_order_id,
            exc,
        )

    session.commit()
    return {"success": True}


def import_claimed_orders(session: Session, adapter: PrintervalAdapter) -> dict:
    """Download+verify the asset for every Order that has a confirmed successful claim
    (a `printerval`-source ExternalObservation row — written only when claim_batch's
    adapter.set_designer call actually succeeded, never on a dead-lettered failure) and
    is still at DISCOVERED. Scans across ALL batches/cycles, not just one just-created
    batch — this is what makes a crash-interrupted import naturally retried by the next
    crawl cycle. The ExternalObservation join is what makes a claim-failed order
    structurally ineligible for import, closing the gap where it could otherwise reach
    CLAIMED_IMPORTED without the real site ever confirming the claim.

    Each order's import is its own idempotent operation (`import_order:<external_order_id>`)
    rather than one batch-wide operation. A crashed/never-finished attempt is retried
    (run_idempotent's pending-lease reclaim naturally handles this). A *confirmed*
    download failure (with_retry exhausted, dead-lettered) is marked "completed" (not
    raised) so it stops being silently re-attempted — per claude.md §11, an
    exhausted-retry failure needs an operator's explicit recovery action, not
    indefinite silent auto-retry from this job.
    """
    orders = (
        session.query(Order)
        .join(ExternalObservation, ExternalObservation.order_id == Order.id)
        .filter(
            Order.state == OrderState.OPEN.value,
            ExternalObservation.source == "printerval",
            Order.product_variants.is_(None),
        )
        .distinct()
        .all()
    )
    imported: list[str] = []
    failed: list[str] = []
    for order in orders:

        def _do(order=order) -> dict:
            order_platform_id = str(order.platform_id) if order.platform_id else None
            result = with_retry(
                lambda: adapter.download_asset(order.external_order_id, platform_id=order_platform_id)
            )
            if not result.success:
                session.add(
                    DeadLetter(
                        source="crawl.import_claimed_orders",
                        payload={"order_id": order.external_order_id, "stage": "download_asset"},
                        error_class=result.error_class or "BUG",
                    )
                )
                return {"imported": False}

            detail_result = with_retry(
                lambda: adapter.get_order_detail(order.external_order_id, platform_id=order_platform_id)
            )
            if not detail_result.success:
                session.add(
                    DeadLetter(
                        source="crawl.import_claimed_orders",
                        payload={"order_id": order.external_order_id, "stage": "get_order_detail"},
                        error_class=detail_result.error_class or "BUG",
                    )
                )
                return {"imported": False}

            # Written only once the detail call has also succeeded (moved from
            # right after download_asset) — otherwise a detail failure below would
            # still leave a committed OrderAsset row for an order stuck at
            # DISCOVERED, which then double-inserts on operator recovery/retry
            # (claude.md §18: batch/resume/retry must be idempotent).
            # download_asset can succeed with no local_path (plain product orders have
            # no separate personalized source file to download) — only record an
            # OrderAsset when there's an actual file, since source_image_ref/
            # storage_location are NOT NULL columns.
            if result.local_path:
                session.add(
                    OrderAsset(
                        order_id=order.id,
                        source_image_ref=result.local_path,
                        checksum=result.checksum,
                        storage_location=result.local_path,
                    )
                )

            _apply_order_detail_result(order, detail_result)

            apply_transition(
                session,
                order,
                OrderState.OPEN,
                actor_id=None,
                evidence={"source": "crawl_job"},
            )
            return {"imported": True}

        try:
            outcome = run_idempotent(
                session, f"import_order:{order.external_order_id}", "import_order", _do
            )
        except OperationInProgressError:
            # Another process is mid-attempt on this exact order right now (fresh
            # pending lease) — skip it this cycle, it'll be picked up naturally once
            # that attempt finishes or its lease expires.
            continue

        if outcome["imported"]:
            imported.append(order.external_order_id)
        else:
            failed.append(order.external_order_id)

    return {"imported": imported, "failed": failed}


PLATFORM_DATA_DIR = Path("platform_data")

_CSV_FIELDNAMES = [
    "external_order_id",
    "state",
    "product_name",
    "sku",
    "product_category",
    "thumbnail_url",
    "product_sku_count",
    "created_at",
]


def export_platform_orders_csv(session: Session, platform_id: uuid.UUID | None) -> Path:
    """Overwrite platform_data/<platform_id>/orders.csv with every Order this platform
    currently has in Postgres (the source of truth) — one row per order, no duplicates.

    Replaces the old per-row append during discover_orders, which re-appended the same
    order on every retry/poll (a single order could accumulate a dozen duplicate CSV
    rows) and had no real platform isolation (a missing platform_id silently fell back
    to one shared root-level file, which pytest runs polluted with fixture data too).
    A fresh, deduplicated snapshot each call sidesteps all of that — it can never drift
    from the DB, and calling it twice in a row is a no-op.
    """
    target_dir = PLATFORM_DATA_DIR / (str(platform_id) if platform_id else "default")
    target_dir.mkdir(parents=True, exist_ok=True)
    csv_path = target_dir / "orders.csv"

    query = session.query(Order)
    query = query.filter(Order.platform_id == platform_id) if platform_id else query.filter(
        Order.platform_id.is_(None)
    )
    orders = query.order_by(Order.external_order_id).all()

    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDNAMES)
        writer.writeheader()
        for order in orders:
            writer.writerow(
                {
                    "external_order_id": order.external_order_id,
                    "state": order.state,
                    "product_name": order.product_name or "",
                    "sku": order.sku or "",
                    "product_category": order.product_category or "",
                    "thumbnail_url": order.thumbnail_url or "",
                    "product_sku_count": len(order.product_skus or []),
                    "created_at": order.created_at.isoformat() if order.created_at else "",
                }
            )
    return csv_path

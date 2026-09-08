from __future__ import annotations

import csv
import hashlib
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.adapters.db.models import Batch, DeadLetter, ExternalObservation, Order, OrderAsset
from app.adapters.playwright_support import with_retry
from app.adapters.printerval.interface import ALL_JOB_TYPES, NTTH_DESIGNER_OPTION, PrintervalAdapter
from app.adapters.printerval.models import OrderSummary
from app.application.operations import OperationInProgressError, run_idempotent
from app.application.order_transitions import apply_transition
from app.domain.models import OrderState


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


def discover_waiting_orders_with_summaries(
    session: Session,
    adapter: PrintervalAdapter,
    limit: int = 40,
    job_type: str = ALL_JOB_TYPES,
    platform_id: uuid.UUID | None = None,
) -> tuple[list[str], list[OrderSummary]]:
    """Return new external_order_ids + OrderSummary objects from adapter's Waiting queue."""
    platform_str = str(platform_id) if platform_id else None
    kwargs = {"status": "Waiting", "job_type": job_type, "limit": limit}
    if platform_str:
        kwargs["platform_id"] = platform_str
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
            if summary.template_jobs:
                existing_order.template_jobs = summary.template_jobs
                existing_order.has_template = True
            elif summary.has_template:
                existing_order.has_template = True

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
            order = (
                session.query(Order).filter_by(external_order_id=order_id).one_or_none()
            )
            if order is None:
                summary = summaries_map.get(order_id)
                order = Order(
                    external_order_id=order_id,
                    batch_id=batch.id,
                    platform_id=platform_id,
                    state=OrderState.DISCOVERED.value,
                    product_name=summary.product_name if summary else None,
                    thumbnail_url=summary.thumbnail_url if summary else None,
                    sku=summary.sku if summary else None,
                    product_category=summary.product_category if summary else None,
                    template_jobs=summary.template_jobs if summary else None,
                    has_template=summary.has_template if summary else False,
                )
                session.add(order)
                session.flush()

            result = with_retry(lambda oid=order_id: adapter.set_designer(oid, owner))
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
                claimed.append(order_id)
            else:
                session.add(
                    DeadLetter(
                        source="crawl.claim_batch",
                        payload={"order_id": order_id, "batch_id": str(batch.id)},
                        error_class=result.error_class or "BUG",
                    )
                )
                failed.append(order_id)

        return {"batch_id": str(batch.id), "claimed": claimed, "failed": failed}

    return run_idempotent(session, idempotency_key, "claim_batch", _do)


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
            Order.state == OrderState.DISCOVERED.value,
            ExternalObservation.source == "printerval",
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

            # Only overwrite what discover-time already captured (from the list API
            # response) when the detail scrape actually found a value — Playwright's
            # DOM extraction can legitimately come back empty for a field (selector
            # didn't match this row's layout) and must not blank out a value we
            # already have, just because it ran second.
            if detail_result.product_name:
                order.product_name = detail_result.product_name
            if detail_result.thumbnail_url:
                order.thumbnail_url = detail_result.thumbnail_url
            if detail_result.sku:
                order.sku = detail_result.sku
            if detail_result.product_category:
                order.product_category = detail_result.product_category
            order.product_variants = [v.model_dump() for v in detail_result.product_variants]
            order.has_template = detail_result.has_template
            if detail_result.template_jobs:
                order.template_jobs = detail_result.template_jobs
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

            apply_transition(
                session,
                order,
                OrderState.CLAIMED_IMPORTED,
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
    "has_template",
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
                    "has_template": order.has_template,
                    "created_at": order.created_at.isoformat() if order.created_at else "",
                }
            )
    return csv_path

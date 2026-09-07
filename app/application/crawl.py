from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from app.adapters.db.models import Batch, DeadLetter, ExternalObservation, Order, OrderAsset
from app.adapters.playwright_support import with_retry
from app.adapters.printerval.interface import ALL_JOB_TYPES, NTTH_DESIGNER_OPTION, PrintervalAdapter
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


def discover_waiting_orders(
    session: Session,
    adapter: PrintervalAdapter,
    limit: int = 40,
    job_type: str = ALL_JOB_TYPES,
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
    result = with_retry(
        lambda: adapter.discover_orders(status="Waiting", job_type=job_type, limit=limit)
    )
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
        return []
    existing_ids = {
        row[0]
        for row in session.query(Order.external_order_id)
        .filter(Order.external_order_id.in_(discovered_ids))
        .all()
    }
    return [oid for oid in discovered_ids if oid not in existing_ids]


def claim_batch(
    session: Session,
    adapter: PrintervalAdapter,
    order_ids: list[str],
    owner: str = NTTH_DESIGNER_OPTION,
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

    def _do() -> dict:
        batch = Batch(source="printerval_crawl", owner=owner, count=len(order_ids))
        session.add(batch)
        session.flush()  # populate batch.id before it's referenced below

        claimed: list[str] = []
        failed: list[str] = []
        for order_id in order_ids:
            order = (
                session.query(Order).filter_by(external_order_id=order_id).one_or_none()
            )
            if order is None:
                order = Order(
                    external_order_id=order_id,
                    batch_id=batch.id,
                    state=OrderState.DISCOVERED.value,
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
            result = with_retry(lambda: adapter.download_asset(order.external_order_id))
            if not result.success:
                session.add(
                    DeadLetter(
                        source="crawl.import_claimed_orders",
                        payload={"order_id": order.external_order_id, "stage": "download_asset"},
                        error_class=result.error_class or "BUG",
                    )
                )
                return {"imported": False}

            detail_result = with_retry(lambda: adapter.get_order_detail(order.external_order_id))
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
            session.add(
                OrderAsset(
                    order_id=order.id,
                    source_image_ref=result.local_path,
                    checksum=result.checksum,
                    storage_location=result.local_path,
                )
            )

            order.product_name = detail_result.product_name
            order.thumbnail_url = detail_result.thumbnail_url
            order.sku = detail_result.sku
            order.product_category = detail_result.product_category
            order.product_variants = [v.model_dump() for v in detail_result.product_variants]
            order.has_template = detail_result.has_template
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

from __future__ import annotations

from sqlalchemy.orm import Session

from app.adapters.db.models import Batch, DeadLetter, ExternalObservation, Order, OrderAsset
from app.adapters.playwright_support import with_retry
from app.adapters.printerval.interface import PrintervalAdapter
from app.application.operations import OperationInProgressError, run_idempotent
from app.application.order_transitions import apply_transition
from app.domain.models import OrderState


def discover_waiting_orders(
    session: Session, adapter: PrintervalAdapter, limit: int = 40
) -> list[str]:
    """Return external_order_ids from the adapter's Waiting/2D queue that don't already
    have an `Order` row — safe to call repeatedly. An exhausted-retry adapter failure is
    dead-lettered (not silently treated as "zero new orders") so a prolonged failure
    (login/session expired, site markup changed) stays visible to an operator instead of
    looking identical to "nothing new right now."
    """
    result = with_retry(
        lambda: adapter.discover_orders(status="Waiting", job_type="2D", limit=limit)
    )
    if not result.success:
        session.add(
            DeadLetter(
                source="crawl.discover_waiting_orders",
                payload={"status": "Waiting", "job_type": "2D", "limit": limit},
                error_class=result.error_class or "BUG",
            )
        )
        session.commit()
        return []
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
    owner: str = "ntth",
) -> dict:
    """Create a Batch + Order rows for order_ids (skipping any that already have an
    Order row — defensive re-entrancy if a prior crash happened between discover and
    claim), then claim each on the site via `adapter.set_designer`. One order's claim
    failure dead-letters that order and continues the rest of the batch.
    """
    idempotency_key = f"claim_batch:{','.join(sorted(order_ids))}"

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
            if result.success:
                session.add(
                    OrderAsset(
                        order_id=order.id,
                        source_image_ref=result.local_path,
                        checksum=result.checksum,
                        storage_location=result.local_path,
                    )
                )
                apply_transition(
                    session,
                    order,
                    OrderState.CLAIMED_IMPORTED,
                    actor_id=None,
                    evidence={"source": "crawl_job"},
                )
                return {"imported": True}
            session.add(
                DeadLetter(
                    source="crawl.import_claimed_orders",
                    payload={"order_id": order.external_order_id},
                    error_class=result.error_class or "BUG",
                )
            )
            return {"imported": False}

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

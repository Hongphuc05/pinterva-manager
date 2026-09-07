from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.adapters.db.models import Batch, DeadLetter, ExternalObservation, Order, OrderAsset
from app.adapters.playwright_support import with_retry
from app.adapters.printerval.interface import PrintervalAdapter
from app.application.operations import run_idempotent
from app.application.order_transitions import apply_transition
from app.domain.models import OrderState


def discover_waiting_orders(
    session: Session, adapter: PrintervalAdapter, limit: int = 40
) -> list[str]:
    """Return external_order_ids from the adapter's Waiting/2D queue that don't already
    have an `Order` row — pure read, safe to call repeatedly, no idempotency key needed.
    """
    result = adapter.discover_orders(status="Waiting", job_type="2D", limit=limit)
    if not result.success:
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


def import_claimed_batch(session: Session, adapter: PrintervalAdapter, batch_id: str) -> dict:
    """Download+verify the asset for every Order in this batch still at DISCOVERED
    (i.e. claimed but not yet imported), transitioning each to CLAIMED_IMPORTED only on
    a verified download. A failed download dead-letters that order and leaves it at
    DISCOVERED for the next crawl cycle to retry.
    """
    idempotency_key = f"import_claimed_batch:{batch_id}"

    def _do() -> dict:
        orders = (
            session.query(Order)
            .filter_by(batch_id=uuid.UUID(batch_id), state=OrderState.DISCOVERED.value)
            .all()
        )
        imported: list[str] = []
        failed: list[str] = []
        for order in orders:
            result = with_retry(lambda o=order: adapter.download_asset(o.external_order_id))
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
                imported.append(order.external_order_id)
            else:
                session.add(
                    DeadLetter(
                        source="crawl.import_claimed_batch",
                        payload={"order_id": order.external_order_id, "batch_id": batch_id},
                        error_class=result.error_class or "BUG",
                    )
                )
                failed.append(order.external_order_id)

        return {"batch_id": batch_id, "imported": imported, "failed": failed}

    return run_idempotent(session, idempotency_key, "import_claimed_batch", _do)

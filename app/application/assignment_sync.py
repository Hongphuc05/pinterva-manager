"""Mirrors an internal designer assignment onto Printerval: sets the site's own
Designer field to that designer's registered label, then moves its status to Doing.

Deliberately does NOT touch our own Order.state / the domain state machine — that
stays driven exactly as before (the designer's own "Bắt đầu" action still owns the
ASSIGNED -> IN_PROGRESS transition, claude.md §5). This is a one-directional write of
"who's on it" + "work has started" to the external site, orthogonal to our internal
workflow, not a replacement for it.

Skipped (not guessed) whenever the assigned User has no `printerval_designer_option`
— not every internal designer is necessarily registered as a Printerval sub-user.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.adapters.db.models import DeadLetter, ExternalObservation, Order, User
from app.adapters.playwright_support import with_retry
from app.adapters.printerval.interface import PrintervalAdapter
from app.application.operations import run_idempotent

PRINTERVAL_DOING_STATUS = "Doing"


def sync_assignment_to_printerval(
    session: Session, adapter: PrintervalAdapter, order: Order, designer: User
) -> dict:
    """Idempotent per (order, designer) pair — re-assigning the same designer to the
    same order again is a no-op; assigning a *different* designer later gets its own
    fresh attempt. (ponytail: coarse-grained key, matches claim_batch's own
    idempotency granularity — a designer un-assigned then re-assigned to the exact
    same order re-uses the first attempt's cached result. Upgrade to a per-event key
    if that reassignment pattern turns out to matter in practice.)
    """
    if not designer.printerval_designer_option:
        return {"synced": False, "reason": "designer_not_registered_on_printerval"}

    idempotency_key = f"assignment_sync:{order.id}:{designer.id}"

    def _do() -> dict:
        designer_result = with_retry(
            lambda: adapter.set_designer(order.external_order_id, designer.printerval_designer_option)
        )
        if not designer_result.success:
            session.add(
                DeadLetter(
                    source="assignment_sync.set_designer",
                    payload={"order_id": order.external_order_id, "designer_id": str(designer.id)},
                    error_class=designer_result.error_class or "BUG",
                )
            )
            return {"synced": False, "stage": "set_designer"}
        session.add(
            ExternalObservation(
                order_id=order.id,
                source="printerval",
                external_id=order.external_order_id,
                observed_state=str(designer_result.observed_state.get("designer")),
                evidence=designer_result.evidence,
            )
        )

        status_result = with_retry(
            lambda: adapter.set_status(order.external_order_id, PRINTERVAL_DOING_STATUS)
        )
        if not status_result.success:
            session.add(
                DeadLetter(
                    source="assignment_sync.set_status",
                    payload={"order_id": order.external_order_id, "designer_id": str(designer.id)},
                    error_class=status_result.error_class or "BUG",
                )
            )
            return {"synced": False, "stage": "set_status"}
        session.add(
            ExternalObservation(
                order_id=order.id,
                source="printerval",
                external_id=order.external_order_id,
                observed_state=str(status_result.observed_state.get("status")),
                evidence=status_result.evidence,
            )
        )
        return {"synced": True}

    return run_idempotent(session, idempotency_key, "assignment_sync", _do)

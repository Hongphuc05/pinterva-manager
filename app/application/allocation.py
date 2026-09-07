from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.adapters.db.models import ApprovalDecision, ApprovalRequest, Assignment, Batch, Order, User
from app.application.operations import run_idempotent
from app.application.order_transitions import apply_transition
from app.domain.exceptions import CapacityExceededError
from app.domain.models import OrderState


def _remaining_order_ids(session: Session, batch_id: uuid.UUID) -> list[Order]:
    """Orders of this batch still open for allocation with no Assignment row yet,
    in a stable order (external_order_id) — locked FOR UPDATE so two concurrent
    callers serialize on this batch instead of double-granting an order. Returns
    Order objects (not just ids) since callers need more than the id."""
    assigned_order_ids = session.query(Assignment.order_id).subquery()
    return (
        session.query(Order)
        .filter(
            Order.batch_id == batch_id,
            Order.state == OrderState.OPEN_FOR_ALLOCATION.value,
            ~Order.id.in_(session.query(assigned_order_ids.c.order_id)),
        )
        .order_by(Order.external_order_id)
        .with_for_update()
        .all()
    )


def _held_count(session: Session, designer_id: uuid.UUID) -> int:
    return (
        session.query(Assignment)
        .filter(Assignment.designer_id == designer_id, Assignment.status.in_(["draft", "approved"]))
        .count()
    )


def _grant_orders(
    session: Session,
    orders: list[Order],
    designer_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    replacement_of_id: uuid.UUID | None = None,
) -> list[Assignment]:
    """Create one Assignment (draft) + one ApprovalRequest per order, transitioning
    each order to ASSIGNMENT_PENDING_APPROVAL. One ApprovalRequest per order (spec
    §2.3) — never one for the whole block — so Cancel can release a single order
    without touching its siblings."""
    assignments: list[Assignment] = []
    for order in orders:
        assignment = Assignment(
            order_id=order.id,
            designer_id=designer_id,
            status="draft",
            replacement_of_id=replacement_of_id,
        )
        session.add(assignment)
        session.flush()
        apply_transition(
            session,
            order,
            OrderState.ASSIGNMENT_PENDING_APPROVAL,
            actor_id=actor_id,
            evidence={"source": "allocation"},
        )
        session.add(ApprovalRequest(kind="assignment", target_id=assignment.id))
        assignments.append(assignment)
    return assignments


def _check_capacity(session: Session, designer_id: uuid.UUID, quantity: int) -> None:
    designer = session.get(User, designer_id)
    if designer is None:
        raise ValueError(f"designer {designer_id} not found")
    if designer.capacity is None:
        return
    held = _held_count(session, designer_id)
    if quantity > designer.capacity - held:
        raise CapacityExceededError(designer_id, designer.capacity, held, quantity)


def open_allocation(session: Session, batch_id: uuid.UUID, idempotency_key: str) -> dict:
    def _do() -> dict:
        batch = session.get(Batch, batch_id)
        if batch is None:
            raise ValueError(f"batch {batch_id} not found")
        orders = (
            session.query(Order)
            .filter_by(batch_id=batch.id, state=OrderState.CLAIMED_IMPORTED.value)
            .all()
        )
        order_ids = []
        for order in orders:
            apply_transition(
                session,
                order,
                OrderState.OPEN_FOR_ALLOCATION,
                actor_id=None,
                evidence={"source": "open_allocation"},
            )
            order_ids.append(order.external_order_id)
        batch.lifecycle_state = "allocating"
        session.add(batch)
        return {"order_ids": order_ids}

    return run_idempotent(session, idempotency_key, "open_allocation", _do)


def request_quantity(
    session: Session,
    allocation_tool,
    designer_id: uuid.UUID,
    batch_id: uuid.UUID,
    quantity: int,
    idempotency_key: str,
) -> dict:
    def _do() -> dict:
        _check_capacity(session, designer_id, quantity)
        remaining = _remaining_order_ids(session, batch_id)
        by_ext_id = {o.external_order_id: o for o in remaining}
        granted_ids = allocation_tool.select_block(list(by_ext_id.keys()), quantity)
        ordered_objs = [by_ext_id[oid] for oid in granted_ids]
        assignments = _grant_orders(session, ordered_objs, designer_id, actor_id=designer_id)
        return {
            "granted_order_ids": [o.external_order_id for o in ordered_objs],
            "assignment_ids": [str(a.id) for a in assignments],
        }

    return run_idempotent(session, idempotency_key, "request_quantity", _do)


def create_assignment_draft(
    session: Session,
    order_id: str,
    designer_id: uuid.UUID,
    actor_id: uuid.UUID,
    idempotency_key: str,
) -> dict:
    def _do() -> dict:
        order = session.query(Order).filter_by(external_order_id=order_id).one_or_none()
        if order is None or order.state != OrderState.OPEN_FOR_ALLOCATION.value:
            raise ValueError(f"order {order_id} is not open for allocation")
        _check_capacity(session, designer_id, 1)
        assignments = _grant_orders(session, [order], designer_id, actor_id=actor_id)
        return {"assignment_id": str(assignments[0].id)}

    return run_idempotent(session, idempotency_key, "create_assignment_draft", _do)


def decide_assignment(
    session: Session,
    allocation_tool,
    approval_id: uuid.UUID,
    decision: str,
    actor_id: uuid.UUID,
    idempotency_key: str,
    reason: str | None = None,
) -> dict:
    """decision is "approve" or "cancel". Multi-admin race (claude.md §10): keyed
    only by approval_id (not actor/decision) so run_idempotent's own cache makes
    the FIRST successful call the only one that ever runs _do() — every later call
    on the same approval_id, from any actor, gets that first call's cached result
    back unchanged. The API layer compares result["actor_id"] to the caller's own
    id to phrase "you decided" vs "already decided by someone else"."""
    if decision not in ("approve", "cancel"):
        raise ValueError(f"unknown decision {decision!r}")

    def _do() -> dict:
        approval = session.get(ApprovalRequest, approval_id)
        if approval is None or approval.kind != "assignment":
            raise ValueError(f"assignment approval {approval_id} not found")
        assignment = session.get(Assignment, approval.target_id)
        order = session.get(Order, assignment.order_id)

        if decision == "approve":
            apply_transition(
                session, order, OrderState.ASSIGNED, actor_id=actor_id,
                evidence={"source": "decide_assignment"},
            )
            assignment.status = "approved"
            approval.status = "approved"
            session.add(
                ApprovalDecision(
                    approval_request_id=approval.id, actor_id=actor_id, decision="approve"
                )
            )
            result = {"decision": "approve", "order_id": order.external_order_id}
        else:
            if not reason:
                raise ValueError("cancel requires a reason")
            apply_transition(
                session, order, OrderState.OPEN_FOR_ALLOCATION, actor_id=actor_id,
                evidence={"source": "decide_assignment"},
            )
            assignment.status = "cancelled"
            assignment.cancel_reason = reason
            approval.status = "cancelled"
            session.add(
                ApprovalDecision(
                    approval_request_id=approval.id,
                    actor_id=actor_id,
                    decision="cancel",
                    comment=reason,
                )
            )
            replacement_ids: list[str] = []
            remaining = _remaining_order_ids(session, order.batch_id)
            if remaining:
                by_ext_id = {o.external_order_id: o for o in remaining}
                granted = allocation_tool.select_block(list(by_ext_id.keys()), 1)
                ordered_objs = [by_ext_id[oid] for oid in granted]
                new_assignments = _grant_orders(
                    session, ordered_objs, assignment.designer_id, actor_id=actor_id,
                    replacement_of_id=assignment.id,
                )
                replacement_ids = [str(a.id) for a in new_assignments]
            result = {
                "decision": "cancel",
                "order_id": order.external_order_id,
                "replacement_assignment_ids": replacement_ids,
            }

        result["actor_id"] = str(actor_id)
        result["decided_at"] = datetime.now(UTC).isoformat()
        return result

    return run_idempotent(session, idempotency_key, "decide_assignment", _do)

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.adapters.db.models import Order, WorkflowEvent
from app.domain.models import OrderState
from app.domain.state_machine import validate_transition


def apply_transition(
    session: Session,
    order: Order,
    target_state: OrderState,
    actor_id: uuid.UUID | None,
    evidence: dict,
    commit: bool = True,
) -> WorkflowEvent:
    """`commit=False` lets a caller batch several transitions (plus other writes)
    into one transaction — e.g. allocation's granting loop, which must hold its
    `FOR UPDATE` locks across every order it touches, not release them after the
    first. Every existing caller keeps the old commit-per-call behaviour by
    default."""
    current_state = OrderState(order.state)
    validate_transition(current_state, target_state)

    event = WorkflowEvent(
        order_id=order.id,
        from_state=current_state.value,
        to_state=target_state.value,
        actor_id=actor_id,
        evidence=evidence,
    )
    now_utc = datetime.now(UTC)
    order.state = target_state.value
    order.status_changed_at = now_utc
    if target_state == OrderState.QC_PENDING:
        order.review_submitted_at = now_utc

    session.add(event)
    session.add(order)
    if commit:
        session.commit()
        session.refresh(order)
    return event

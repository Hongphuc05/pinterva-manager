from __future__ import annotations

import uuid

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
) -> WorkflowEvent:
    current_state = OrderState(order.state)
    validate_transition(current_state, target_state)

    event = WorkflowEvent(
        order_id=order.id,
        from_state=current_state.value,
        to_state=target_state.value,
        actor_id=actor_id,
        evidence=evidence,
    )
    order.state = target_state.value
    session.add(event)
    session.add(order)
    session.commit()
    session.refresh(order)
    return event

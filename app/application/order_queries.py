from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.adapters.db.models import Assignment, Order, User, WorkflowEvent


def list_orders_for_user(
    session: Session,
    user: User,
    status: str | None = None,
    batch_id: str | None = None,
    designer_id: str | None = None,
) -> list[Order]:
    """Admin: all orders, optionally filtered. Designer: forced to only their own
    assigned orders (any designer_id param is ignored, never trusted for a designer's
    own view) — status/batch_id filters still apply on top of that.
    """
    query = session.query(Order)

    if user.role == "designer":
        query = query.join(Assignment, Assignment.order_id == Order.id).filter(
            Assignment.designer_id == user.id
        )
    elif designer_id:
        try:
            designer_uuid = uuid.UUID(designer_id)
        except ValueError:
            return []
        query = query.join(Assignment, Assignment.order_id == Order.id).filter(
            Assignment.designer_id == designer_uuid
        )

    if status:
        query = query.filter(Order.state == status)

    if batch_id:
        try:
            batch_uuid = uuid.UUID(batch_id)
        except ValueError:
            return []
        query = query.filter(Order.batch_id == batch_uuid)

    return query.order_by(Order.created_at.desc()).all()


def get_order_detail_for_user(session: Session, user: User, order_id: str) -> Order | None:
    """Admin: any order. Designer: only if they have an Assignment on it — returning
    None either way (not 403) so a designer can't distinguish "doesn't exist" from
    "not yours" by probing IDs.
    """
    try:
        order_uuid = uuid.UUID(order_id)
    except ValueError:
        return None

    order = session.get(Order, order_uuid)
    if order is None:
        return None

    if user.role == "designer":
        has_assignment = (
            session.query(Assignment)
            .filter_by(order_id=order.id, designer_id=user.id)
            .first()
            is not None
        )
        if not has_assignment:
            return None

    return order


def get_order_history(session: Session, order_id: str) -> list[WorkflowEvent]:
    try:
        order_uuid = uuid.UUID(order_id)
    except ValueError:
        return []
    return (
        session.query(WorkflowEvent)
        .filter_by(order_id=order_uuid)
        .order_by(WorkflowEvent.created_at)
        .all()
    )

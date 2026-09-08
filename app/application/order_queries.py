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
    platform_id: uuid.UUID | None = None,
) -> list[Order]:
    """Admin and Designer: all platform orders, optionally filtered. Read-only for designers.
    If designer_id is passed, filter by assigned designer.
    """
    query = session.query(Order)

    if platform_id:
        query = query.filter((Order.platform_id == platform_id) | (Order.platform_id.is_(None)))

    if designer_id:
        if designer_id == "unassigned":
            subq = session.query(Assignment.order_id).filter(Assignment.status == "approved")
            query = query.filter(Order.id.not_in(subq))
        else:
            try:
                designer_uuid = uuid.UUID(designer_id)
            except ValueError:
                return []
            query = query.join(Assignment, Assignment.order_id == Order.id).filter(
                Assignment.designer_id == designer_uuid, Assignment.status == "approved"
            )

    if status:
        query = query.filter(Order.state == status)

    if batch_id:
        try:
            batch_uuid = uuid.UUID(batch_id)
        except ValueError:
            return []
        query = query.filter(Order.batch_id == batch_uuid)

    return query.distinct().order_by(Order.created_at.desc()).all()


def get_order_detail_for_user(session: Session, user: User, order_id: str) -> Order | None:
    """Return Order detail for Admin or Designer in platform."""
    try:
        order_uuid = uuid.UUID(order_id)
    except ValueError:
        return None

    order = session.get(Order, order_uuid)
    if order is None:
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

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
    """Admin sees all platform orders (optionally filtered).
    Designer sees ONLY orders assigned to themselves.
    """
    if user.role == "designer":
        designer_id = str(user.id)

    query = session.query(Order)

    if platform_id:
        query = query.filter(Order.platform_id == platform_id)

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
    """Return Order detail for Admin or Designer in platform.
    If user is a Designer, they can only view orders assigned to themselves.
    Supports both internal UUID string and external_order_id string (e.g. DJ1475461).
    """
    order = None
    try:
        order_uuid = uuid.UUID(order_id)
        order = session.get(Order, order_uuid)
    except ValueError:
        pass

    if order is None:
        order = session.query(Order).filter(Order.external_order_id == order_id).first()

    if order is None:
        return None

    if user.role == "designer":
        assignment = (
            session.query(Assignment)
            .filter(
                Assignment.order_id == order.id,
                Assignment.designer_id == user.id,
                Assignment.status != "cancelled",
            )
            .first()
        )
        if assignment is None:
            return None

    return order


def get_order_history(session: Session, order_id: str) -> list[WorkflowEvent]:
    order_uuid = None
    try:
        order_uuid = uuid.UUID(order_id)
    except ValueError:
        order = session.query(Order).filter(Order.external_order_id == order_id).first()
        if order:
            order_uuid = order.id

    if not order_uuid:
        return []

    return (
        session.query(WorkflowEvent)
        .filter_by(order_id=order_uuid)
        .order_by(WorkflowEvent.created_at)
        .all()
    )


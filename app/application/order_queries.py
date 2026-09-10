from __future__ import annotations

import uuid

from sqlalchemy import or_
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
            query = query.filter(Order.id.not_in(subq), Order.printerval_designer.is_(None))
        else:
            try:
                designer_uuid = uuid.UUID(designer_id)
            except ValueError:
                return []
            target_user = session.get(User, designer_uuid)
            printerval_opt = target_user.printerval_designer_option if target_user else None
            full_name = target_user.full_name if target_user else None

            conds = [
                Order.id.in_(
                    session.query(Assignment.order_id).filter(
                        Assignment.designer_id == designer_uuid,
                        Assignment.status == "approved",
                    )
                )
            ]
            if printerval_opt:
                conds.append(Order.printerval_designer == printerval_opt)
            if full_name:
                conds.append(Order.printerval_designer == full_name)
            query = query.filter(or_(*conds))

    if status:
        st = status.strip()
        st_upper = st.upper()
        if st_upper == "TODO":
            query = query.filter(
                or_(
                    Order.state.in_(["WAITING", "ASSIGNED", "OPEN_FOR_ALLOCATION", "DISCOVERED", "PENDING"]),
                    (Order.state.in_(["REVISION", "FIX"]) & (Order.fix_approved_by_admin.is_(True))),
                )
            )
        elif st_upper in ("WAITING", "OPEN_FOR_ALLOCATION", "DISCOVERED", "PENDING"):
            query = query.filter(
                or_(
                    Order.state.in_(["WAITING", "OPEN_FOR_ALLOCATION", "DISCOVERED", "PENDING"]),
                    Order.printerval_status.ilike("waiting"),
                )
            )
        elif st_upper in ("DOING", "IN_PROGRESS", "ASSIGNED"):
            query = query.filter(
                or_(
                    Order.state.in_(["IN_PROGRESS", "ASSIGNED"]),
                    Order.printerval_status.ilike("doing"),
                )
            )
        elif st_upper in ("DONE", "COMPLETED", "CLAIMED_IMPORTED"):
            query = query.filter(
                or_(
                    Order.state.in_(["DONE", "COMPLETED", "CLAIMED_IMPORTED"]),
                    Order.printerval_status.ilike("done"),
                )
            )
        elif st_upper in ("REVIEW", "QC_PENDING", "RESULT_SUBMITTED"):
            query = query.filter(
                or_(
                    Order.state.in_(["QC_PENDING", "RESULT_SUBMITTED", "SUBMITTING_TO_SITE", "REVIEW"]),
                    Order.printerval_status.ilike("review"),
                )
            )
        elif st_upper in ("FIX", "REVISION", "REVISION_REQUESTED"):
            query = query.filter(
                or_(
                    Order.state.in_(["REVISION", "REVISION_REQUESTED", "FIX"]),
                    Order.printerval_status.ilike("fix"),
                )
            )
        else:
            query = query.filter(
                or_(
                    Order.state == st,
                    Order.state == st_upper,
                    Order.printerval_status.ilike(st),
                )
            )

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
        is_printerval_match = (
            bool(user.printerval_designer_option and order.printerval_designer == user.printerval_designer_option)
            or bool(user.full_name and order.printerval_designer == user.full_name)
        )
        if assignment is None and not is_printerval_match:
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


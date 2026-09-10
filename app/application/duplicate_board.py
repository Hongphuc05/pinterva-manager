"""Commands and read model for the shared duplicate-order Trello board."""

from __future__ import annotations

import uuid

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.adapters.db.models import Assignment, Order, User, WorkflowEvent
from app.domain.access import (
    ROLE_ADMIN,
    ROLE_DESIGNER_TRELLO,
    WORK_DOMAIN_DUPLICATE,
    WORK_DOMAINS,
)


class DuplicateBoardError(ValueError):
    pass


def _active_assignments(session: Session, order_id: uuid.UUID, *, lock: bool) -> list[Assignment]:
    query = session.query(Assignment).filter(
        Assignment.order_id == order_id,
        Assignment.status.in_(("draft", "approved")),
    )
    if lock:
        query = query.with_for_update()
    return query.all()


def _same_platform_or_unscoped(user: User, platform_id: uuid.UUID) -> bool:
    return user.platform_id is None or user.platform_id == platform_id


def _event(session: Session, order: Order, actor_id: uuid.UUID, action: str, **evidence) -> None:
    session.add(
        WorkflowEvent(
            order_id=order.id,
            from_state=order.state,
            to_state=order.state,
            actor_id=actor_id,
            evidence={"source": "duplicate_board", "action": action, **evidence},
        )
    )


def _cancel_assignments(
    session: Session, assignments: list[Assignment], *, reason: str
) -> None:
    for assignment in assignments:
        assignment.status = "cancelled"
        assignment.cancel_reason = reason
        session.add(assignment)


def set_orders_work_domain(
    session: Session,
    *,
    actor: User,
    platform_id: uuid.UUID,
    order_ids: list[uuid.UUID],
    work_domain: str,
) -> int:
    """Move selected orders into/out of the duplicate workspace safely."""
    if actor.role != ROLE_ADMIN:
        raise DuplicateBoardError("Chỉ admin được thay đổi domain đơn hàng")
    if not order_ids:
        raise DuplicateBoardError("Danh sách đơn hàng không được để trống")
    if len(set(order_ids)) != len(order_ids):
        raise DuplicateBoardError("Danh sách đơn hàng bị trùng")
    if work_domain not in WORK_DOMAINS:
        raise DuplicateBoardError("Domain đơn hàng không hợp lệ")

    orders = (
        session.query(Order)
        .filter(Order.id.in_(order_ids))
        .with_for_update()
        .all()
    )
    if len(orders) != len(order_ids) or any(order.platform_id != platform_id for order in orders):
        raise DuplicateBoardError("Mỗi đơn phải thuộc platform đang chọn")

    for order in orders:
        if order.work_domain == work_domain:
            continue
        active_assignments = _active_assignments(session, order.id, lock=True)
        _cancel_assignments(
            session,
            active_assignments,
            reason=f"moved_to_{work_domain}_domain",
        )
        previous_domain = order.work_domain
        order.work_domain = work_domain
        session.add(order)
        _event(
            session,
            order,
            actor.id,
            "work_domain_changed",
            from_domain=previous_domain,
            to_domain=work_domain,
            cancelled_assignment_ids=[str(item.id) for item in active_assignments],
        )
    session.commit()
    return len(orders)


def _get_target_designer(
    session: Session, target_designer_id: uuid.UUID, platform_id: uuid.UUID
) -> User:
    target = session.get(User, target_designer_id)
    if (
        target is None
        or not target.active
        or target.role != ROLE_DESIGNER_TRELLO
        or not _same_platform_or_unscoped(target, platform_id)
    ):
        raise DuplicateBoardError("Designer Trello không hợp lệ cho platform này")
    return target


def move_duplicate_order(
    session: Session,
    *,
    actor: User,
    platform_id: uuid.UUID,
    order_id: uuid.UUID,
    target_designer_id: uuid.UUID | None,
) -> dict:
    """Claim, release or admin-reassign one duplicate-domain card.

    The Order lock serializes simultaneous drops. Assignments are deliberately
    cancelled instead of overwritten, preserving the ownership history.
    """
    order = (
        session.query(Order)
        .filter(Order.id == order_id, Order.platform_id == platform_id)
        .with_for_update()
        .one_or_none()
    )
    if order is None:
        raise DuplicateBoardError("Không tìm thấy đơn hàng trong platform đang chọn")
    if order.work_domain != WORK_DOMAIN_DUPLICATE:
        raise DuplicateBoardError("Đơn chưa thuộc domain Đơn trùng lặp")

    active_assignments = _active_assignments(session, order.id, lock=True)
    current_assignment = next(
        (
            item
            for item in active_assignments
            if (designer := session.get(User, item.designer_id)) is not None
            and designer.role == ROLE_DESIGNER_TRELLO
        ),
        None,
    )
    if actor.role not in (ROLE_ADMIN, ROLE_DESIGNER_TRELLO):
        raise DuplicateBoardError("Bạn không có quyền thay đổi board này")

    if actor.role == ROLE_DESIGNER_TRELLO:
        if target_designer_id not in (None, actor.id):
            raise DuplicateBoardError("Designer Trello chỉ có thể nhận đơn cho chính mình")
        if target_designer_id is None and current_assignment and current_assignment.designer_id != actor.id:
            raise DuplicateBoardError("Bạn chỉ có thể trả đơn do chính mình nhận")

    target = _get_target_designer(session, target_designer_id, platform_id) if target_designer_id else None
    if current_assignment and target and current_assignment.designer_id == target.id:
        return _card(order, target)

    _cancel_assignments(session, active_assignments, reason="duplicate_board_reassigned")
    if target:
        assignment = Assignment(order_id=order.id, designer_id=target.id, status="approved")
        session.add(assignment)
        action = "claimed" if not current_assignment else "reassigned"
    else:
        action = "released"
    _event(
        session,
        order,
        actor.id,
        action,
        from_designer_id=str(current_assignment.designer_id) if current_assignment else None,
        to_designer_id=str(target.id) if target else None,
    )
    session.commit()
    return _card(order, target)


def _card(order: Order, assignee: User | None) -> dict:
    return {
        "id": str(order.id),
        "external_order_id": order.external_order_id,
        "product_name": order.product_name,
        "thumbnail_url": order.thumbnail_url,
        "deadline_at_ext": order.deadline_at_ext.isoformat() if order.deadline_at_ext else None,
        "state": order.state,
        "assignee_id": str(assignee.id) if assignee else None,
        "assignee_name": (assignee.full_name or assignee.username) if assignee else None,
    }


def list_duplicate_board(session: Session, *, platform_id: uuid.UUID) -> list[dict]:
    designers = (
        session.query(User)
        .filter(
            User.role == ROLE_DESIGNER_TRELLO,
            User.active.is_(True),
            or_(User.platform_id == platform_id, User.platform_id.is_(None)),
        )
        .order_by(User.full_name, User.username)
        .all()
    )
    columns = [{"id": "unassigned", "title": "Thiếu form", "cards": []}]
    columns.extend(
        {"id": str(designer.id), "title": designer.full_name or designer.username, "cards": []}
        for designer in designers
    )
    column_by_designer = {str(designer.id): column for designer, column in zip(designers, columns[1:])}

    orders = (
        session.query(Order)
        .filter(Order.platform_id == platform_id, Order.work_domain == WORK_DOMAIN_DUPLICATE)
        .order_by(Order.deadline_at_ext.nullslast(), Order.created_at.desc())
        .all()
    )
    active_assignments = (
        session.query(Assignment, User)
        .join(User, User.id == Assignment.designer_id)
        .filter(
            Assignment.order_id.in_([order.id for order in orders]),
            Assignment.status == "approved",
            User.role == ROLE_DESIGNER_TRELLO,
        )
        .all()
        if orders
        else []
    )
    assignment_by_order = {assignment.order_id: designer for assignment, designer in active_assignments}
    for order in orders:
        assignee = assignment_by_order.get(order.id)
        target_column = column_by_designer.get(str(assignee.id)) if assignee else None
        (target_column or columns[0])["cards"].append(_card(order, assignee))
    return columns

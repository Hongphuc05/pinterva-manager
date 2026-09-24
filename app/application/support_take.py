"""Support's "Lấy": take duplicate orders for the in-house designer instead of the board.

A duplicate order waits in the Duplicate Board's "Đơn hàng" column for outside (Trello) designers.
Taking it assigns it to the company's own designer (``support_take_designer_username``, "des1") through
the ordinary assignment command, so it follows the normal flow (Doing, Review, ...) and counts as
that designer's work. It leaves the board because the board only lists ``work_domain == duplicate``;
revoking the assignment puts it back (see ``revoke_assignment_command``).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.adapters.db.models import Assignment, Order, User, WorkflowEvent
from app.application.assignment_commands import AssignmentCommandError, queue_assignment_command
from app.config import get_settings
from app.domain.access import (
    DUPLICATE_CHECK_DUPLICATE,
    ROLE_ADMIN,
    ROLE_DESIGNER,
    ROLE_SUPPORT,
    WORK_DOMAIN_DUPLICATE,
    WORK_DOMAIN_STANDARD,
)
from app.domain.models import OrderState

# A duplicate card that already has a Designer, or is past Doing, is not "taken" from the board.
TAKEABLE_STATES = (OrderState.IN_PROGRESS.value, OrderState.WAITING.value)


class TakeDuplicateError(AssignmentCommandError):
    pass


def take_duplicate_orders(
    session: Session,
    *,
    actor: User,
    platform_id: uuid.UUID,
    order_ids: list[uuid.UUID],
) -> int:
    if actor.role not in (ROLE_SUPPORT, ROLE_ADMIN):
        raise TakeDuplicateError("Chỉ Support hoặc Admin được lấy đơn trùng lặp")
    if not order_ids or len(set(order_ids)) != len(order_ids):
        raise TakeDuplicateError("Danh sách đơn hàng không hợp lệ")

    username = get_settings().support_take_designer_username
    designer = (
        session.query(User)
        .filter(User.username == username, User.role == ROLE_DESIGNER, User.active.is_(True))
        .first()
    )
    if designer is None:
        raise TakeDuplicateError(f"Không tìm thấy designer '{username}' đang hoạt động")

    orders = (
        session.query(Order)
        .filter(Order.id.in_(order_ids), Order.platform_id == platform_id)
        .order_by(Order.id)
        .with_for_update()
        .all()
    )
    if len(orders) != len(order_ids):
        raise TakeDuplicateError("Một số đơn hàng không tồn tại hoặc không thuộc nền tảng này")

    for order in orders:
        active = session.query(Assignment).filter(
            Assignment.order_id == order.id, Assignment.status.in_(("draft", "approved"))
        ).count()
        if (
            order.duplicate_check_status != DUPLICATE_CHECK_DUPLICATE
            or order.work_domain != WORK_DOMAIN_DUPLICATE
            or active
            or (order.state or "").upper() not in TAKEABLE_STATES
        ):
            raise TakeDuplicateError(
                f"Đơn {order.external_order_id} không còn ở cột Đơn hàng của board hoặc đã có designer nhận"
            )

    for order in orders:
        # Standard domain = visible to the in-house designer and off the duplicate board.
        order.work_domain = WORK_DOMAIN_STANDARD
        order.duplicate_board_position = None
        session.add(
            WorkflowEvent(
                order_id=order.id,
                from_state=order.state,
                to_state=order.state,
                actor_id=actor.id,
                evidence={"source": "support_take", "action": "taken_from_duplicate_board", "designer": designer.username},
            )
        )
    session.flush()

    _, queued = queue_assignment_command(
        session,
        platform_id=platform_id,
        actor=actor,
        order_ids=order_ids,
        designer_id=designer.id,
        printerval_designer=None,
        printerval_status="Doing",
    )
    return queued

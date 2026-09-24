"""Support puts a classified order back into "Chưa kiểm tra" so it can be checked again.

Allowed only while no designer has taken the order (a designer's work is never undone from here).
A duplicate-tagged order leaves the Duplicate Board (Waiting again, and Printerval goes back to
Waiting when the tag had moved it to Doing). Its earlier comparison result is retired, so the next
/check may queue the order again, and any unanswered Telegram confirmation of the old result is
closed (a late press then says it was already handled).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.adapters.db.models import Order, SupportCompareItem, TelegramActionLog, User
from app.application.concurrency import require_expected_order_version
from app.application.duplicate_board import (
    DuplicateBoardError,
    _active_assignments,
    _dispatch_printerval_requests,
    _event,
    _record_support_classification,
)
from app.application.printerval_assignment_requests import create_request
from app.domain.access import (
    DUPLICATE_CHECK_UNCHECK,
    ROLE_ADMIN,
    ROLE_SUPPORT,
    SUPPORT_CLASSIFICATION_STATES,
    WORK_DOMAIN_DUPLICATE,
    WORK_DOMAIN_STANDARD,
)
from app.domain.models import OrderState

# Telegram confirmations of a comparison result (see support_compare.ACTION_CONFIRM / ACTION_REJECT).
_COMPARE_ACTIONS = ("SUPPORT_COMPARE_CONFIRM_DUPLICATE", "SUPPORT_COMPARE_REJECT_DUPLICATE")


def return_orders_to_unchecked(
    session: Session,
    *,
    actor: User,
    platform_id: uuid.UUID,
    order_ids: list[uuid.UUID],
    expected_versions: dict[uuid.UUID, int] | None = None,
) -> int:
    if actor.role not in (ROLE_SUPPORT, ROLE_ADMIN):
        raise DuplicateBoardError("Chỉ Support hoặc Admin được đưa đơn về Chưa kiểm tra")
    if not order_ids or len(set(order_ids)) != len(order_ids):
        raise DuplicateBoardError("Danh sách đơn hàng không hợp lệ")

    orders = (
        session.query(Order).filter(Order.id.in_(order_ids)).order_by(Order.id).with_for_update().all()
    )
    if len(orders) != len(order_ids) or any(order.platform_id != platform_id for order in orders):
        raise DuplicateBoardError("Mỗi đơn phải thuộc platform đang chọn")

    request_ids: list[uuid.UUID] = []
    for order in orders:
        code = order.external_order_id
        if (order.duplicate_check_status or DUPLICATE_CHECK_UNCHECK) == DUPLICATE_CHECK_UNCHECK:
            raise DuplicateBoardError(f"Đơn {code} đang ở tab Chưa xử lý")
        if _active_assignments(session, order.id, lock=True):
            raise DuplicateBoardError(f"Đơn {code} đã có designer đảm nhận, không đưa về Chưa xử lý được")
        state = (order.state or "").upper()
        on_board = order.work_domain == WORK_DOMAIN_DUPLICATE
        allowed = SUPPORT_CLASSIFICATION_STATES | ({OrderState.IN_PROGRESS.value} if on_board else set())
        if state not in allowed:
            raise DuplicateBoardError(f"Đơn {code} đã sang bước xử lý khác, không đưa về Chưa xử lý được")
        require_expected_order_version(order, (expected_versions or {}).get(order.id))

        prev_state, prev_check = order.state, order.duplicate_check_status
        if on_board:
            order.state = OrderState.WAITING.value
            order.fix_approved_by_admin = False
            if (order.printerval_status or "").lower() == "doing":
                # Tagging it duplicate had moved the source order to Doing: put it back to Waiting.
                request_ids.append(
                    create_request(
                        session,
                        order=order,
                        internal_designer=actor,
                        platform_id=platform_id,
                        designer_option=None,
                        target_status="Waiting",
                        commit=False,
                    ).id
                )
        order.work_domain = WORK_DOMAIN_STANDARD
        order.duplicate_board_position = None
        order.duplicate_check_status = DUPLICATE_CHECK_UNCHECK
        _record_support_classification(order, actor=actor, duplicate_status=DUPLICATE_CHECK_UNCHECK)
        session.add(order)

        # Retire the previous comparison so the order counts as never compared again.
        for item in session.query(SupportCompareItem).filter(
            SupportCompareItem.order_id == order.id, SupportCompareItem.processing_status == "completed"
        ):
            item.processing_status = "skipped"
            item.review_status = None
        for action in session.query(TelegramActionLog).filter(
            TelegramActionLog.order_id == order.id,
            TelegramActionLog.action_type.in_(_COMPARE_ACTIONS),
            TelegramActionLog.status == "pending",
        ):
            action.status = "superseded"

        _event(
            session,
            order,
            actor.id,
            "returned_to_unchecked",
            from_state=prev_state,
            to_state=order.state,
            from_check_status=prev_check,
            to_check_status=DUPLICATE_CHECK_UNCHECK,
        )

    session.commit()
    _dispatch_printerval_requests(request_ids)
    return len(orders)

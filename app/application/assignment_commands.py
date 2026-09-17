"""One command path for internal assignment and Printerval assignment sync."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.adapters.db.models import (
    Assignment,
    Order,
    PrintervalAssignmentRequest,
    User,
    WorkflowEvent,
)
from app.application.printerval_assignment_requests import (
    PRINTERVAL_STATUSES,
    PrintervalAssignmentValidationError,
    create_request,
)
from app.domain.models import OrderState


class AssignmentCommandError(ValueError):
    pass


def queue_assignment_command(
    session: Session,
    *,
    platform_id: uuid.UUID,
    actor: User,
    order_ids: list[uuid.UUID],
    designer_id: uuid.UUID | None,
    printerval_designer: str | None,
    printerval_status: str,
) -> tuple[list[PrintervalAssignmentRequest], int]:
    """Persist one assignment intent for each selected order and enqueue its sync.

    `order_ids` is a command snapshot, so every selected row is validated against
    the active platform before any worker is sent to Printerval.
    """
    if not order_ids:
        raise AssignmentCommandError("Danh sách đơn hàng không được để trống")
    if len(set(order_ids)) != len(order_ids):
        raise AssignmentCommandError("Danh sách đơn hàng bị trùng")
    if printerval_status not in PRINTERVAL_STATUSES:
        raise AssignmentCommandError("Invalid Printerval status")

    designer: User | None = None
    if designer_id is not None:
        designer = session.get(User, designer_id)
        if designer is None or not designer.active:
            raise AssignmentCommandError("Designer not found")

    status_state_map = {
        "Doing": OrderState.IN_PROGRESS,
        "Review": OrderState.QC_PENDING,
        "Fix": OrderState.REVISION,
        "Done": OrderState.DONE,
        "Waiting": OrderState.WAITING,
        "Skipped": OrderState.DONE,
    }
    target_state = status_state_map.get(printerval_status, OrderState.IN_PROGRESS)

    designer_option = (printerval_designer or "").strip()
    if not designer_option and designer is not None and designer.printerval_designer_option:
        designer_option = designer.printerval_designer_option.strip()
    if not designer_option and designer is not None:
        designer_option = "nguyễn thị thúy hường 2d prin"

    orders = (
        session.query(Order)
        .filter(Order.id.in_(order_ids), Order.platform_id == platform_id)
        .all()
    )
    if len(orders) != len(order_ids):
        raise AssignmentCommandError("Một số đơn hàng không tồn tại hoặc không thuộc nền tảng này")

    requests: list[PrintervalAssignmentRequest] = []
    if designer_option:
        for order in orders:
            if designer is not None:
                _upsert_internal_assignment(session, order, designer)
            order.state = target_state.value
            try:
                requests.append(
                    create_request(
                        session,
                        order=order,
                        internal_designer=designer or actor,
                        platform_id=platform_id,
                        designer_option=designer_option,
                        target_status=printerval_status,
                    )
                )
            except PrintervalAssignmentValidationError as exc:
                raise AssignmentCommandError(str(exc)) from exc

        session.commit()

        from app.workers.assignment_sync_tasks import sync_printerval_assignment_request

        for request in requests:
            sync_printerval_assignment_request.delay(str(request.id))
        return requests, len(requests)

    for order in orders:
        if designer is not None:
            _upsert_internal_assignment(session, order, designer)
        order.state = target_state.value
    session.commit()

    # Status-only commands use the same durable request as Designer+Status commands.
    # This makes queued/running/failure visible in Order.printerval_assignment_lifecycle.
    for order in orders:
        try:
            requests.append(
                create_request(
                    session,
                    order=order,
                    internal_designer=designer or actor,
                    platform_id=platform_id,
                    designer_option=None,
                    target_status=printerval_status,
                )
            )
        except PrintervalAssignmentValidationError as exc:
            raise AssignmentCommandError(str(exc)) from exc

    from app.workers.assignment_sync_tasks import sync_printerval_assignment_request

    for request in requests:
        sync_printerval_assignment_request.delay(str(request.id))
    return requests, len(orders)


def _upsert_internal_assignment(session: Session, order: Order, designer: User) -> None:
    assignment = session.query(Assignment).filter(Assignment.order_id == order.id).one_or_none()
    if assignment is None:
        session.add(Assignment(order_id=order.id, designer_id=designer.id, status="approved"))
    else:
        assignment.designer_id = designer.id
        assignment.status = "approved"


def revoke_assignment_command(
    session: Session,
    *,
    platform_id: uuid.UUID,
    actor: User,
    order_ids: list[uuid.UUID],
) -> int:
    """Revoke active assignments for orders before designer submits work.
    Reverts order state to WAITING, clears assigned designer, and cancels active assignments.
    """
    if not order_ids:
        raise AssignmentCommandError("Danh sách đơn hàng không được để trống")
    if len(set(order_ids)) != len(order_ids):
        raise AssignmentCommandError("Danh sách đơn hàng bị trùng")

    orders = (
        session.query(Order)
        .filter(Order.id.in_(order_ids), Order.platform_id == platform_id)
        .all()
    )
    if len(orders) != len(order_ids):
        raise AssignmentCommandError("Một số đơn hàng không tồn tại hoặc không thuộc nền tảng này")

    # Only allowed before designer submits review (state not in QC_PENDING, RESULT_SUBMITTED, REVIEW, DONE, etc.)
    non_revocable = [
        order.external_order_id
        for order in orders
        if order.review_submitted_at is not None
        or (order.state or "").upper() in ("QC_PENDING", "RESULT_SUBMITTED", "REVIEW", "DONE", "COMPLETED", "CLAIMED_IMPORTED")
    ]
    if non_revocable:
        raise AssignmentCommandError(
            f"Chỉ có thể hủy chia đơn trước khi Designer nộp bài. Các đơn sau đã nộp hoặc hoàn thành: {', '.join(non_revocable)}"
        )

    for order in orders:
        prev_state = order.state
        active_assignments = (
            session.query(Assignment)
            .filter(Assignment.order_id == order.id, Assignment.status.in_(("draft", "approved")))
            .all()
        )
        for assignment in active_assignments:
            assignment.status = "cancelled"
            assignment.cancel_reason = f"Revoked by admin {actor.username}"

        order.printerval_designer = None
        order.state = OrderState.WAITING.value
        session.add(
            WorkflowEvent(
                order_id=order.id,
                from_state=prev_state,
                to_state=OrderState.WAITING.value,
                actor_id=actor.id,
                evidence={
                    "source": "assignment_revocation",
                    "action": "assignment_revoked",
                    "revoked_by": actor.username,
                },
            )
        )

    session.commit()
    return len(orders)

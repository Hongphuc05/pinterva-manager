"""One command path for internal assignment and Printerval assignment sync."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.adapters.db.models import Assignment, Order, PrintervalAssignmentRequest, User
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

    orders = session.query(Order).filter(Order.id.in_(order_ids)).all()
    if len(orders) != len(order_ids) or any(order.platform_id != platform_id for order in orders):
        raise AssignmentCommandError("Mỗi đơn phải thuộc platform đang chọn")

    designer_option = (printerval_designer or "").strip()
    requests: list[PrintervalAssignmentRequest] = []
    if designer_option:
        for order in orders:
            if designer is not None:
                _upsert_internal_assignment(session, order, designer)
                order.state = OrderState.WAITING.value
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

        from app.workers.assignment_sync_tasks import sync_printerval_assignment_request

        for request in requests:
            sync_printerval_assignment_request.delay(str(request.id))
        return requests, len(requests)

    status_state_map = {
        "Doing": OrderState.IN_PROGRESS,
        "Review": OrderState.QC_PENDING,
        "Fix": OrderState.REVISION,
        "Done": OrderState.DONE,
        "Waiting": OrderState.WAITING,
        "Skipped": OrderState.DONE,
    }
    mapped_state = status_state_map.get(printerval_status)
    for order in orders:
        if designer is not None:
            _upsert_internal_assignment(session, order, designer)
        if mapped_state:
            order.state = mapped_state.value
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

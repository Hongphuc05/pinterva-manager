"""Commands and read model for the shared duplicate-order Trello board."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.adapters.db.models import Assignment, Order, Platform, ResultVersion, User, WorkflowEvent
from app.application.concurrency import require_expected_order_version
from app.application.printerval_assignment_requests import create_request
from app.application.sanitization import encode_proxy_url, sanitize_text
from app.domain.access import (
    DUPLICATE_CHECK_DUPLICATE,
    DUPLICATE_CHECK_NON_DUPLICATE,
    DUPLICATE_CHECK_STATUSES,
    ROLE_ADMIN,
    ROLE_DESIGNER_TRELLO,
    ROLE_SUPPORT,
    WORK_DOMAIN_DUPLICATE,
    WORK_DOMAIN_STANDARD,
    WORK_DOMAINS,
)
from app.domain.models import OrderState

DONE_STATES = ("DONE", "CLAIMED_IMPORTED", "COMPLETED", "SKIPPED")
logger = logging.getLogger(__name__)


class DuplicateBoardError(ValueError):
    pass


def remove_duplicate_from_backlog(session: Session, *, actor: User, platform_id: uuid.UUID, order_id: uuid.UUID, expected_version: int | None = None) -> None:
    """Return an unclaimed duplicate-board card to the ordinary Waiting queue.

    This is deliberately not a delete: the order remains auditable and becomes
    available for normal-designer assignment again.
    """
    order = session.query(Order).filter(Order.id == order_id, Order.platform_id == platform_id).with_for_update().one_or_none()
    if order is None or order.work_domain != WORK_DOMAIN_DUPLICATE:
        raise DuplicateBoardError("Đơn không còn thuộc board Đơn trùng lặp")
    require_expected_order_version(order, expected_version)
    if actor.role not in (ROLE_ADMIN, ROLE_SUPPORT, ROLE_DESIGNER_TRELLO):
        raise DuplicateBoardError("Bạn không có quyền hủy đơn trùng lặp")
    active = _active_assignments(session, order.id, lock=True)
    if active or order.template_missing or order.state != OrderState.IN_PROGRESS.value:
        raise DuplicateBoardError("Chỉ được hủy đơn đang ở cột Đơn hàng chưa có Designer nhận")
    old_state = order.state
    order.work_domain = WORK_DOMAIN_STANDARD
    order.duplicate_check_status = "uncheck"
    order.state = OrderState.WAITING.value
    order.status_changed_at = datetime.now(UTC)
    _event(session, order, actor.id, "removed_from_duplicate_backlog", from_state=old_state, to_state=order.state)
    session.commit()


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


def _event(
    session: Session,
    order: Order,
    actor_id: uuid.UUID,
    action: str,
    *,
    from_state: str | None = None,
    to_state: str | None = None,
    **evidence,
) -> None:
    session.add(
        WorkflowEvent(
            order_id=order.id,
            from_state=from_state if from_state is not None else order.state,
            to_state=to_state if to_state is not None else order.state,
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


def _create_duplicate_board_doing_request(
    session: Session,
    *,
    order: Order,
    actor: User,
    platform_id: uuid.UUID,
) -> uuid.UUID:
    """Record the status-only external update required when an order enters this board.

    The internal board deliberately starts the card at WAITING.  Its source
    order, however, must be moved to Doing.  Keep that write in the existing
    auditable request lifecycle and leave the source-side designer untouched.
    """
    request = create_request(
        session,
        order=order,
        internal_designer=actor,
        platform_id=platform_id,
        designer_option=None,
        target_status="Doing",
        commit=False,
    )
    return request.id


def _dispatch_printerval_requests(request_ids: list[uuid.UUID]) -> None:
    """Queue committed sync intents without making the board mutation depend on Celery."""
    if not request_ids:
        return
    from app.workers.assignment_sync_tasks import sync_printerval_assignment_request

    for request_id in request_ids:
        try:
            sync_printerval_assignment_request.delay(str(request_id))
        except Exception:
            # The intent is already committed and remains visible/retriable in
            # its request lifecycle.  Do not report the board move as failed.
            # This matches the existing duplicate-board dispatch semantics.
            logger.exception("Failed to queue Printerval status sync request %s", request_id)


def set_orders_work_domain(
    session: Session,
    *,
    actor: User,
    platform_id: uuid.UUID,
    order_ids: list[uuid.UUID],
    work_domain: str,
    expected_versions: dict[uuid.UUID, int] | None = None,
) -> int:
    """Move selected orders into/out of the duplicate workspace safely."""
    if actor.role not in (ROLE_ADMIN, ROLE_SUPPORT):
        raise DuplicateBoardError("Chỉ admin và support được thay đổi domain đơn hàng")
    if not order_ids:
        raise DuplicateBoardError("Danh sách đơn hàng không được để trống")
    if len(set(order_ids)) != len(order_ids):
        raise DuplicateBoardError("Danh sách đơn hàng bị trùng")
    if work_domain not in WORK_DOMAINS:
        raise DuplicateBoardError("Domain đơn hàng không hợp lệ")

    orders = (
        session.query(Order)
        .filter(Order.id.in_(order_ids))
        .order_by(Order.id)
        .with_for_update()
        .all()
    )
    if len(orders) != len(order_ids) or any(order.platform_id != platform_id for order in orders):
        raise DuplicateBoardError("Mỗi đơn phải thuộc platform đang chọn")

    request_ids: list[uuid.UUID] = []
    for order in orders:
        require_expected_order_version(order, (expected_versions or {}).get(order.id))
        if order.work_domain == work_domain:
            continue
        active_assignments = _active_assignments(session, order.id, lock=True)
        _cancel_assignments(
            session,
            active_assignments,
            reason=f"moved_to_{work_domain}_domain",
        )
        previous_domain = order.work_domain
        previous_state = order.state
        order.work_domain = work_domain
        # A duplicate card enters the shared board pool already in Doing. The
        # board itself owns assignment, so it must leave the standard Waiting queue.
        if work_domain == WORK_DOMAIN_DUPLICATE:
            order.state = OrderState.IN_PROGRESS.value
            order.status_changed_at = datetime.now(UTC)
            order.printerval_designer = None
            order.duplicate_check_status = DUPLICATE_CHECK_DUPLICATE
            order.template_missing = False
            order.fix_approved_by_admin = False
            request_ids.append(
                _create_duplicate_board_doing_request(
                    session,
                    order=order,
                    actor=actor,
                    platform_id=platform_id,
                )
            )
        else:
            order.state = OrderState.WAITING.value
            order.duplicate_check_status = DUPLICATE_CHECK_NON_DUPLICATE
            order.fix_approved_by_admin = False
        session.add(order)
        _event(
            session,
            order,
            actor.id,
            "work_domain_changed",
            from_state=previous_state,
            to_state=order.state,
            from_domain=previous_domain,
            to_domain=work_domain,
            cancelled_assignment_ids=[str(item.id) for item in active_assignments],
        )
    session.commit()
    _dispatch_printerval_requests(request_ids)
    return len(orders)


def set_orders_duplicate_status(
    session: Session,
    *,
    actor: User,
    platform_id: uuid.UUID,
    order_ids: list[uuid.UUID],
    duplicate_status: str,
    expected_versions: dict[uuid.UUID, int] | None = None,
) -> int:
    """Update duplicate verification status for orders (by Admin or Support)."""
    if actor.role not in (ROLE_ADMIN, ROLE_SUPPORT):
        raise DuplicateBoardError("Chỉ admin và support được thay đổi trạng thái trùng lặp của đơn hàng")
    if not order_ids:
        raise DuplicateBoardError("Danh sách đơn hàng không được để trống")
    if len(set(order_ids)) != len(order_ids):
        raise DuplicateBoardError("Danh sách đơn hàng bị trùng")
    if duplicate_status not in DUPLICATE_CHECK_STATUSES:
        raise DuplicateBoardError("Trạng thái kiểm tra trùng lặp không hợp lệ")

    orders = (
        session.query(Order)
        .filter(Order.id.in_(order_ids))
        .order_by(Order.id)
        .with_for_update()
        .all()
    )
    if len(orders) != len(order_ids) or any(order.platform_id != platform_id for order in orders):
        raise DuplicateBoardError("Mỗi đơn phải thuộc platform đang chọn")

    request_ids: list[uuid.UUID] = []
    for order in orders:
        require_expected_order_version(order, (expected_versions or {}).get(order.id))
        prev_domain = order.work_domain
        prev_state = order.state
        prev_check_status = order.duplicate_check_status
        cancelled_ids = []

        if duplicate_status == DUPLICATE_CHECK_DUPLICATE:
            target_domain = WORK_DOMAIN_DUPLICATE
            order.work_domain = target_domain
            order.duplicate_check_status = DUPLICATE_CHECK_DUPLICATE
            order.state = OrderState.IN_PROGRESS.value
            order.status_changed_at = datetime.now(UTC)
            order.printerval_designer = None
            order.template_missing = False
            order.fix_approved_by_admin = False
            active_assignments = _active_assignments(session, order.id, lock=True)
            _cancel_assignments(
                session,
                active_assignments,
                reason="moved_to_duplicate_domain",
            )
            cancelled_ids = [str(item.id) for item in active_assignments]
            if prev_domain != WORK_DOMAIN_DUPLICATE or prev_state != OrderState.IN_PROGRESS.value:
                request_ids.append(
                    _create_duplicate_board_doing_request(
                        session,
                        order=order,
                        actor=actor,
                        platform_id=platform_id,
                    )
                )
        else:
            target_domain = WORK_DOMAIN_STANDARD
            order.work_domain = target_domain
            order.duplicate_check_status = duplicate_status
            if prev_domain == WORK_DOMAIN_DUPLICATE:
                order.state = OrderState.WAITING.value
                order.fix_approved_by_admin = False

        session.add(order)
        _event(
            session,
            order,
            actor.id,
            "duplicate_status_changed",
            from_state=prev_state,
            to_state=order.state,
            from_domain=prev_domain,
            to_domain=order.work_domain,
            from_check_status=prev_check_status,
            to_check_status=duplicate_status,
            cancelled_assignment_ids=cancelled_ids,
        )

    session.commit()
    _dispatch_printerval_requests(request_ids)
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
    expected_version: int | None = None,
    target_column_id: str | None = None,
    target_designer_id: uuid.UUID | None = None,
    before_order_id: uuid.UUID | None = None,
    reorder: bool = False,
) -> dict:
    """Claim, release, mark done or reassign a duplicate-domain card.

    Supports target columns:
    - 'orders': unassigned pool
    - 'missing_form' / 'unassigned': missing template unassigned pool
    - 'done': completed pool
    - '<designer_id>' / target_designer_id: assign to a Trello designer
    """
    order = (
        session.query(Order)
        .filter(Order.id == order_id, Order.platform_id == platform_id)
        .with_for_update()
        .one_or_none()
    )
    if order is None:
        raise DuplicateBoardError("Không tìm thấy đơn hàng trong platform đang chọn")
    require_expected_order_version(order, expected_version)
    if order.work_domain != WORK_DOMAIN_DUPLICATE:
        raise DuplicateBoardError("Đơn chưa thuộc domain Đơn trùng lặp")

    platform = session.get(Platform, platform_id)
    if platform is None:
        raise DuplicateBoardError("Không tìm thấy platform đang chọn")

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
    if (
        actor.role == ROLE_DESIGNER_TRELLO
        and (order.state or "").upper() in {"REVISION", "REVISION_REQUESTED", "FIX"}
        and not order.fix_approved_by_admin
    ):
        raise DuplicateBoardError("Đơn Fix đang chờ Admin chấp nhận và giao lại; bạn chưa thể thao tác")

    # Determine destination type
    col_id = (target_column_id or "").strip()
    designer_uuid = target_designer_id

    if not designer_uuid and col_id and col_id not in ("orders", "missing_form", "unassigned", "done"):
        try:
            designer_uuid = uuid.UUID(col_id)
        except ValueError:
            pass

    # Permission checks for Designer Trello
    if actor.role == ROLE_DESIGNER_TRELLO:
        if not platform.duplicate_board_cross_designer_drag_enabled:
            # When cross drag is disabled:
            # Can only move to own column, to done, to missing_form, or to orders if currently holding it
            if designer_uuid and designer_uuid != actor.id:
                raise DuplicateBoardError("Admin đang tắt quyền kéo thẻ sang cột Designer khác")
            if current_assignment and current_assignment.designer_id != actor.id:
                raise DuplicateBoardError("Bạn chỉ có thể thao tác với đơn do chính mình nhận hoặc nhận đơn từ kho chung")

    from_st = order.state

    # 1. Target: "orders" (Unassigned pool, template is OK)
    if col_id == "orders" or (col_id == "" and designer_uuid is None):
        _cancel_assignments(session, active_assignments, reason="duplicate_board_released_to_orders")
        order.template_missing = False
        order.state = OrderState.WAITING.value
        _event(
            session,
            order,
            actor.id,
            "released_to_orders",
            from_designer_id=str(current_assignment.designer_id) if current_assignment else None,
            from_state=from_st,
            to_state=order.state,
        )
        if reorder:
            _reorder_duplicate_board(
                session,
                platform_id=platform_id,
                moved_order_id=order.id,
                target_column_id="orders",
                before_order_id=before_order_id,
            )
        session.commit()
        return _card(order, None, hide_internal_notes=actor.role == ROLE_DESIGNER_TRELLO)

    # 2. Target: "missing_form" / "unassigned" (Missing template pool)
    if col_id in ("missing_form", "unassigned"):
        _cancel_assignments(session, active_assignments, reason="duplicate_board_flagged_missing_form")
        order.template_missing = True
        order.state = OrderState.WAITING.value
        _event(
            session,
            order,
            actor.id,
            "flagged_missing_form",
            from_designer_id=str(current_assignment.designer_id) if current_assignment else None,
            from_state=from_st,
            to_state=order.state,
        )
        if reorder:
            _reorder_duplicate_board(
                session,
                platform_id=platform_id,
                moved_order_id=order.id,
                target_column_id="missing_form",
                before_order_id=before_order_id,
            )
        session.commit()
        return _card(order, None, hide_internal_notes=actor.role == ROLE_DESIGNER_TRELLO)

    # 3. Target: "done" (Completed column)
    if col_id == "done":
        order.state = OrderState.DONE.value
        order.status_changed_at = datetime.now(UTC)
        order.template_missing = False
        assignee = None
        if current_assignment:
            assignee = session.get(User, current_assignment.designer_id)
        elif actor.role == ROLE_DESIGNER_TRELLO:
            assignment = Assignment(order_id=order.id, designer_id=actor.id, status="approved")
            session.add(assignment)
            assignee = actor
        _event(
            session,
            order,
            actor.id,
            "marked_done",
            from_state=from_st,
            to_state="DONE",
            designer_id=str(assignee.id) if assignee else None,
        )
        if reorder:
            _reorder_duplicate_board(
                session,
                platform_id=platform_id,
                moved_order_id=order.id,
                target_column_id="done",
                before_order_id=before_order_id,
            )
        session.commit()
        return _card(order, assignee, hide_internal_notes=actor.role == ROLE_DESIGNER_TRELLO)

    # 4. Target: Specific Designer column
    if designer_uuid:
        target = _get_target_designer(session, designer_uuid, platform_id)
        order.template_missing = False
        order.state = OrderState.IN_PROGRESS.value

        if current_assignment and current_assignment.designer_id == target.id:
            if reorder:
                _reorder_duplicate_board(
                    session,
                    platform_id=platform_id,
                    moved_order_id=order.id,
                    target_column_id=str(target.id),
                    before_order_id=before_order_id,
                )
            session.commit()
            return _card(order, target, hide_internal_notes=actor.role == ROLE_DESIGNER_TRELLO)

        _cancel_assignments(session, active_assignments, reason="duplicate_board_reassigned")
        assignment = Assignment(order_id=order.id, designer_id=target.id, status="approved")
        session.add(assignment)
        action = "claimed" if not current_assignment else "reassigned"
        _event(
            session,
            order,
            actor.id,
            action,
            from_designer_id=str(current_assignment.designer_id) if current_assignment else None,
            to_designer_id=str(target.id),
            from_state=from_st,
            to_state=order.state,
        )

        designer_option = (target.printerval_designer_option or "").strip() or "nguyễn thị thúy hường 2d prin"
        try:
            req = create_request(
                session,
                order=order,
                internal_designer=target,
                platform_id=platform_id,
                designer_option=designer_option,
                target_status="Doing",
            )
            from app.workers.assignment_sync_tasks import sync_printerval_assignment_request
            sync_printerval_assignment_request.delay(str(req.id))
        except Exception:
            pass

        if reorder:
            _reorder_duplicate_board(
                session,
                platform_id=platform_id,
                moved_order_id=order.id,
                target_column_id=str(target.id),
                before_order_id=before_order_id,
            )
        session.commit()

        # Telegram notification for designer
        try:
            from app.workers.telegram_tasks import (
                async_notify_designer_new_order,
                safe_dispatch_telegram_task,
            )

            safe_dispatch_telegram_task(async_notify_designer_new_order, str(order.id), str(target.id))
        except Exception:
            pass

        return _card(order, target, hide_internal_notes=actor.role == ROLE_DESIGNER_TRELLO)

    raise DuplicateBoardError("Cột đích không hợp lệ")


def _card(
    order: Order,
    assignee: User | None,
    *,
    hide_internal_notes: bool = False,
    latest_submission: ResultVersion | None = None,
) -> dict:
    return {
        "id": str(order.id),
        "version": order.version,
        "external_order_id": order.external_order_id,
        "product_name": order.product_name,
        "thumbnail_url": encode_proxy_url(order.thumbnail_url),
        "deadline_tacahu": order.deadline_tacahu.isoformat() if order.deadline_tacahu else None,
        "order_created_at_ext": order.order_created_at_ext.isoformat() if order.order_created_at_ext else None,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
        "status_changed_at": order.status_changed_at.isoformat() if order.status_changed_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "is_paid": bool(order.is_paid),
        "template_missing": bool(order.template_missing),
        "state": order.state,
        "note_outsource": "" if hide_internal_notes else (sanitize_text(order.note_outsource, "Web mẹ") or ""),
        "previous_note_outsource": None if hide_internal_notes else sanitize_text(order.previous_note_outsource, "Web mẹ"),
        "fix_approved_by_admin": order.fix_approved_by_admin,
        "fix_return_count": order.fix_return_count,
        "assignee_id": str(assignee.id) if assignee else None,
        "assignee_name": (assignee.full_name or assignee.username) if assignee else None,
        "duplicate_board_position": order.duplicate_board_position,
        # The shared Trello board is deliberately a collaboration surface. This
        # is the only Designer-facing read model that exposes a submitted
        # result link, and only for duplicate-domain orders.
        "submission_url": latest_submission.drive_url if latest_submission else None,
        "submission_version": latest_submission.version_marker if latest_submission else None,
    }


def _column_metrics(cards: list[dict]) -> dict[str, int]:
    return {
        "total": len(cards),
        "doing": sum(card["state"] == OrderState.IN_PROGRESS.value for card in cards),
        "review": sum(card["state"] == OrderState.QC_PENDING.value for card in cards),
        "fix": sum(card["state"] == OrderState.REVISION.value for card in cards),
        "done": sum((card["state"] in DONE_STATES or card.get("is_paid", False)) for card in cards),
    }


def _board_order_buckets(session: Session, *, platform_id: uuid.UUID) -> dict[str, list[Order]]:
    """Return the current card order for every rendered duplicate-board column."""
    orders = (
        session.query(Order)
        .filter(Order.platform_id == platform_id, Order.work_domain == WORK_DOMAIN_DUPLICATE)
        .order_by(
            Order.duplicate_board_position.asc().nullslast(),
            Order.deadline_tacahu.nullslast(),
            Order.created_at.desc(),
        )
        .all()
    )
    active_assignments = (
        session.query(Assignment, User)
        .join(User, User.id == Assignment.designer_id)
        .filter(
            Assignment.order_id.in_([order.id for order in orders]),
            Assignment.status.in_(("approved", "draft")),
            User.role == ROLE_DESIGNER_TRELLO,
        )
        .order_by(Assignment.created_at.desc())
        .all()
        if orders
        else []
    )
    assignment_by_order: dict[uuid.UUID, User] = {}
    for assignment, designer in active_assignments:
        if assignment.order_id not in assignment_by_order:
            assignment_by_order[assignment.order_id] = designer

    buckets: dict[str, list[Order]] = {"orders": [], "missing_form": [], "done": []}
    for order in orders:
        assignee = assignment_by_order.get(order.id)
        if (order.state or "").upper() in DONE_STATES or order.is_paid:
            bucket_id = "done"
        elif assignee:
            bucket_id = str(assignee.id)
        elif order.template_missing:
            bucket_id = "missing_form"
        else:
            bucket_id = "orders"
        buckets.setdefault(bucket_id, []).append(order)
    return buckets


def _reorder_duplicate_board(
    session: Session,
    *,
    platform_id: uuid.UUID,
    moved_order_id: uuid.UUID,
    target_column_id: str,
    before_order_id: uuid.UUID | None,
) -> None:
    """Insert a moved card before another card, or at the end when no target exists."""
    buckets = _board_order_buckets(session, platform_id=platform_id)
    moved_order: Order | None = None
    target_bucket: list[Order] | None = buckets.get(target_column_id)
    for bucket in buckets.values():
        for order in bucket:
            if order.id == moved_order_id:
                moved_order = order
            if before_order_id is not None and order.id == before_order_id:
                target_bucket = bucket

    if moved_order is None:
        return
    if before_order_id == moved_order_id:
        return

    for bucket in buckets.values():
        bucket[:] = [order for order in bucket if order.id != moved_order_id]

    if target_bucket is None:
        return

    if before_order_id is None:
        target_bucket.append(moved_order)
    else:
        target_index = next(
            (index for index, order in enumerate(target_bucket) if order.id == before_order_id),
            len(target_bucket),
        )
        target_bucket.insert(target_index, moved_order)

    for bucket in buckets.values():
        for position, order in enumerate(bucket):
            order.duplicate_board_position = position


def list_duplicate_board(
    session: Session, *, platform_id: uuid.UUID, viewer: User | None = None
) -> dict:
    platform = session.get(Platform, platform_id)
    if platform is None:
        raise DuplicateBoardError("Không tìm thấy platform đang chọn")
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

    col_orders: dict = {"id": "orders", "title": "Đơn hàng", "column_type": "orders", "cards": []}
    col_missing_form: dict = {"id": "missing_form", "title": "Thiếu form", "column_type": "missing_form", "cards": []}

    col_designers: list[dict] = [
        {"id": str(designer.id), "title": designer.full_name or designer.username, "column_type": "designer", "cards": []}
        for designer in designers
    ]
    column_by_designer = {str(designer.id): col for designer, col in zip(designers, col_designers)}

    col_done: dict = {"id": "done", "title": "Done", "column_type": "done", "cards": []}

    columns = [col_orders, col_missing_form, *col_designers, col_done]

    orders = (
        session.query(Order)
        .filter(Order.platform_id == platform_id, Order.work_domain == WORK_DOMAIN_DUPLICATE)
        .order_by(
            Order.duplicate_board_position.asc().nullslast(),
            Order.deadline_tacahu.nullslast(),
            Order.created_at.desc(),
        )
        .all()
    )
    if viewer and viewer.role == ROLE_DESIGNER_TRELLO:
        orders = [
            order
            for order in orders
            if not (
                (order.state or "").upper() in {"REVISION", "REVISION_REQUESTED", "FIX"}
                and not order.fix_approved_by_admin
            )
        ]
    active_assignments = (
        session.query(Assignment, User)
        .join(User, User.id == Assignment.designer_id)
        .filter(
            Assignment.order_id.in_([order.id for order in orders]),
            Assignment.status.in_(("approved", "draft")),
            User.role == ROLE_DESIGNER_TRELLO,
        )
        .order_by(Assignment.created_at.desc())
        .all()
        if orders
        else []
    )
    assignment_by_order: dict[uuid.UUID, User] = {}
    for assignment, designer in active_assignments:
        if assignment.order_id not in assignment_by_order:
            assignment_by_order[assignment.order_id] = designer

    latest_submission_by_order: dict[uuid.UUID, ResultVersion] = {}
    submission_rows = (
        session.query(ResultVersion, Assignment.order_id)
        .join(Assignment, Assignment.id == ResultVersion.assignment_id)
        .filter(Assignment.order_id.in_([order.id for order in orders]))
        .order_by(
            Assignment.order_id,
            ResultVersion.submitted_at.desc().nullslast(),
            ResultVersion.version_marker.desc(),
            ResultVersion.created_at.desc(),
        )
        .all()
        if orders
        else []
    )
    for result_version, order_id in submission_rows:
        latest_submission_by_order.setdefault(order_id, result_version)

    for order in orders:
        assignee = assignment_by_order.get(order.id)
        card_data = _card(
            order,
            assignee,
            hide_internal_notes=bool(viewer and viewer.role == ROLE_DESIGNER_TRELLO),
            latest_submission=latest_submission_by_order.get(order.id),
        )
        norm_st = (order.state or "").upper()

        if norm_st in DONE_STATES or order.is_paid:
            col_done["cards"].append(card_data)
        elif assignee and str(assignee.id) in column_by_designer:
            column_by_designer[str(assignee.id)]["cards"].append(card_data)
        elif order.template_missing:
            col_missing_form["cards"].append(card_data)
        else:
            col_orders["cards"].append(card_data)

    for column in columns:
        column["metrics"] = _column_metrics(column["cards"])

    return {
        "columns": columns,
        "cross_designer_drag_enabled": platform.duplicate_board_cross_designer_drag_enabled,
    }


def set_cross_designer_drag_enabled(
    session: Session,
    *,
    actor: User,
    platform_id: uuid.UUID,
    enabled: bool,
) -> bool:
    if actor.role != ROLE_ADMIN:
        raise DuplicateBoardError("Chỉ admin được thay đổi quyền kéo thẻ")
    platform = session.get(Platform, platform_id)
    if platform is None:
        raise DuplicateBoardError("Không tìm thấy platform đang chọn")
    platform.duplicate_board_cross_designer_drag_enabled = enabled
    session.commit()
    return platform.duplicate_board_cross_designer_drag_enabled

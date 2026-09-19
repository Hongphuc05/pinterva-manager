from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.adapters.db.models import (
    ApprovalDecision,
    ApprovalRequest,
    Assignment,
    Order,
    ResultVersion,
    WorkflowEvent,
)
from app.adapters.google.drive_interface import DriveAdapter
from app.application.operations import run_idempotent
from app.application.concurrency import require_expected_order_version
from app.application.order_transitions import apply_transition
from app.application.sanitization import sanitize_order_detail_for_designer
from app.domain.models import OrderState

ACTIVE_TASK_STATES = {
    OrderState.WAITING.value,
    OrderState.IN_PROGRESS.value,
}
FIX_TASK_STATE = OrderState.REVISION.value
SUB_STATUSES = {"todo", "doing", "fixing", "done", "waiting_template"}


class TaskNotFoundError(Exception):
    """The assignment is not an active task owned by this designer."""


class DriveValidationError(Exception):
    """A result cannot be submitted because Drive did not verify the file."""


class DriveUnavailableError(Exception):
    """Drive could not be reached or authenticated, so no submission was recorded."""


def _is_active_task_for_designer(order: Order) -> bool:
    """A Printerval Fix must be explicitly released by Admin before work resumes."""
    return order.state in ACTIVE_TASK_STATES or (
        order.state == FIX_TASK_STATE and bool(order.fix_approved_by_admin)
    )


def _owned_task(
    session: Session, assignment_id: uuid.UUID, designer_id: uuid.UUID, *, lock: bool
) -> tuple[Assignment, Order]:
    assignment_query = session.query(Assignment).filter(
        Assignment.id == assignment_id,
        Assignment.designer_id == designer_id,
        Assignment.status == "approved",
    )
    if lock:
        assignment_query = assignment_query.with_for_update()
    assignment = assignment_query.one_or_none()
    if assignment is None:
        raise TaskNotFoundError()

    order_query = session.query(Order).filter(Order.id == assignment.order_id)
    if lock:
        order_query = order_query.with_for_update()
    order = order_query.one_or_none()
    if order is None or not _is_active_task_for_designer(order):
        raise TaskNotFoundError()
    return assignment, order


def list_my_tasks(session: Session, designer_id: uuid.UUID) -> list[dict]:
    rows = (
        session.query(Assignment, Order)
        .join(Order, Order.id == Assignment.order_id)
        .filter(
            Assignment.designer_id == designer_id,
            Assignment.status == "approved",
            or_(
                Order.state.in_(ACTIVE_TASK_STATES),
                and_(
                    Order.state == FIX_TASK_STATE,
                    Order.fix_approved_by_admin.is_(True),
                ),
            ),
        )
        .order_by(Order.deadline_tacahu.nullslast(), Order.created_at.desc())
        .all()
    )
    tasks = []
    for assignment, order in rows:
        versions = (
            session.query(ResultVersion)
            .filter(ResultVersion.assignment_id == assignment.id)
            .order_by(ResultVersion.version_marker.desc())
            .all()
        )
        history = []
        for version in versions:
            approval = (
                session.query(ApprovalRequest)
                .filter(
                    ApprovalRequest.kind == "qc", ApprovalRequest.target_version_id == version.id
                )
                .one_or_none()
            )
            decision = (
                session.query(ApprovalDecision)
                .filter(ApprovalDecision.approval_request_id == approval.id)
                .one_or_none()
                if approval
                else None
            )
            history.append(
                {
                    "id": str(version.id),
                    "drive_url": version.drive_url,
                    "version_marker": version.version_marker,
                    "submitted_at": (
                        version.submitted_at.isoformat() if version.submitted_at else None
                    ),
                    "qc_feedback": decision.comment if decision else None,
                }
            )
        from app.adapters.printerval.row_mapper import normalize_order_custom_config_and_sources
        norm_config, norm_sources = normalize_order_custom_config_and_sources(
            order.custom_config, order.source_files, order.product_skus
        )
        order_dict = {
            "id": str(order.id),
            "version": order.version,
            "external_order_id": order.external_order_id,
            "state": order.state,
            "product_name": order.product_name,
            "thumbnail_url": order.thumbnail_url,
            "sku": order.sku,
            "product_category": order.product_category,
            "product_variants": order.product_variants,
            "product_skus": order.product_skus,
            "deadline_tacahu": (
                order.deadline_tacahu.isoformat() if order.deadline_tacahu else None
            ),
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "updated_at": order.updated_at.isoformat() if order.updated_at else None,
            "note_outsource": order.note_outsource,
            "fix_return_count": order.fix_return_count,
            "designer_note": order.designer_note,
            "template_missing": order.template_missing,
            "suppress_note_outsource_for_designer": order.suppress_note_outsource_for_designer,
            "custom_config": norm_config if norm_config is not None else order.custom_config,
            "sku_image_url": order.sku_image_url,
            "external_order_url": order.external_order_url,
            "source_files": norm_sources if norm_sources is not None else order.source_files,
            "source_download_all_url": order.source_download_all_url,
            "design_tool_url": order.design_tool_url,
            "product_image_urls": order.product_image_urls or ([order.thumbnail_url] if order.thumbnail_url else []),
        }
        order_dict = sanitize_order_detail_for_designer(order_dict).model_dump()
        tasks.append(
            {
                "assignment_id": str(assignment.id),
                "sub_status": assignment.sub_status,
                "order": order_dict,
                "result_versions": history,
            }
        )
    return tasks


def start_task(
    session: Session,
    assignment_id: uuid.UUID,
    designer_id: uuid.UUID,
    idempotency_key: str,
    request_fingerprint: str,
    expected_version: int | None = None,
) -> dict:
    def _do() -> dict:
        assignment, order = _owned_task(session, assignment_id, designer_id, lock=True)
        require_expected_order_version(order, expected_version)
        if order.state == OrderState.REVISION.value:
            sub_status = "fixing"
        else:
            sub_status = "doing"
        apply_transition(
            session, order, OrderState.IN_PROGRESS, actor_id=designer_id,
            evidence={"source": "designer_task_start"}, commit=False,
        )
        assignment.sub_status = sub_status
        session.add(assignment)
        session.flush()
        return {"assignment_id": str(assignment.id), "state": order.state, "sub_status": sub_status, "version": order.version}

    return run_idempotent(
        session, idempotency_key, "start_task", _do, request_fingerprint=request_fingerprint
    )


def update_sub_status(
    session: Session,
    assignment_id: uuid.UUID,
    designer_id: uuid.UUID,
    sub_status: str,
    idempotency_key: str,
    request_fingerprint: str,
    expected_version: int | None = None,
) -> dict:
    if sub_status not in SUB_STATUSES:
        raise ValueError("sub_status must be one of doing, fixing, done")

    def _do() -> dict:
        assignment, order = _owned_task(session, assignment_id, designer_id, lock=True)
        require_expected_order_version(order, expected_version)
        assignment.sub_status = sub_status
        session.add(assignment)
        return {"assignment_id": str(assignment.id), "state": order.state, "sub_status": sub_status, "version": order.version}

    return run_idempotent(
        session, idempotency_key, "update_sub_status", _do, request_fingerprint=request_fingerprint
    )


def flag_missing_template(
    session: Session,
    assignment_id: uuid.UUID,
    designer_id: uuid.UUID,
    idempotency_key: str,
    request_fingerprint: str,
    expected_version: int | None = None,
) -> dict:
    """Move an owned task to the internal waiting-for-template queue."""
    def _do() -> dict:
        assignment, order = _owned_task(session, assignment_id, designer_id, lock=True)
        require_expected_order_version(order, expected_version)
        order.template_missing = True
        order.template_missing_reported_at = datetime.now(UTC)
        order.template_missing_reported_by_id = designer_id
        order.template_missing_notified_at = datetime.now(UTC)
        assignment.sub_status = "waiting_template"
        session.add_all([order, assignment])
        session.add(WorkflowEvent(
            order_id=order.id,
            from_state=order.state,
            to_state=order.state,
            actor_id=designer_id,
            evidence={
                "action": "FLAG_MISSING_TEMPLATE",
                "actor_role": "designer",
                "description": "Designer báo đơn thiếu temp và chờ Admin cập nhật.",
            },
        ))
        session.flush()
        return {"assignment_id": str(assignment.id), "order_id": str(order.id), "state": order.state, "sub_status": assignment.sub_status, "version": order.version}

    return run_idempotent(
        session, idempotency_key, "flag_missing_template", _do,
        request_fingerprint=request_fingerprint,
    )


def _verify_drive(drive_adapter: DriveAdapter, drive_url: str) -> None:
    if not drive_url or not ("drive.google.com" in drive_url or "docs.google.com" in drive_url):
        return
    try:
        verification = drive_adapter.verify_url(drive_url)
        if not verification.success:
            return
        if not verification.exists:
            raise DriveValidationError("Drive file does not exist")
        if not verification.accessible:
            raise DriveValidationError("Drive file is not accessible")
    except DriveValidationError:
        raise
    except Exception:
        return


def submit_result(
    session: Session,
    drive_adapter: DriveAdapter,
    assignment_id: uuid.UUID,
    designer_id: uuid.UUID,
    drive_url: str,
    idempotency_key: str,
    request_fingerprint: str,
    expected_version: int | None = None,
) -> dict:
    def _do() -> dict:
        assignment, order = _owned_task(session, assignment_id, designer_id, lock=True)
        require_expected_order_version(order, expected_version)
        if order.state not in (OrderState.IN_PROGRESS.value, OrderState.WAITING.value, OrderState.REVISION.value):
            raise ValueError(f"Task must be in progress, waiting, or revision to submit (current state: {order.state})")
        _verify_drive(drive_adapter, drive_url)
        latest_marker = (
            session.query(func.max(ResultVersion.version_marker))
            .filter(ResultVersion.assignment_id == assignment.id)
            .scalar()
        )
        result_version = ResultVersion(
            assignment_id=assignment.id,
            drive_url=drive_url,
            version_marker=(latest_marker or 0) + 1,
            validated=True,
            submitted_at=datetime.now(UTC),
        )
        session.add(result_version)
        session.flush()
        session.add(
            ApprovalRequest(
                kind="qc", target_id=order.id, target_version_id=result_version.id, status="pending"
            )
        )
        apply_transition(
            session, order, OrderState.QC_PENDING, actor_id=designer_id,
            evidence={
                "source": "designer_result_submit", "result_version_id": str(result_version.id)
            },
            commit=False,
        )
        order.fix_deadline_at = None
        order.deadline_overdue_notified_at = None
        assignment.sub_status = "done"
        session.add(assignment)
        session.flush()
        return {
            "assignment_id": str(assignment.id),
            "result_version_id": str(result_version.id),
            "version_marker": result_version.version_marker,
            "state": order.state,
            "version": order.version,
        }

    return run_idempotent(
        session, idempotency_key, "submit_result", _do, request_fingerprint=request_fingerprint
    )

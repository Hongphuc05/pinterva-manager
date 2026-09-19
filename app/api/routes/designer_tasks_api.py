from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.api.concurrency import OrderCommandPayload
from app.adapters.google.drive_adapter import GoogleDriveAdapter
from app.adapters.google.drive_interface import DriveAdapter
from app.api.deps import get_db, require_any_role
from app.application.designer_tasks import (
    DriveUnavailableError,
    DriveValidationError,
    TaskNotFoundError,
    flag_missing_template,
    heartbeat_task,
    list_my_tasks,
    start_task,
    submit_result,
    update_sub_status,
)
from app.application.processing_leases import ProcessingLeaseConflictError
from app.application.operations import IdempotencyKeyReusedError, OperationInProgressError
from app.domain.access import ROLE_DESIGNER, ROLE_DESIGNER_TRELLO
from app.domain.models import OrderState

router = APIRouter()


def get_drive_adapter() -> DriveAdapter:
    try:
        return GoogleDriveAdapter()
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Không thể khởi tạo xác minh Google Drive; chưa ghi nhận kết quả.",
        ) from exc


class ResultVersionOut(BaseModel):
    id: str
    drive_url: str
    version_marker: int
    submitted_at: str | None
    qc_feedback: str | None


class TaskOrderOut(BaseModel):
    id: str
    version: int
    external_order_id: str
    state: str
    product_name: str | None
    thumbnail_url: str | None
    sku: str | None
    product_category: str | None = None
    product_variants: list[dict] | None = None
    product_skus: list[dict] | None = None
    deadline_tacahu: str | None
    updated_at: str | None = None
    note_outsource: str | None = None
    designer_note: str = ""
    template_missing: bool = False
    custom_config: dict | None
    sku_image_url: str | None = None
    external_order_url: str | None = None
    source_files: list[dict] | None = None
    source_download_all_url: str | None = None
    design_tool_url: str | None = None
    product_image_urls: list[str] | None = None


class DesignerTaskOut(BaseModel):
    assignment_id: str
    sub_status: str | None
    order: Any
    result_versions: list[ResultVersionOut]


class TasksResponse(BaseModel):
    tasks: list[DesignerTaskOut]


class RequestIdPayload(OrderCommandPayload):
    request_id: str = Field(min_length=1, max_length=128)


class SubStatusPayload(RequestIdPayload):
    sub_status: str


class SubmitResultPayload(RequestIdPayload):
    drive_url: str = Field(default="")


class TaskMutationResponse(BaseModel):
    assignment_id: str
    state: str
    sub_status: str | None = None
    result_version_id: str | None = None
    version_marker: int | None = None
    version: int | None = None
    processing_lock_expires_at: str | None = None


def _raise_task_error(exc: Exception) -> None:
    if isinstance(exc, ProcessingLeaseConflictError):
        raise HTTPException(
            status.HTTP_423_LOCKED,
            detail={
                "code": "PROCESSING_LEASE_CONFLICT",
                "message": "Đơn đang được xử lý trong một phiên khác hoặc lease đã hết hạn. Hãy tải lại trước khi tiếp tục.",
                "order_id": str(exc.order_id),
                "expires_at": exc.expires_at.isoformat() if exc.expires_at else None,
            },
        ) from exc
    if isinstance(exc, TaskNotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found") from exc
    if isinstance(exc, DriveValidationError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if isinstance(exc, DriveUnavailableError):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Không thể xác minh Google Drive lúc này; chưa ghi nhận kết quả.",
        ) from exc
    if isinstance(exc, (OperationInProgressError, IdempotencyKeyReusedError)):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Yêu cầu đang được xử lý hoặc đã thay đổi."
        ) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    raise exc


@router.get("/my-tasks", response_model=TasksResponse)
def api_my_tasks(
    user: User = Depends(require_any_role(ROLE_DESIGNER, ROLE_DESIGNER_TRELLO)), db: Session = Depends(get_db)
):
    return TasksResponse(tasks=list_my_tasks(db, user.id))


@router.post("/assignments/{assignment_id}/start", response_model=TaskMutationResponse)
def api_start_task(
    assignment_id: uuid.UUID,
    payload: RequestIdPayload,
    user: User = Depends(require_any_role(ROLE_DESIGNER, ROLE_DESIGNER_TRELLO)),
    db: Session = Depends(get_db),
):
    try:
        result = start_task(
            db, assignment_id, user.id, f"start:{user.id}:{payload.request_id}",
            request_fingerprint=str(assignment_id),
            expected_version=payload.expected_version,
        )
    except Exception as exc:  # routed through stable HTTP errors above
        _raise_task_error(exc)
    return TaskMutationResponse(**result)


@router.post("/assignments/{assignment_id}/processing-lease/heartbeat", response_model=TaskMutationResponse)
def api_heartbeat_task_processing_lease(
    assignment_id: uuid.UUID,
    payload: OrderCommandPayload,
    user: User = Depends(require_any_role(ROLE_DESIGNER, ROLE_DESIGNER_TRELLO)),
    db: Session = Depends(get_db),
):
    try:
        result = heartbeat_task(
            db, assignment_id, user.id, expected_version=payload.expected_version,
        )
    except Exception as exc:
        _raise_task_error(exc)
    return TaskMutationResponse(**result)


@router.patch("/assignments/{assignment_id}/sub-status", response_model=TaskMutationResponse)
def api_update_sub_status(
    assignment_id: uuid.UUID,
    payload: SubStatusPayload,
    user: User = Depends(require_any_role(ROLE_DESIGNER, ROLE_DESIGNER_TRELLO)),
    db: Session = Depends(get_db),
):
    try:
        result = update_sub_status(
            db, assignment_id, user.id, payload.sub_status,
            f"sub-status:{user.id}:{payload.request_id}",
            request_fingerprint=f"{assignment_id}:{payload.sub_status}",
            expected_version=payload.expected_version,
        )
    except Exception as exc:  # routed through stable HTTP errors above
        _raise_task_error(exc)
    return TaskMutationResponse(**result)


@router.post("/assignments/{assignment_id}/flag-missing-template", response_model=TaskMutationResponse)
def api_flag_missing_template(
    assignment_id: uuid.UUID,
    payload: RequestIdPayload,
    user: User = Depends(require_any_role(ROLE_DESIGNER, ROLE_DESIGNER_TRELLO)),
    db: Session = Depends(get_db),
):
    try:
        result = flag_missing_template(
            db, assignment_id, user.id,
            f"flag-missing-template:{user.id}:{payload.request_id}",
            request_fingerprint=str(assignment_id),
            expected_version=payload.expected_version,
        )
    except Exception as exc:
        _raise_task_error(exc)
    try:
        from app.workers.telegram_tasks import async_notify_admin_missing_template, safe_dispatch_telegram_task
        safe_dispatch_telegram_task(async_notify_admin_missing_template, result["order_id"], str(user.id))
    except Exception:
        pass
    return TaskMutationResponse(**result)


@router.post("/assignments/{assignment_id}/results", response_model=TaskMutationResponse)
def api_submit_result(
    assignment_id: uuid.UUID,
    payload: SubmitResultPayload,
    user: User = Depends(require_any_role(ROLE_DESIGNER, ROLE_DESIGNER_TRELLO)),
    db: Session = Depends(get_db),
    drive_adapter: DriveAdapter = Depends(get_drive_adapter),
):
    try:
        result = submit_result(
            db, drive_adapter, assignment_id, user.id, str(payload.drive_url),
            f"submit-result:{user.id}:{payload.request_id}",
            request_fingerprint=f"{assignment_id}:{payload.drive_url}",
            expected_version=payload.expected_version,
        )
    except Exception as exc:  # routed through stable HTTP errors above
        _raise_task_error(exc)
    if result.get("sync_printerval_review"):
        try:
            from app.workers.assignment_sync_tasks import sync_order_review_to_printerval_task

            sync_order_review_to_printerval_task.delay(
                result["order_id"],
                None,
                "Review",
                expected_state=OrderState.QC_PENDING.value,
                expected_fix_approved=True,
            )
        except Exception:
            # The internal review transition is authoritative and committed; a
            # failed enqueue is observable/retriable independently.
            pass
    return TaskMutationResponse(**result)

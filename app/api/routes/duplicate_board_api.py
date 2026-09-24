from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.api.concurrency import OrderCommandPayload
from app.api.deps import get_current_platform_id, get_db, require_any_role, require_role
from app.application.assignment_commands import AssignmentCommandError
from app.application.duplicate_board import (
    DuplicateBoardError,
    list_duplicate_board,
    move_duplicate_order,
    remove_duplicate_from_backlog,
    set_cross_designer_drag_enabled,
    set_orders_duplicate_status,
    set_orders_work_domain,
)
from app.application.support_return import return_orders_to_unchecked
from app.application.support_take import take_duplicate_orders
from app.domain.access import ROLE_ADMIN, ROLE_DESIGNER_TRELLO, ROLE_SUPPORT

router = APIRouter()


class DuplicateCardOut(BaseModel):
    id: str
    version: int
    external_order_id: str
    product_name: str | None
    thumbnail_url: str | None
    deadline_tacahu: datetime | None
    order_created_at_ext: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    status_changed_at: datetime | None = None
    paid_at: datetime | None = None
    is_paid: bool = False
    template_missing: bool = False
    duplicate_check_status: str = "duplicate"
    state: str
    note_outsource: str
    previous_note_outsource: str | None
    fix_approved_by_admin: bool
    assignee_id: str | None
    assignee_name: str | None
    duplicate_board_position: int | None = None
    submission_url: str | None = None
    submission_version: int | None = None


class DuplicateColumnOut(BaseModel):
    id: str
    title: str
    column_type: str = "designer"
    metrics: dict[str, int]
    cards: list[DuplicateCardOut]


class DuplicateBoardResponse(BaseModel):
    columns: list[DuplicateColumnOut]
    cross_designer_drag_enabled: bool


class MoveDuplicateCardRequest(OrderCommandPayload):
    order_id: uuid.UUID
    target_column_id: str | None = None
    target_designer_id: uuid.UUID | None = None
    before_order_id: uuid.UUID | None = None
    reorder: bool = False


class SetWorkDomainRequest(BaseModel):
    order_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    work_domain: str
    expected_versions: dict[uuid.UUID, int] | None = None


class SetDuplicateCheckStatusRequest(BaseModel):
    order_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    status: str
    expected_versions: dict[uuid.UUID, int] | None = None


class DuplicateBoardSettingsRequest(BaseModel):
    cross_designer_drag_enabled: bool


@router.post("/duplicate-board/remove-from-duplicate")
def api_remove_from_duplicate_backlog(
    payload: MoveDuplicateCardRequest,
    user: User = Depends(require_any_role(ROLE_ADMIN, ROLE_DESIGNER_TRELLO)),
    platform_id: uuid.UUID = Depends(get_current_platform_id), db: Session = Depends(get_db),
):
    try:
        remove_duplicate_from_backlog(db, actor=user, platform_id=platform_id, order_id=payload.order_id, expected_version=payload.expected_version)
        return {"ok": True}
    except DuplicateBoardError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/duplicate-board", response_model=DuplicateBoardResponse)
def api_duplicate_board(
    user: User = Depends(require_any_role(ROLE_ADMIN, ROLE_DESIGNER_TRELLO)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    try:
        return DuplicateBoardResponse(**list_duplicate_board(db, platform_id=platform_id, viewer=user))
    except DuplicateBoardError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/duplicate-board/move", response_model=DuplicateCardOut)
def api_move_duplicate_card(
    payload: MoveDuplicateCardRequest,
    user: User = Depends(require_any_role(ROLE_ADMIN, ROLE_DESIGNER_TRELLO)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    try:
        return DuplicateCardOut(
            **move_duplicate_order(
                db,
                actor=user,
                platform_id=platform_id,
                order_id=payload.order_id,
                expected_version=payload.expected_version,
                target_column_id=payload.target_column_id,
                target_designer_id=payload.target_designer_id,
                before_order_id=payload.before_order_id,
                reorder=payload.reorder,
            )
        )
    except DuplicateBoardError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/orders/duplicate-domain")
def api_set_orders_duplicate_domain(
    payload: SetWorkDomainRequest,
    user: User = Depends(require_any_role(ROLE_ADMIN, ROLE_SUPPORT)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    try:
        changed_count = set_orders_work_domain(
            db,
            actor=user,
            platform_id=platform_id,
            order_ids=payload.order_ids,
            work_domain=payload.work_domain,
            expected_versions=payload.expected_versions,
        )
    except DuplicateBoardError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"changed_count": changed_count, "work_domain": payload.work_domain}


class SupportTakeRequest(BaseModel):
    order_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


@router.post("/orders/support-take")
def api_support_take_duplicates(
    payload: SupportTakeRequest,
    user: User = Depends(require_any_role(ROLE_ADMIN, ROLE_SUPPORT)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    """Support's "Lấy": give duplicate orders to the in-house designer instead of the board."""
    try:
        taken = take_duplicate_orders(db, actor=user, platform_id=platform_id, order_ids=payload.order_ids)
    except AssignmentCommandError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"taken_count": taken}


@router.post("/orders/duplicate-check-status")
def api_set_orders_duplicate_check_status(
    payload: SetDuplicateCheckStatusRequest,
    user: User = Depends(require_any_role(ROLE_ADMIN, ROLE_SUPPORT)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    try:
        changed_count = set_orders_duplicate_status(
            db,
            actor=user,
            platform_id=platform_id,
            order_ids=payload.order_ids,
            duplicate_status=payload.status,
            expected_versions=payload.expected_versions,
            allow_support_unclassified_doing=True,
        )
    except DuplicateBoardError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"changed_count": changed_count, "status": payload.status}


class ReturnToUncheckedRequest(BaseModel):
    order_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    expected_versions: dict[uuid.UUID, int] | None = None


@router.post("/orders/return-to-unchecked")
def api_return_orders_to_unchecked(
    payload: ReturnToUncheckedRequest,
    user: User = Depends(require_any_role(ROLE_ADMIN, ROLE_SUPPORT)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    """Put classified orders without a designer back into Chưa kiểm tra (they can be checked again)."""
    try:
        changed = return_orders_to_unchecked(
            db,
            actor=user,
            platform_id=platform_id,
            order_ids=payload.order_ids,
            expected_versions=payload.expected_versions,
        )
    except DuplicateBoardError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"changed_count": changed}


@router.put("/duplicate-board/settings")
def api_set_duplicate_board_settings(
    payload: DuplicateBoardSettingsRequest,
    user: User = Depends(require_role(ROLE_ADMIN)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    try:
        enabled = set_cross_designer_drag_enabled(
            db,
            actor=user,
            platform_id=platform_id,
            enabled=payload.cross_designer_drag_enabled,
        )
    except DuplicateBoardError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"cross_designer_drag_enabled": enabled}

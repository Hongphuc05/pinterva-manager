from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.api.deps import get_current_platform_id, get_db, require_any_role, require_role
from app.application.duplicate_board import (
    DuplicateBoardError,
    list_duplicate_board,
    move_duplicate_order,
    set_cross_designer_drag_enabled,
    set_orders_duplicate_status,
    set_orders_work_domain,
)
from app.domain.access import ROLE_ADMIN, ROLE_DESIGNER_TRELLO, ROLE_SUPPORT

router = APIRouter()


class DuplicateCardOut(BaseModel):
    id: str
    external_order_id: str
    product_name: str | None
    thumbnail_url: str | None
    deadline_at_ext: datetime | None
    order_created_at_ext: datetime | None = None
    created_at: datetime | None = None
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


class DuplicateColumnOut(BaseModel):
    id: str
    title: str
    column_type: str = "designer"
    metrics: dict[str, int]
    cards: list[DuplicateCardOut]


class DuplicateBoardResponse(BaseModel):
    columns: list[DuplicateColumnOut]
    cross_designer_drag_enabled: bool


class MoveDuplicateCardRequest(BaseModel):
    order_id: uuid.UUID
    target_column_id: str | None = None
    target_designer_id: uuid.UUID | None = None
    before_order_id: uuid.UUID | None = None
    reorder: bool = False


class SetWorkDomainRequest(BaseModel):
    order_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    work_domain: str


class SetDuplicateCheckStatusRequest(BaseModel):
    order_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    status: str


class DuplicateBoardSettingsRequest(BaseModel):
    cross_designer_drag_enabled: bool


@router.get("/duplicate-board", response_model=DuplicateBoardResponse)
def api_duplicate_board(
    user: User = Depends(require_any_role(ROLE_ADMIN, ROLE_DESIGNER_TRELLO, ROLE_SUPPORT)),
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
        )
    except DuplicateBoardError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"changed_count": changed_count, "work_domain": payload.work_domain}


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
        )
    except DuplicateBoardError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"changed_count": changed_count, "status": payload.status}


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

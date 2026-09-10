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
    set_orders_work_domain,
)
from app.domain.access import ROLE_ADMIN, ROLE_DESIGNER_TRELLO

router = APIRouter()


class DuplicateCardOut(BaseModel):
    id: str
    external_order_id: str
    product_name: str | None
    thumbnail_url: str | None
    deadline_at_ext: datetime | None
    state: str
    assignee_id: str | None
    assignee_name: str | None


class DuplicateColumnOut(BaseModel):
    id: str
    title: str
    cards: list[DuplicateCardOut]


class DuplicateBoardResponse(BaseModel):
    columns: list[DuplicateColumnOut]


class MoveDuplicateCardRequest(BaseModel):
    order_id: uuid.UUID
    target_designer_id: uuid.UUID | None = None


class SetWorkDomainRequest(BaseModel):
    order_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    work_domain: str


@router.get("/duplicate-board", response_model=DuplicateBoardResponse)
def api_duplicate_board(
    user: User = Depends(require_any_role(ROLE_ADMIN, ROLE_DESIGNER_TRELLO)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    return DuplicateBoardResponse(columns=list_duplicate_board(db, platform_id=platform_id))


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
                target_designer_id=payload.target_designer_id,
            )
        )
    except DuplicateBoardError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/orders/duplicate-domain")
def api_set_orders_duplicate_domain(
    payload: SetWorkDomainRequest,
    user: User = Depends(require_role(ROLE_ADMIN)),
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

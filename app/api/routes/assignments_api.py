from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.api.deps import get_current_platform_id, get_db, require_role
from app.application.assignment_commands import AssignmentCommandError, queue_assignment_command

router = APIRouter(prefix="/assignments", tags=["assignments"])


class CreateAssignmentRequest(BaseModel):
    order_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    designer_id: uuid.UUID | None = None
    printerval_designer: str | None = None
    printerval_status: str = "Doing"


class CreateAssignmentResponse(BaseModel):
    request_ids: list[uuid.UUID]
    queued_count: int


@router.post("", response_model=CreateAssignmentResponse, status_code=status.HTTP_202_ACCEPTED)
def create_assignments(
    payload: CreateAssignmentRequest,
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    try:
        requests, queued_count = queue_assignment_command(
            db,
            platform_id=platform_id,
            actor=user,
            order_ids=payload.order_ids,
            designer_id=payload.designer_id,
            printerval_designer=payload.printerval_designer,
            printerval_status=payload.printerval_status,
        )
    except AssignmentCommandError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return CreateAssignmentResponse(
        request_ids=[request.id for request in requests],
        queued_count=queued_count,
    )

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.allocation.reference import ReferenceAllocationTool
from app.adapters.db.models import ApprovalRequest, Assignment, Order, User
from app.api.deps import get_current_user, get_db, require_role
from app.application.allocation import (
    _remaining_order_ids,
    create_assignment_draft,
    decide_assignment,
    open_allocation,
    request_quantity,
)
from app.domain.exceptions import CapacityExceededError

router = APIRouter()
_allocation_tool = ReferenceAllocationTool()


class OpenAllocationResponse(BaseModel):
    order_ids: list[str]


@router.post("/batches/{batch_id}/open-allocation", response_model=OpenAllocationResponse)
def api_open_allocation(
    batch_id: str, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)
):
    try:
        result = open_allocation(db, uuid.UUID(batch_id), f"open_allocation:{batch_id}")
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return OpenAllocationResponse(order_ids=result["order_ids"])


class OfferRequest(BaseModel):
    batch_id: str
    quantity: int


class GrantResponse(BaseModel):
    granted_order_ids: list[str]
    assignment_ids: list[str]


@router.post("/allocation/offer", response_model=GrantResponse)
def api_allocation_offer(
    payload: OfferRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role != "designer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Chỉ designer mới tự offer được")
    try:
        result = request_quantity(
            db, _allocation_tool, user.id, uuid.UUID(payload.batch_id), payload.quantity,
            f"offer:{payload.batch_id}:{user.id}:{uuid.uuid4()}",
        )
    except CapacityExceededError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return GrantResponse(**result)


class AssignRequest(BaseModel):
    order_id: str
    designer_id: str


class AssignResponse(BaseModel):
    assignment_id: str


@router.post("/allocation/assign", response_model=AssignResponse)
def api_allocation_assign(
    payload: AssignRequest,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    try:
        result = create_assignment_draft(
            db, payload.order_id, uuid.UUID(payload.designer_id), user.id,
            f"assign:{payload.order_id}:{uuid.uuid4()}",
        )
    except (ValueError, CapacityExceededError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return AssignResponse(**result)


class BoardOrderOut(BaseModel):
    id: uuid.UUID
    external_order_id: str
    thumbnail_url: str | None
    sku: str | None
    deadline_at_ext: str | None


class PendingApprovalOut(BaseModel):
    approval_id: uuid.UUID
    order: BoardOrderOut


class BoardDesignerOut(BaseModel):
    id: uuid.UUID
    full_name: str
    capacity: int | None
    held: int
    pending_approvals: list[PendingApprovalOut]


class BoardResponse(BaseModel):
    unassigned: list[BoardOrderOut]
    designers: list[BoardDesignerOut]


@router.get("/allocation/board", response_model=BoardResponse)
def api_allocation_board(
    batch_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    unassigned = [
        BoardOrderOut(
            id=o.id, external_order_id=o.external_order_id, thumbnail_url=o.thumbnail_url,
            sku=o.sku, deadline_at_ext=str(o.deadline_at_ext) if o.deadline_at_ext else None,
        )
        for o in _remaining_order_ids(db, uuid.UUID(batch_id))
    ]

    designers_out = []
    for designer in db.query(User).filter_by(role="designer", active=True).all():
        held = (
            db.query(Assignment)
            .filter(
                Assignment.designer_id == designer.id,
                Assignment.status.in_(["draft", "approved"]),
            )
            .count()
        )
        pending = []
        if user.role == "admin":
            draft_assignments = (
                db.query(Assignment)
                .filter_by(designer_id=designer.id, status="draft")
                .all()
            )
            for assignment in draft_assignments:
                approval = (
                    db.query(ApprovalRequest)
                    .filter_by(target_id=assignment.id, kind="assignment", status="pending")
                    .one_or_none()
                )
                if approval is None:
                    continue
                order = db.get(Order, assignment.order_id)
                pending.append(
                    PendingApprovalOut(
                        approval_id=approval.id,
                        order=BoardOrderOut(
                            id=order.id, external_order_id=order.external_order_id,
                            thumbnail_url=order.thumbnail_url, sku=order.sku,
                            deadline_at_ext=(
                                str(order.deadline_at_ext) if order.deadline_at_ext else None
                            ),
                        ),
                    )
                )
        designers_out.append(
            BoardDesignerOut(
                id=designer.id, full_name=designer.full_name, capacity=designer.capacity,
                held=held, pending_approvals=pending,
            )
        )

    return BoardResponse(unassigned=unassigned, designers=designers_out)


class DecideRequest(BaseModel):
    decision: str
    reason: str | None = None


class DecideResponse(BaseModel):
    decision: str
    order_id: str
    actor_id: str
    decided_by_me: bool
    replacement_assignment_ids: list[str] = []


@router.post("/approvals/{approval_id}/decide", response_model=DecideResponse)
def api_decide_assignment(
    approval_id: str, payload: DecideRequest, user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    try:
        result = decide_assignment(
            db, _allocation_tool, uuid.UUID(approval_id), payload.decision, user.id,
            f"decide_assignment:{approval_id}", reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return DecideResponse(
        decision=result["decision"],
        order_id=result["order_id"],
        actor_id=result["actor_id"],
        decided_by_me=result["actor_id"] == str(user.id),
        replacement_assignment_ids=result.get("replacement_assignment_ids", []),
    )

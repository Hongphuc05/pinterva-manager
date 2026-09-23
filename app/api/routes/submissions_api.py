from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.adapters.db.models import Assignment, Order, ResultVersion, User, WorkflowEvent
from app.api.deps import (
    get_current_platform_id,
    get_db,
    require_any_role,
    require_role,
)
from app.domain.access import ROLE_DESIGNER, ROLE_DESIGNER_TRELLO

router = APIRouter()


class SubmittedVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    assignment_id: uuid.UUID
    version_marker: int
    drive_url: str
    submitted_at: datetime | None = None
    created_at: datetime


class DesignerSubmissionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    order_id: uuid.UUID
    external_order_id: str
    product_name: str | None = None
    thumbnail_url: str | None = None
    sku: str | None = None
    designer_id: uuid.UUID | None = None
    designer_name: str | None = None
    designer_username: str | None = None
    first_submitted_at: datetime | None = None
    latest_submitted_at: datetime | None = None
    first_drive_url: str | None = None
    latest_drive_url: str | None = None
    versions: list[SubmittedVersionOut] = []
    current_note_outsource: str | None = None
    order_state: str
    printerval_status: str | None = None
    created_at: datetime


class DesignerSubmissionsResponse(BaseModel):
    items: list[DesignerSubmissionItem]
    total_items: int
    page: int
    page_size: int
    total_pages: int
    total_versions_count: int
    total_first_versions_count: int


class SubmissionDesignerOption(BaseModel):
    """A platform-scoped Designer option for the submissions filter."""

    id: str
    username: str
    full_name: str
    role: str


class OverrideSubmissionLinkRequest(BaseModel):
    version_id: uuid.UUID | None = None
    drive_url: str
    reason: str | None = None


@router.get(
    "/orders/designer-submissions/designers",
    response_model=list[SubmissionDesignerOption],
)
def list_submission_designers(
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    user: User = Depends(require_any_role("admin", "support")),
    db: Session = Depends(get_db),
):
    """Return Designers that have assignments in the active platform.

    The generic ``/users`` endpoint is intentionally admin-only because it is
    part of account management.  The submissions page needs a much narrower,
    platform-scoped read model so Support can use its Designer filter without
    gaining access to the user-management endpoint.
    """
    designers = (
        db.query(User)
        .join(Assignment, Assignment.designer_id == User.id)
        .join(Order, Order.id == Assignment.order_id)
        .filter(
            Order.platform_id == platform_id,
            Assignment.status != "cancelled",
            User.role.in_((ROLE_DESIGNER, ROLE_DESIGNER_TRELLO)),
            User.active.is_(True),
        )
        .distinct()
        .order_by(User.full_name.asc(), User.username.asc())
        .all()
    )
    return [
        SubmissionDesignerOption(
            id=str(designer.id),
            username=designer.username,
            full_name=designer.full_name,
            role=designer.role,
        )
        for designer in designers
    ]


@router.get("/orders/designer-submissions", response_model=DesignerSubmissionsResponse)
def list_designer_submissions(
    search: str | None = Query(None, description="Search by order code, product name, or drive link"),
    designer_id: uuid.UUID | None = Query(None, description="Filter by designer ID"),
    date_from: datetime | None = Query(None, description="Filter submissions from date"),
    date_to: datetime | None = Query(None, description="Filter submissions to date"),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    platform_id: uuid.UUID | None = Depends(get_current_platform_id),
    user: User = Depends(require_any_role("admin", "support")),
    db: Session = Depends(get_db),
):
    """Retrieves all designer submitted links (ResultVersions) grouped by order/assignment for Admin checking."""
    # Query all assignments that have result versions or match filters
    query = (
        db.query(Order, Assignment, User)
        .join(Assignment, Assignment.order_id == Order.id)
        .outerjoin(User, User.id == Assignment.designer_id)
        .filter(Assignment.status != "cancelled")
    )

    if platform_id:
        query = query.filter(Order.platform_id == platform_id)

    if designer_id:
        query = query.filter(Assignment.designer_id == designer_id)

    # We want orders that have at least one ResultVersion or matching search
    if search and search.strip():
        search_term = f"%{search.strip()}%"
        # Check if search matches order code, product name, or a result version drive_url
        matching_rv_order_ids = (
            db.query(Assignment.order_id)
            .join(ResultVersion, ResultVersion.assignment_id == Assignment.id)
            .filter(ResultVersion.drive_url.ilike(search_term))
        )
        query = query.filter(
            or_(
                Order.external_order_id.ilike(search_term),
                Order.product_name.ilike(search_term),
                Order.sku.ilike(search_term),
                Order.id.in_(matching_rv_order_ids),
            )
        )

    # Filter to orders that actually have ResultVersion entries OR drive links
    rv_assignment_ids_subquery = db.query(ResultVersion.assignment_id).distinct()
    query = query.filter(Assignment.id.in_(rv_assignment_ids_subquery))

    if date_from or date_to:
        rv_date_filtered = db.query(ResultVersion.assignment_id)
        if date_from:
            rv_date_filtered = rv_date_filtered.filter(
                or_(ResultVersion.submitted_at >= date_from, ResultVersion.created_at >= date_from)
            )
        if date_to:
            rv_date_filtered = rv_date_filtered.filter(
                or_(ResultVersion.submitted_at <= date_to, ResultVersion.created_at <= date_to)
            )
        query = query.filter(Assignment.id.in_(rv_date_filtered))

    # Calculate overall counts
    all_matching_rows = query.order_by(Order.created_at.desc()).all()
    total_items = len(all_matching_rows)
    total_pages = max(1, math.ceil(total_items / page_size))

    # Paginate
    offset = (page - 1) * page_size
    paginated_rows = all_matching_rows[offset : offset + page_size]

    # Gather all ResultVersions for the paginated assignments
    asgn_ids = [a.id for _, a, _ in paginated_rows]
    rv_by_asgn: dict[uuid.UUID, list[ResultVersion]] = {}
    if asgn_ids:
        all_rvs = (
            db.query(ResultVersion)
            .filter(ResultVersion.assignment_id.in_(asgn_ids))
            .order_by(ResultVersion.version_marker.asc(), ResultVersion.created_at.asc())
            .all()
        )
        for rv in all_rvs:
            rv_by_asgn.setdefault(rv.assignment_id, []).append(rv)

    # Calculate total counts across entire DB for summary header
    total_versions_count = db.query(func.count(ResultVersion.id)).scalar() or 0
    total_first_versions_count = (
        db.query(func.count(ResultVersion.id))
        .filter(ResultVersion.version_marker == 1)
        .scalar()
        or 0
    )

    items: list[DesignerSubmissionItem] = []
    for order_obj, asgn_obj, des_user in paginated_rows:
        versions = rv_by_asgn.get(asgn_obj.id, [])
        v_outs = [SubmittedVersionOut.model_validate(v) for v in versions]

        first_url = versions[0].drive_url if versions else None
        first_time = versions[0].submitted_at or versions[0].created_at if versions else None

        latest_url = versions[-1].drive_url if versions else None
        latest_time = versions[-1].submitted_at or versions[-1].created_at if versions else None

        des_name = None
        des_username = None
        if des_user:
            des_name = des_user.full_name or des_user.username
            des_username = des_user.username
        elif order_obj.printerval_designer:
            des_name = order_obj.printerval_designer

        items.append(
            DesignerSubmissionItem(
                order_id=order_obj.id,
                external_order_id=order_obj.external_order_id,
                product_name=order_obj.product_name,
                thumbnail_url=order_obj.thumbnail_url,
                sku=order_obj.sku,
                designer_id=asgn_obj.designer_id,
                designer_name=des_name,
                designer_username=des_username,
                first_submitted_at=first_time,
                latest_submitted_at=latest_time,
                first_drive_url=first_url,
                latest_drive_url=latest_url,
                versions=v_outs,
                current_note_outsource=order_obj.note_outsource,
                order_state=order_obj.state,
                printerval_status=order_obj.printerval_status,
                created_at=order_obj.created_at,
            )
        )

    return DesignerSubmissionsResponse(
        items=items,
        total_items=total_items,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        total_versions_count=total_versions_count,
        total_first_versions_count=total_first_versions_count,
    )


@router.post("/orders/{order_id}/override-submission-link")
def override_submission_link(
    order_id: uuid.UUID,
    payload: OverrideSubmissionLinkRequest,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Allows Admin to override/replace a submitted drive link in ResultVersion (Source of Truth)."""
    new_url = payload.drive_url.strip()
    if not new_url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Drive URL cannot be empty")

    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    assignment = (
        db.query(Assignment)
        .filter(Assignment.order_id == order.id, Assignment.status != "cancelled")
        .first()
    )
    if not assignment:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Order has no active assignment")

    target_version: ResultVersion | None = None
    if payload.version_id:
        target_version = db.get(ResultVersion, payload.version_id)
        if not target_version or target_version.assignment_id != assignment.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Result version not found for this assignment")
    else:
        # Get the latest or create version 1
        target_version = (
            db.query(ResultVersion)
            .filter(ResultVersion.assignment_id == assignment.id)
            .order_by(ResultVersion.version_marker.desc())
            .first()
        )

    old_url = target_version.drive_url if target_version else None

    if target_version:
        target_version.drive_url = new_url
        target_version.submitted_at = datetime.now(UTC)
        target_version.validated = True
    else:
        target_version = ResultVersion(
            assignment_id=assignment.id,
            drive_url=new_url,
            version_marker=1,
            submitted_at=datetime.now(UTC),
            validated=True,
        )
        db.add(target_version)

    # Record audit workflow event
    evt = WorkflowEvent(
        order_id=order.id,
        actor_id=user.id,
        from_state=order.state,
        to_state=order.state,
        evidence={
            "action": "ADMIN_OVERRIDE_SUBMISSION_LINK",
            "actor_id": str(user.id),
            "actor_name": user.full_name or user.username,
            "version_id": str(target_version.id) if target_version else None,
            "old_drive_url": old_url,
            "new_drive_url": new_url,
            "reason": payload.reason,
        },
    )
    db.add(evt)
    db.commit()
    db.refresh(target_version)

    return {
        "ok": True,
        "message": f"Đã cập nhật link nộp bài cho đơn {order.external_order_id} thành công",
        "version": SubmittedVersionOut.model_validate(target_version),
    }

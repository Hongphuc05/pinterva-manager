from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.adapters.db.models import (
    Assignment,
    FinanceNote,
    Order,
    Platform,
    ResultVersion,
    User,
    WorkflowEvent,
)
from app.api.deps import DEFAULT_PLATFORM_ID, get_current_platform_id, get_current_user, get_db
from app.application.sanitization import encode_proxy_url
from app.domain.access import (
    ROLE_ADMIN,
    ROLE_DESIGNER,
    ROLE_DESIGNER_TRELLO,
    WORK_DOMAIN_DUPLICATE,
)
from app.domain.models import OrderState

router = APIRouter(tags=["finance"])


class DesignerSummaryOut(BaseModel):
    designer_id: str | None
    designer_name: str
    username: str | None = None
    total_tasks: int
    unpaid_tasks: int = 0
    paid_tasks: int = 0
    in_review_tasks: int
    in_fix_tasks: int
    done_tasks: int
    first_submission_at: datetime | None
    latest_submission_at: datetime | None
    notes_count: int = 0
    total_amount: int = 0
    unpaid_amount: int = 0
    paid_amount: int = 0


class CreditedTaskOut(BaseModel):
    order_id: str
    external_order_id: str
    product_name: str | None
    thumbnail_url: str | None
    designer_id: str | None
    designer_name: str
    current_state: str
    printerval_status: str | None
    drive_link: str | None
    placeholder_filled: bool = True
    status_changed_at: datetime | None
    review_submitted_at: datetime | None = None
    first_submitted_at: datetime
    latest_submitted_at: datetime
    submission_count: int
    order_created_at: datetime
    notes_count: int = 0
    is_paid: bool = False
    paid_at: datetime | None = None
    paid_by_id: str | None = None
    work_domain: str = "standard"
    custom_rate: int | None = None
    rate: int = 40000


class FinanceStatsResponse(BaseModel):
    total_credited_tasks: int
    total_unpaid_tasks: int = 0
    total_paid_tasks: int = 0
    total_designers: int
    total_done_tasks: int
    total_in_review_tasks: int
    total_in_fix_tasks: int
    standard_rate: int = 40000
    duplicate_rate: int = 40000
    total_amount_unpaid: int = 0
    total_amount_paid: int = 0
    total_amount_credited: int = 0
    designers_summary: list[DesignerSummaryOut]
    tasks: list[CreditedTaskOut]
    total_tasks_count: int
    page: int
    page_size: int
    total_pages: int


class OrderRatesUpdate(BaseModel):
    standard_rate: int
    duplicate_rate: int


class OrderRatesOut(BaseModel):
    standard_rate: int
    duplicate_rate: int


class FinanceNoteCreate(BaseModel):
    target_type: str  # 'order' or 'designer'
    order_id: str | None = None
    order_code: str | None = None
    designer_id: str | None = None
    designer_name: str | None = None
    content: str


class FinanceNoteUpdate(BaseModel):
    content: str


class FinanceNoteOut(BaseModel):
    id: str
    target_type: str
    order_id: str | None = None
    order_code: str | None = None
    designer_id: str | None = None
    designer_name: str | None = None
    author_id: str | None = None
    author_name: str
    content: str
    created_at: datetime
    updated_at: datetime


class FinanceNoteListResponse(BaseModel):
    notes: list[FinanceNoteOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class MarkPaidPayload(BaseModel):
    order_ids: list[str]


@router.get("/finance/rates", response_model=OrderRatesOut)
def get_order_rates(
    user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    platform = db.get(Platform, platform_id)
    if platform is None or not platform.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform not found")
    return OrderRatesOut(
        standard_rate=platform.standard_order_rate,
        duplicate_rate=platform.duplicate_order_rate,
    )


@router.put("/finance/rates", response_model=OrderRatesOut)
def update_order_rates(
    payload: OrderRatesUpdate,
    user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ Admin mới có quyền cập nhật đơn giá.",
        )

    if payload.standard_rate < 0 or payload.duplicate_rate < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Đơn giá không được nhỏ hơn 0.",
        )

    platform = db.get(Platform, platform_id)
    if platform is None or not platform.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform not found")
    platform.standard_order_rate = payload.standard_rate
    platform.duplicate_order_rate = payload.duplicate_rate

    db.commit()
    return OrderRatesOut(
        standard_rate=payload.standard_rate,
        duplicate_rate=payload.duplicate_rate,
    )


@router.get("/finance/stats", response_model=FinanceStatsResponse)
def get_finance_stats(
    request: Request,
    designer_id: str | None = None,
    search: str | None = None,
    state: str | None = None,
    is_paid: bool | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    header_platform_id = request.headers.get("X-Platform-Id")
    p_uuid = None
    if header_platform_id and header_platform_id != "ALL":
        try:
            p_uuid = uuid.UUID(header_platform_id)
            if p_uuid == DEFAULT_PLATFORM_ID:
                p_uuid = None
        except ValueError:
            pass

    # Platform rates
    target_platform = None
    if p_uuid:
        target_platform = db.get(Platform, p_uuid)
    if not target_platform:
        target_platform = db.query(Platform).first()
    standard_rate = target_platform.standard_order_rate if target_platform else 40000
    duplicate_rate = target_platform.duplicate_order_rate if target_platform else 40000

    # 1. Fetch all users for designer name mapping
    all_users = db.query(User).all()
    user_map_by_id: dict[uuid.UUID, User] = {u.id: u for u in all_users}
    user_map_by_name: dict[str, User] = {
        (u.full_name or u.username).lower().strip(): u for u in all_users
    }
    user_map_by_opt: dict[str, User] = {
        u.printerval_designer_option.lower().strip(): u
        for u in all_users
        if u.printerval_designer_option
    }

    # 2. Gather candidate orders
    orders_query = db.query(Order)
    if p_uuid:
        orders_query = orders_query.filter(Order.platform_id == p_uuid)
    orders = orders_query.all()
    orders_by_id: dict[uuid.UUID, Order] = {o.id: o for o in orders}

    if not orders:
        return FinanceStatsResponse(
            total_credited_tasks=0,
            total_unpaid_tasks=0,
            total_paid_tasks=0,
            total_designers=0,
            total_done_tasks=0,
            total_in_review_tasks=0,
            total_in_fix_tasks=0,
            standard_rate=standard_rate,
            duplicate_rate=duplicate_rate,
            total_amount_unpaid=0,
            total_amount_paid=0,
            total_amount_credited=0,
            designers_summary=[],
            tasks=[],
            total_tasks_count=0,
            page=page,
            page_size=page_size,
            total_pages=1,
        )

    # 3. Gather notes count
    order_notes_count: dict[uuid.UUID, int] = {}
    designer_notes_count: dict[str, int] = {}
    all_notes = db.query(FinanceNote).all()
    for n in all_notes:
        if n.order_id:
            order_notes_count[n.order_id] = order_notes_count.get(n.order_id, 0) + 1
        if n.designer_id:
            d_id_str = str(n.designer_id)
            designer_notes_count[d_id_str] = designer_notes_count.get(d_id_str, 0) + 1
        elif n.designer_name:
            d_name_norm = n.designer_name.strip().lower()
            designer_notes_count[d_name_norm] = designer_notes_count.get(d_name_norm, 0) + 1

    # 4. Gather all workflow events related to reviews / submissions / completions
    events = (
        db.query(WorkflowEvent)
        .filter(WorkflowEvent.order_id.in_(list(orders_by_id.keys())))
        .order_by(WorkflowEvent.created_at.asc())
        .all()
    )

    # 5. Gather ResultVersions
    assignments = (
        db.query(Assignment)
        .filter(Assignment.order_id.in_(list(orders_by_id.keys())))
        .all()
    )
    asgn_by_id: dict[uuid.UUID, Assignment] = {a.id: a for a in assignments}
    asgns_by_order: dict[uuid.UUID, list[Assignment]] = {}
    for a in assignments:
        asgns_by_order.setdefault(a.order_id, []).append(a)

    result_versions = (
        db.query(ResultVersion)
        .filter(ResultVersion.assignment_id.in_(list(asgn_by_id.keys())))
        .order_by(ResultVersion.created_at.asc())
        .all()
        if asgn_by_id
        else []
    )

    # 6. Build submission records per (designer_key, order_id)
    submissions_by_key: dict[tuple[str, uuid.UUID], dict[str, Any]] = {}

    for ev in events:
        order = orders_by_id.get(ev.order_id)
        if not order:
            continue

        ev_evidence = ev.evidence or {}
        action = ev_evidence.get("action")
        actor_role = ev_evidence.get("actor_role")
        from_st = (ev.from_state or "").upper()
        to_st = (ev.to_state or "").upper()

        is_submission = (
            action in ("SUBMIT_REVIEW", "RESUBMIT_FIX")
            or (to_st in ("QC_PENDING", "REVIEW") and from_st not in ("QC_PENDING", "REVIEW"))
            or (actor_role == "designer" and to_st in ("QC_PENDING", "REVIEW"))
        )

        if not is_submission:
            continue

        # Identify designer
        des_user: User | None = None
        if ev.actor_id and ev.actor_id in user_map_by_id:
            u_act = user_map_by_id[ev.actor_id]
            if u_act.role in (ROLE_DESIGNER, ROLE_DESIGNER_TRELLO):
                des_user = u_act

        if not des_user and ev_evidence.get("designer_name"):
            d_name = str(ev_evidence["designer_name"]).lower().strip()
            des_user = user_map_by_name.get(d_name) or user_map_by_opt.get(d_name)

        if not des_user and order.printerval_designer:
            d_name = order.printerval_designer.lower().strip()
            des_user = user_map_by_name.get(d_name) or user_map_by_opt.get(d_name)

        if not des_user and ev.order_id in asgns_by_order:
            for asg in asgns_by_order[ev.order_id]:
                if asg.designer_id and asg.designer_id in user_map_by_id:
                    des_user = user_map_by_id[asg.designer_id]
                    break

        des_key = str(des_user.id) if des_user else (ev_evidence.get("designer_name") or order.printerval_designer or (ev_evidence.get("actor_name") if actor_role == "designer" else "Unknown Designer"))
        des_display_name = (des_user.full_name or des_user.username) if des_user else str(des_key)
        des_username = des_user.username if des_user else None
        des_id_str = str(des_user.id) if des_user else None

        key = (des_key, order.id)
        drive_link = ev_evidence.get("drive_link") or (order.note_outsource if ("drive.google" in (order.note_outsource or "") or "http" in (order.note_outsource or "")) else (order.note_outsource if (order.note_outsource or "").strip() else None))

        time_anchor = order.status_changed_at or ev.created_at
        review_sub_time = order.review_submitted_at or order.status_changed_at or ev.created_at

        task_domain = order.work_domain or "standard"
        task_rate = order.custom_rate if order.custom_rate is not None else (
            duplicate_rate if task_domain == WORK_DOMAIN_DUPLICATE else standard_rate
        )

        if key not in submissions_by_key:
            submissions_by_key[key] = {
                "order_id": str(order.id),
                "external_order_id": order.external_order_id,
                "product_name": order.product_name,
                "thumbnail_url": order.thumbnail_url,
                "designer_id": des_id_str,
                "designer_name": des_display_name,
                "designer_username": des_username,
                "designer_key": des_key,
                "current_state": order.state,
                "printerval_status": order.printerval_status,
                "drive_link": drive_link,
                "placeholder_filled": bool(drive_link and str(drive_link).strip()),
                "status_changed_at": time_anchor,
                "review_submitted_at": review_sub_time,
                "first_submitted_at": ev.created_at,
                "latest_submitted_at": ev.created_at,
                "submission_count": 1,
                "order_created_at": order.created_at,
                "notes_count": order_notes_count.get(order.id, 0),
                "is_paid": bool(order.is_paid),
                "paid_at": order.paid_at,
                "paid_by_id": str(order.paid_by_id) if order.paid_by_id else None,
                "work_domain": task_domain,
                "custom_rate": order.custom_rate,
                "rate": task_rate,
            }
        else:
            rec = submissions_by_key[key]
            # Only count as separate submission if > 30s apart from previous recorded submission
            if abs((ev.created_at - rec["latest_submitted_at"]).total_seconds()) > 30:
                rec["submission_count"] += 1
            if ev.created_at < rec["first_submitted_at"]:
                rec["first_submitted_at"] = ev.created_at
            if ev.created_at > rec["latest_submitted_at"]:
                rec["latest_submitted_at"] = ev.created_at
                if drive_link:
                    rec["drive_link"] = drive_link
                    rec["placeholder_filled"] = bool(drive_link and str(drive_link).strip())

    # Also incorporate ResultVersions
    for rv in result_versions:
        asg = asgn_by_id.get(rv.assignment_id)
        if not asg:
            continue
        order = orders_by_id.get(asg.order_id)
        if not order:
            continue

        des_user = user_map_by_id.get(asg.designer_id) if asg.designer_id else None
        des_key = str(des_user.id) if des_user else (order.printerval_designer or "Unknown Designer")
        des_display_name = (des_user.full_name or des_user.username) if des_user else str(des_key)
        des_username = des_user.username if des_user else None
        des_id_str = str(des_user.id) if des_user else None

        key = (des_key, order.id)
        sub_time = rv.submitted_at or rv.created_at
        time_anchor = order.status_changed_at or sub_time
        review_sub_time = order.review_submitted_at or order.status_changed_at or sub_time

        task_domain = order.work_domain or "standard"
        task_rate = order.custom_rate if order.custom_rate is not None else (
            duplicate_rate if task_domain == WORK_DOMAIN_DUPLICATE else standard_rate
        )

        if key not in submissions_by_key:
            submissions_by_key[key] = {
                "order_id": str(order.id),
                "external_order_id": order.external_order_id,
                "product_name": order.product_name,
                "thumbnail_url": order.thumbnail_url,
                "designer_id": des_id_str,
                "designer_name": des_display_name,
                "designer_username": des_username,
                "designer_key": des_key,
                "current_state": order.state,
                "printerval_status": order.printerval_status,
                "drive_link": rv.drive_url,
                "placeholder_filled": bool(rv.drive_url and str(rv.drive_url).strip()),
                "status_changed_at": time_anchor,
                "review_submitted_at": review_sub_time,
                "first_submitted_at": sub_time,
                "latest_submitted_at": sub_time,
                "submission_count": 1,
                "order_created_at": order.created_at,
                "notes_count": order_notes_count.get(order.id, 0),
                "is_paid": bool(order.is_paid),
                "paid_at": order.paid_at,
                "paid_by_id": str(order.paid_by_id) if order.paid_by_id else None,
                "work_domain": task_domain,
                "custom_rate": order.custom_rate,
                "rate": task_rate,
            }
        else:
            rec = submissions_by_key[key]
            if not rec.get("drive_link") and rv.drive_url:
                rec["drive_link"] = rv.drive_url
                rec["placeholder_filled"] = bool(rv.drive_url and str(rv.drive_url).strip())
            if sub_time < rec["first_submitted_at"]:
                rec["first_submitted_at"] = sub_time
            if sub_time > rec["latest_submitted_at"]:
                rec["latest_submitted_at"] = sub_time

    # Also check orders in QC_PENDING, REVIEW, REVISION, DONE that have an assigned designer
    for order in orders:
        st_upper = (order.state or "").upper()
        if st_upper in ("QC_PENDING", "REVIEW", "REVISION", "FIX", "DONE", "CLAIMED_IMPORTED"):
            des_user = None
            if order.id in asgns_by_order:
                for asg in asgns_by_order[order.id]:
                    if asg.designer_id and asg.designer_id in user_map_by_id:
                        des_user = user_map_by_id[asg.designer_id]
                        break
            if not des_user and order.printerval_designer:
                d_name = order.printerval_designer.lower().strip()
                des_user = user_map_by_name.get(d_name) or user_map_by_opt.get(d_name)

            if des_user or order.printerval_designer:
                des_key = str(des_user.id) if des_user else str(order.printerval_designer)
                key = (des_key, order.id)
                drive_val = (
                    order.note_outsource
                    if ("drive.google" in (order.note_outsource or "") or "http" in (order.note_outsource or ""))
                    else (order.note_outsource if (order.note_outsource or "").strip() else None)
                )
                time_anchor = order.status_changed_at or order.updated_at or order.created_at
                review_sub_time = order.review_submitted_at or order.status_changed_at or time_anchor

                task_domain = order.work_domain or "standard"
                task_rate = order.custom_rate if order.custom_rate is not None else (
                    duplicate_rate if task_domain == WORK_DOMAIN_DUPLICATE else standard_rate
                )

                if key not in submissions_by_key:
                    submissions_by_key[key] = {
                        "order_id": str(order.id),
                        "external_order_id": order.external_order_id,
                        "product_name": order.product_name,
                        "thumbnail_url": order.thumbnail_url,
                        "designer_id": str(des_user.id) if des_user else None,
                        "designer_name": (des_user.full_name or des_user.username) if des_user else str(order.printerval_designer),
                        "designer_username": des_user.username if des_user else None,
                        "designer_key": des_key,
                        "current_state": order.state,
                        "printerval_status": order.printerval_status,
                        "drive_link": drive_val,
                        "placeholder_filled": bool(drive_val and str(drive_val).strip()),
                        "status_changed_at": time_anchor,
                        "review_submitted_at": review_sub_time,
                        "first_submitted_at": order.updated_at or order.created_at,
                        "latest_submitted_at": order.updated_at or order.created_at,
                        "submission_count": 1,
                        "order_created_at": order.created_at,
                        "notes_count": order_notes_count.get(order.id, 0),
                        "is_paid": bool(order.is_paid),
                        "paid_at": order.paid_at,
                        "paid_by_id": str(order.paid_by_id) if order.paid_by_id else None,
                        "work_domain": task_domain,
                        "custom_rate": order.custom_rate,
                        "rate": task_rate,
                    }
                else:
                    # Update status_changed_at if available
                    rec = submissions_by_key[key]
                    if order.status_changed_at and not rec.get("status_changed_at"):
                        rec["status_changed_at"] = order.status_changed_at
                    if order.review_submitted_at and not rec.get("review_submitted_at"):
                        rec["review_submitted_at"] = order.review_submitted_at

    all_tasks = list(submissions_by_key.values())

    # If role is designer, restrict to own tasks only
    if user.role in (ROLE_DESIGNER, ROLE_DESIGNER_TRELLO):
        cur_user_name = (user.full_name or user.username).lower().strip()
        cur_user_opt = (user.printerval_designer_option or "").lower().strip()
        all_tasks = [
            t
            for t in all_tasks
            if t["designer_id"] == str(user.id)
            or str(t["designer_key"]).lower().strip() in (str(user.id), cur_user_name, cur_user_opt)
            or str(t["designer_name"]).lower().strip() in (cur_user_name, cur_user_opt)
        ]

    # Date filter: filter by task's status_changed_at / first_submitted_at timestamp
    filtered_tasks = all_tasks
    if start_date:
        try:
            st_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            filtered_tasks = [
                t for t in filtered_tasks if (t.get("status_changed_at") or t["first_submitted_at"]) >= st_dt
            ]
        except Exception:
            pass

    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            if len(end_date) == 10:
                end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            filtered_tasks = [
                t for t in filtered_tasks if (t.get("status_changed_at") or t["first_submitted_at"]) <= end_dt
            ]
        except Exception:
            pass

    # Group summary by designer (only counting credited tasks with placeholder_filled=True)
    designers_map: dict[str, dict[str, Any]] = {}
    for task in filtered_tasks:
        d_key = task["designer_key"]
        if d_key not in designers_map:
            d_id = task["designer_id"]
            d_notes = 0
            if d_id and d_id in designer_notes_count:
                d_notes = designer_notes_count[d_id]
            elif task["designer_name"].strip().lower() in designer_notes_count:
                d_notes = designer_notes_count[task["designer_name"].strip().lower()]

            designers_map[d_key] = {
                "designer_id": task["designer_id"],
                "designer_name": task["designer_name"],
                "username": task["designer_username"],
                "total_tasks": 0,
                "unpaid_tasks": 0,
                "paid_tasks": 0,
                "in_review_tasks": 0,
                "in_fix_tasks": 0,
                "done_tasks": 0,
                "first_submission_at": task["first_submitted_at"],
                "latest_submission_at": task["latest_submitted_at"],
                "notes_count": d_notes,
                "total_amount": 0,
                "unpaid_amount": 0,
                "paid_amount": 0,
            }
        d_rec = designers_map[d_key]
        if task.get("placeholder_filled"):
            d_rec["total_tasks"] += 1
            t_rate = task.get("rate", standard_rate)
            d_rec["total_amount"] += t_rate
            if task.get("is_paid"):
                d_rec["paid_tasks"] += 1
                d_rec["paid_amount"] += t_rate
            else:
                d_rec["unpaid_tasks"] += 1
                d_rec["unpaid_amount"] += t_rate

            st = (task["current_state"] or "").upper()
            if st in ("QC_PENDING", "REVIEW", "RESULT_SUBMITTED"):
                d_rec["in_review_tasks"] += 1
            elif st in ("REVISION", "FIX", "REVISION_REQUESTED"):
                d_rec["in_fix_tasks"] += 1
            elif st in ("DONE", "CLAIMED_IMPORTED", "COMPLETED"):
                d_rec["done_tasks"] += 1

        if task["first_submitted_at"] < d_rec["first_submission_at"]:
            d_rec["first_submission_at"] = task["first_submitted_at"]
        if task["latest_submitted_at"] > d_rec["latest_submission_at"]:
            d_rec["latest_submission_at"] = task["latest_submitted_at"]

    designers_summary = [
        DesignerSummaryOut(**v)
        for v in sorted(designers_map.values(), key=lambda x: x["total_tasks"], reverse=True)
    ]

    # Global KPI counts (only credited tasks with placeholder_filled=True)
    credited_tasks = [t for t in filtered_tasks if t.get("placeholder_filled")]
    total_credited = len(credited_tasks)
    total_unpaid = sum(1 for t in credited_tasks if not t.get("is_paid"))
    total_paid = sum(1 for t in credited_tasks if t.get("is_paid"))
    total_amount_credited = sum(t.get("rate", standard_rate) for t in credited_tasks)
    total_amount_unpaid = sum(t.get("rate", standard_rate) for t in credited_tasks if not t.get("is_paid"))
    total_amount_paid = sum(t.get("rate", standard_rate) for t in credited_tasks if t.get("is_paid"))

    total_done = sum(
        1 for t in credited_tasks if (t["current_state"] or "").upper() in ("DONE", "CLAIMED_IMPORTED", "COMPLETED")
    )
    total_review = sum(
        1 for t in credited_tasks if (t["current_state"] or "").upper() in ("QC_PENDING", "REVIEW", "RESULT_SUBMITTED")
    )
    total_fix = sum(
        1 for t in credited_tasks if (t["current_state"] or "").upper() in ("REVISION", "FIX", "REVISION_REQUESTED")
    )

    # Filter task list by designer_id, search, state, is_paid
    tasks_to_render = filtered_tasks
    if designer_id and designer_id.strip() and designer_id != "ALL":
        d_filter = designer_id.strip().lower()
        tasks_to_render = [
            t
            for t in tasks_to_render
            if str(t["designer_id"]).lower() == d_filter
            or str(t["designer_key"]).lower() == d_filter
            or str(t["designer_name"]).lower() == d_filter
        ]

    if is_paid is not None:
        tasks_to_render = [t for t in tasks_to_render if bool(t.get("is_paid")) == is_paid]

    if search and search.strip():
        term = search.strip().lower()
        tasks_to_render = [
            t
            for t in tasks_to_render
            if term in t["external_order_id"].lower()
            or (t["product_name"] and term in t["product_name"].lower())
            or term in t["designer_name"].lower()
        ]

    if state and state.strip() and state != "ALL":
        st_filter = state.strip().upper()
        if st_filter == "DONE":
            tasks_to_render = [
                t for t in tasks_to_render if (t["current_state"] or "").upper() in ("DONE", "CLAIMED_IMPORTED", "COMPLETED")
            ]
        elif st_filter in ("REVIEW", "QC_PENDING"):
            tasks_to_render = [
                t for t in tasks_to_render if (t["current_state"] or "").upper() in ("QC_PENDING", "REVIEW", "RESULT_SUBMITTED")
            ]
        elif st_filter in ("FIX", "REVISION"):
            tasks_to_render = [
                t for t in tasks_to_render if (t["current_state"] or "").upper() in ("REVISION", "FIX", "REVISION_REQUESTED")
            ]
        else:
            tasks_to_render = [
                t for t in tasks_to_render if (t["current_state"] or "").upper() == st_filter
            ]

    # Sort tasks by latest status_changed_at or submission first
    tasks_to_render.sort(
        key=lambda x: (x.get("status_changed_at") or x["latest_submitted_at"]), reverse=True
    )

    total_tasks_count = len(tasks_to_render)
    offset = (page - 1) * page_size
    paginated_items = tasks_to_render[offset : offset + page_size]
    total_pages = max(1, math.ceil(total_tasks_count / page_size))

    if user.role != ROLE_ADMIN:
        sanitized_items = []
        for item in paginated_items:
            c = dict(item)
            c["printerval_status"] = None
            if c.get("thumbnail_url"):
                c["thumbnail_url"] = encode_proxy_url(c["thumbnail_url"])
            sanitized_items.append(c)
        paginated_items = sanitized_items

    task_outs = [CreditedTaskOut(**item) for item in paginated_items]

    return FinanceStatsResponse(
        total_credited_tasks=total_credited,
        total_unpaid_tasks=total_unpaid,
        total_paid_tasks=total_paid,
        total_designers=len(designers_summary),
        total_done_tasks=total_done,
        total_in_review_tasks=total_review,
        total_in_fix_tasks=total_fix,
        standard_rate=standard_rate,
        duplicate_rate=duplicate_rate,
        total_amount_unpaid=total_amount_unpaid,
        total_amount_paid=total_amount_paid,
        total_amount_credited=total_amount_credited,
        designers_summary=designers_summary,
        tasks=task_outs,
        total_tasks_count=total_tasks_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("/finance/mark-paid")
def mark_orders_paid(
    payload: MarkPaidPayload,
    user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Chỉ Admin mới có quyền xác nhận thanh toán.")

    if not payload.order_ids:
        return {"ok": True, "updated_count": 0}

    parsed_ids = []
    for oid in payload.order_ids:
        try:
            parsed_ids.append(uuid.UUID(oid))
        except ValueError:
            pass

    if not parsed_ids:
        return {"ok": True, "updated_count": 0}

    now_utc = datetime.now(UTC)
    orders = (
        db.query(Order)
        .filter(Order.id.in_(parsed_ids), Order.platform_id == platform_id)
        .with_for_update()
        .all()
    )
    for o in orders:
        o.is_paid = True
        o.paid_at = now_utc
        o.paid_by_id = user.id
        norm_st = (o.state or "").upper()
        if norm_st not in ("DONE", "CLAIMED_IMPORTED", "COMPLETED"):
            previous_state = o.state
            o.state = OrderState.DONE.value
            o.status_changed_at = now_utc
            db.add(
                WorkflowEvent(
                    order_id=o.id,
                    from_state=previous_state,
                    to_state=OrderState.DONE.value,
                    actor_id=user.id,
                    evidence={"source": "finance", "action": "mark_paid"},
                )
            )
    db.commit()

    # Telegram notification for each paid designer
    try:
        from collections import defaultdict

        from app.adapters.db.models import Assignment, Platform
        from app.workers.telegram_tasks import async_notify_designer_payment, safe_dispatch_telegram_task

        plat = db.get(Platform, platform_id)
        std_rate = plat.standard_order_rate if plat else 40000
        dup_rate = plat.duplicate_order_rate if plat else 40000

        des_summary = defaultdict(lambda: {"count": 0, "amount": 0})
        for o in orders:
            rate = o.custom_rate if o.custom_rate is not None else (dup_rate if o.work_domain == "duplicate" else std_rate)
            asgn = db.query(Assignment).filter(Assignment.order_id == o.id, Assignment.status != "cancelled").first()
            if asgn and asgn.designer_id:
                des_summary[asgn.designer_id]["count"] += 1
                des_summary[asgn.designer_id]["amount"] += rate

        for des_id, stats in des_summary.items():
            if stats["count"] > 0:
                safe_dispatch_telegram_task(async_notify_designer_payment, str(des_id), stats["count"], stats["amount"])
    except Exception:
        pass

    return {"ok": True, "updated_count": len(orders)}


@router.post("/finance/unmark-paid")
def unmark_orders_paid(
    payload: MarkPaidPayload,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Chỉ Admin mới có quyền hủy thanh toán.")

    if not payload.order_ids:
        return {"ok": True, "updated_count": 0}

    parsed_ids = []
    for oid in payload.order_ids:
        try:
            parsed_ids.append(uuid.UUID(oid))
        except ValueError:
            pass

    if not parsed_ids:
        return {"ok": True, "updated_count": 0}

    orders = db.query(Order).filter(Order.id.in_(parsed_ids)).all()
    for o in orders:
        o.is_paid = False
        o.paid_at = None
        o.paid_by_id = None
    db.commit()
    return {"ok": True, "updated_count": len(orders)}


@router.get("/finance/export-excel")
def export_finance_excel(
    request: Request,
    designer_id: str | None = None,
    is_paid: bool | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from fastapi.responses import Response

    stats_res = get_finance_stats(
        request=request,
        designer_id=designer_id,
        is_paid=is_paid,
        start_date=start_date,
        end_date=end_date,
        page=1,
        page_size=10000,
        user=user,
        db=db,
    )

    import csv
    import io

    output = io.StringIO()
    # Write UTF-8 BOM for Excel compatibility
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "Mã Đơn",
        "Loại Đơn",
        "Đơn Giá (VNĐ)",
        "Link Sản Phẩm (Bài Nộp)",
        "Tên Designer",
        "Thời Gian Nộp Review",
        "Thời Gian Thanh Toán",
        "Trạng Thái Thanh Toán",
    ])

    for t in stats_res.tasks:
        sub_time = t.review_submitted_at or t.status_changed_at or t.first_submitted_at
        sub_str = sub_time.strftime("%d/%m/%Y %H:%M:%S") if sub_time else ""
        paid_str = t.paid_at.strftime("%d/%m/%Y %H:%M:%S") if t.paid_at else ""
        paid_status = "Đã thanh toán" if t.is_paid else "Chưa thanh toán"
        domain_str = "Đơn trùng" if t.work_domain == "duplicate" else "Đơn thường"

        writer.writerow([
            t.external_order_id,
            domain_str,
            t.rate,
            t.drive_link or "",
            t.designer_name,
            sub_str,
            paid_str,
            paid_status,
        ])

    csv_data = output.getvalue()
    filename = f"bao_cao_tai_chinh_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        content=csv_data.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


# ---------------------------------------------------------------------------
# Finance Notes API
# ---------------------------------------------------------------------------

@router.get("/finance/notes", response_model=FinanceNoteListResponse)
def list_finance_notes(
    request: Request,
    target_type: str | None = None,
    order_id: str | None = None,
    designer_id: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(FinanceNote)

    header_platform_id = request.headers.get("X-Platform-Id")
    if header_platform_id and header_platform_id != "ALL":
        try:
            p_uuid = uuid.UUID(header_platform_id)
            if p_uuid != DEFAULT_PLATFORM_ID:
                query = query.filter((FinanceNote.platform_id == p_uuid) | (FinanceNote.platform_id.is_(None)))
        except ValueError:
            pass

    # Non-admin users only see notes for themselves
    if user.role == "designer":
        query = query.filter(FinanceNote.designer_id == user.id)

    if target_type and target_type.strip() and target_type.lower() != "all":
        query = query.filter(FinanceNote.target_type == target_type.strip().lower())

    if order_id and order_id.strip():
        try:
            o_uuid = uuid.UUID(order_id)
            query = query.filter(FinanceNote.order_id == o_uuid)
        except ValueError:
            query = query.filter(FinanceNote.order_code == order_id.strip())

    if designer_id and designer_id.strip() and designer_id != "ALL":
        try:
            d_uuid = uuid.UUID(designer_id)
            query = query.filter(FinanceNote.designer_id == d_uuid)
        except ValueError:
            query = query.filter(FinanceNote.designer_name.ilike(f"%{designer_id.strip()}%"))

    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            FinanceNote.content.ilike(term)
            | FinanceNote.order_code.ilike(term)
            | FinanceNote.designer_name.ilike(term)
            | FinanceNote.author_name.ilike(term)
        )

    query = query.order_by(desc(FinanceNote.created_at))
    total = query.count()
    total_pages = max(1, math.ceil(total / page_size))
    offset = (page - 1) * page_size
    notes = query.offset(offset).limit(page_size).all()

    note_outs = [
        FinanceNoteOut(
            id=str(n.id),
            target_type=n.target_type,
            order_id=str(n.order_id) if n.order_id else None,
            order_code=n.order_code,
            designer_id=str(n.designer_id) if n.designer_id else None,
            designer_name=n.designer_name,
            author_id=str(n.author_id) if n.author_id else None,
            author_name=n.author_name,
            content=n.content,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )
        for n in notes
    ]

    return FinanceNoteListResponse(
        notes=note_outs,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("/finance/notes", response_model=FinanceNoteOut)
def create_finance_note(
    request: Request,
    payload: FinanceNoteCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ Admin mới có quyền thêm ghi chú tài chính.",
        )

    content = payload.content.strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nội dung ghi chú không được để trống.",
        )

    header_platform_id = request.headers.get("X-Platform-Id")
    p_uuid = None
    if header_platform_id and header_platform_id != "ALL":
        try:
            p_uuid = uuid.UUID(header_platform_id)
            if p_uuid == DEFAULT_PLATFORM_ID:
                p_uuid = None
        except ValueError:
            pass

    order_uuid: uuid.UUID | None = None
    order_code: str | None = payload.order_code
    if payload.order_id:
        try:
            order_uuid = uuid.UUID(payload.order_id)
            ord_obj = db.get(Order, order_uuid)
            if ord_obj:
                order_code = ord_obj.external_order_id
                if not p_uuid:
                    p_uuid = ord_obj.platform_id
        except ValueError:
            pass

    designer_uuid: uuid.UUID | None = None
    designer_name: str | None = payload.designer_name
    if payload.designer_id:
        try:
            designer_uuid = uuid.UUID(payload.designer_id)
            des_obj = db.get(User, designer_uuid)
            if des_obj:
                designer_name = des_obj.full_name or des_obj.username
        except ValueError:
            pass

    note = FinanceNote(
        platform_id=p_uuid,
        target_type=payload.target_type.lower().strip(),
        order_id=order_uuid,
        order_code=order_code,
        designer_id=designer_uuid,
        designer_name=designer_name,
        author_id=user.id,
        author_name=user.full_name or user.username,
        content=content,
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    return FinanceNoteOut(
        id=str(note.id),
        target_type=note.target_type,
        order_id=str(note.order_id) if note.order_id else None,
        order_code=note.order_code,
        designer_id=str(note.designer_id) if note.designer_id else None,
        designer_name=note.designer_name,
        author_id=str(note.author_id) if note.author_id else None,
        author_name=note.author_name,
        content=note.content,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.put("/finance/notes/{note_id}", response_model=FinanceNoteOut)
def update_finance_note(
    note_id: str,
    payload: FinanceNoteUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        n_uuid = uuid.UUID(note_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID ghi chú không hợp lệ")

    note = db.get(FinanceNote, n_uuid)
    if not note:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy ghi chú")

    if user.role != "admin" and note.author_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền chỉnh sửa ghi chú này",
        )

    content = payload.content.strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nội dung ghi chú không được để trống.",
        )

    note.content = content
    db.commit()
    db.refresh(note)

    return FinanceNoteOut(
        id=str(note.id),
        target_type=note.target_type,
        order_id=str(note.order_id) if note.order_id else None,
        order_code=note.order_code,
        designer_id=str(note.designer_id) if note.designer_id else None,
        designer_name=note.designer_name,
        author_id=str(note.author_id) if note.author_id else None,
        author_name=note.author_name,
        content=note.content,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.delete("/finance/notes/{note_id}")
def delete_finance_note(
    note_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        n_uuid = uuid.UUID(note_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID ghi chú không hợp lệ")

    note = db.get(FinanceNote, n_uuid)
    if not note:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy ghi chú")

    if user.role != "admin" and note.author_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền xóa ghi chú này",
        )

    db.delete(note)
    db.commit()
    return {"message": "Đã xóa ghi chú thành công", "id": note_id}

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.db.models import Assignment, Order, ResultVersion, User, WorkflowEvent
from app.api.deps import DEFAULT_PLATFORM_ID, get_current_user, get_db

router = APIRouter(tags=["finance"])


class DesignerSummaryOut(BaseModel):
    designer_id: str | None
    designer_name: str
    username: str | None = None
    total_tasks: int
    in_review_tasks: int
    in_fix_tasks: int
    done_tasks: int
    first_submission_at: datetime | None
    latest_submission_at: datetime | None


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
    first_submitted_at: datetime
    latest_submitted_at: datetime
    submission_count: int
    order_created_at: datetime


class FinanceStatsResponse(BaseModel):
    total_credited_tasks: int
    total_designers: int
    total_done_tasks: int
    total_in_review_tasks: int
    total_in_fix_tasks: int
    designers_summary: list[DesignerSummaryOut]
    tasks: list[CreditedTaskOut]
    total_tasks_count: int
    page: int
    page_size: int
    total_pages: int


@router.get("/finance/stats", response_model=FinanceStatsResponse)
def get_finance_stats(
    request: Request,
    designer_id: str | None = None,
    search: str | None = None,
    state: str | None = None,
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
            total_designers=0,
            total_done_tasks=0,
            total_in_review_tasks=0,
            total_in_fix_tasks=0,
            designers_summary=[],
            tasks=[],
            total_tasks_count=0,
            page=page,
            page_size=page_size,
            total_pages=1,
        )

    # 3. Gather all workflow events related to reviews / submissions / completions
    events = (
        db.query(WorkflowEvent)
        .filter(WorkflowEvent.order_id.in_(list(orders_by_id.keys())))
        .order_by(WorkflowEvent.created_at.asc())
        .all()
    )

    # 4. Gather ResultVersions
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

    # 5. Build submission records per (designer_key, order_id)
    # A designer submission is recognized if:
    # - WorkflowEvent with action in ("SUBMIT_REVIEW") or to_state in ("QC_PENDING", "REVIEW")
    # - OR ResultVersion exists
    # - OR Order reached QC_PENDING / REVIEW / REVISION / DONE and has an assigned designer
    submissions_by_key: dict[tuple[str, uuid.UUID], dict[str, Any]] = {}

    for ev in events:
        order = orders_by_id.get(ev.order_id)
        if not order:
            continue

        ev_evidence = ev.evidence or {}
        action = ev_evidence.get("action")
        actor_role = ev_evidence.get("actor_role")
        to_st = (ev.to_state or "").upper()

        is_submission = (
            action == "SUBMIT_REVIEW"
            or to_st in ("QC_PENDING", "REVIEW")
            or (actor_role == "designer" and to_st in ("QC_PENDING", "REVIEW", "DONE", "REVISION"))
        )

        if not is_submission:
            continue

        # Identify designer
        des_user: User | None = None
        if ev.actor_id and ev.actor_id in user_map_by_id:
            u_act = user_map_by_id[ev.actor_id]
            if u_act.role == "designer":
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
        drive_link = ev_evidence.get("drive_link") or (order.note_outsource if ("drive.google" in (order.note_outsource or "") or "http" in (order.note_outsource or "")) else None)

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
                "first_submitted_at": ev.created_at,
                "latest_submitted_at": ev.created_at,
                "submission_count": 1,
                "order_created_at": order.created_at,
            }
        else:
            rec = submissions_by_key[key]
            rec["submission_count"] += 1
            if ev.created_at < rec["first_submitted_at"]:
                rec["first_submitted_at"] = ev.created_at
            if ev.created_at > rec["latest_submitted_at"]:
                rec["latest_submitted_at"] = ev.created_at
                if drive_link:
                    rec["drive_link"] = drive_link

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
                "first_submitted_at": sub_time,
                "latest_submitted_at": sub_time,
                "submission_count": 1,
                "order_created_at": order.created_at,
            }
        else:
            rec = submissions_by_key[key]
            if not rec.get("drive_link") and rv.drive_url:
                rec["drive_link"] = rv.drive_url
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
                des_key = str(des_user.id) if des_user else order.printerval_designer
                key = (des_key, order.id)
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
                        "drive_link": order.note_outsource if ("drive.google" in (order.note_outsource or "") or "http" in (order.note_outsource or "")) else None,
                        "first_submitted_at": order.updated_at or order.created_at,
                        "latest_submitted_at": order.updated_at or order.created_at,
                        "submission_count": 1,
                        "order_created_at": order.created_at,
                    }

    all_credited_tasks = list(submissions_by_key.values())

    # If role is designer, restrict to own tasks only
    if user.role == "designer":
        cur_user_name = (user.full_name or user.username).lower().strip()
        cur_user_opt = (user.printerval_designer_option or "").lower().strip()
        all_credited_tasks = [
            t
            for t in all_credited_tasks
            if t["designer_id"] == str(user.id)
            or str(t["designer_key"]).lower().strip() in (str(user.id), cur_user_name, cur_user_opt)
            or str(t["designer_name"]).lower().strip() in (cur_user_name, cur_user_opt)
        ]

    # Group summary by designer
    designers_map: dict[str, dict[str, Any]] = {}
    for task in all_credited_tasks:
        d_key = task["designer_key"]
        if d_key not in designers_map:
            designers_map[d_key] = {
                "designer_id": task["designer_id"],
                "designer_name": task["designer_name"],
                "username": task["designer_username"],
                "total_tasks": 0,
                "in_review_tasks": 0,
                "in_fix_tasks": 0,
                "done_tasks": 0,
                "first_submission_at": task["first_submitted_at"],
                "latest_submission_at": task["latest_submitted_at"],
            }
        d_rec = designers_map[d_key]
        d_rec["total_tasks"] += 1
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

    # Global KPI counts
    total_credited = len(all_credited_tasks)
    total_done = sum(
        1 for t in all_credited_tasks if (t["current_state"] or "").upper() in ("DONE", "CLAIMED_IMPORTED", "COMPLETED")
    )
    total_review = sum(
        1 for t in all_credited_tasks if (t["current_state"] or "").upper() in ("QC_PENDING", "REVIEW", "RESULT_SUBMITTED")
    )
    total_fix = sum(
        1 for t in all_credited_tasks if (t["current_state"] or "").upper() in ("REVISION", "FIX", "REVISION_REQUESTED")
    )

    # Filter task list
    filtered_tasks = all_credited_tasks
    if designer_id and designer_id.strip() and designer_id != "ALL":
        d_filter = designer_id.strip().lower()
        filtered_tasks = [
            t
            for t in filtered_tasks
            if str(t["designer_id"]).lower() == d_filter
            or str(t["designer_key"]).lower() == d_filter
            or str(t["designer_name"]).lower() == d_filter
        ]

    if search and search.strip():
        term = search.strip().lower()
        filtered_tasks = [
            t
            for t in filtered_tasks
            if term in t["external_order_id"].lower()
            or (t["product_name"] and term in t["product_name"].lower())
            or term in t["designer_name"].lower()
        ]

    if state and state.strip() and state != "ALL":
        st_filter = state.strip().upper()
        if st_filter == "DONE":
            filtered_tasks = [
                t for t in filtered_tasks if (t["current_state"] or "").upper() in ("DONE", "CLAIMED_IMPORTED", "COMPLETED")
            ]
        elif st_filter in ("REVIEW", "QC_PENDING"):
            filtered_tasks = [
                t for t in filtered_tasks if (t["current_state"] or "").upper() in ("QC_PENDING", "REVIEW", "RESULT_SUBMITTED")
            ]
        elif st_filter in ("FIX", "REVISION"):
            filtered_tasks = [
                t for t in filtered_tasks if (t["current_state"] or "").upper() in ("REVISION", "FIX", "REVISION_REQUESTED")
            ]
        else:
            filtered_tasks = [
                t for t in filtered_tasks if (t["current_state"] or "").upper() == st_filter
            ]

    if start_date:
        try:
            st_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            filtered_tasks = [t for t in filtered_tasks if t["first_submitted_at"] >= st_dt]
        except Exception:
            pass

    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            filtered_tasks = [t for t in filtered_tasks if t["first_submitted_at"] <= end_dt]
        except Exception:
            pass

    # Sort tasks by latest submission first
    filtered_tasks.sort(key=lambda x: x["latest_submitted_at"], reverse=True)

    total_tasks_count = len(filtered_tasks)
    offset = (page - 1) * page_size
    paginated_items = filtered_tasks[offset : offset + page_size]
    total_pages = max(1, math.ceil(total_tasks_count / page_size))

    task_outs = [CreditedTaskOut(**item) for item in paginated_items]

    return FinanceStatsResponse(
        total_credited_tasks=total_credited,
        total_designers=len(designers_summary),
        total_done_tasks=total_done,
        total_in_review_tasks=total_review,
        total_in_fix_tasks=total_fix,
        designers_summary=designers_summary,
        tasks=task_outs,
        total_tasks_count=total_tasks_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )

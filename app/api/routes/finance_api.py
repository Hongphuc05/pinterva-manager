from __future__ import annotations

import math
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
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
from app.application.concurrency import require_expected_order_version
from app.application.sanitization import encode_proxy_url
from app.domain.access import (
    DUPLICATE_CHECK_DUPLICATE,
    ROLE_ADMIN,
    ROLE_DESIGNER,
    ROLE_DESIGNER_TRELLO,
    ROLE_SUPPORT,
    WORK_DOMAIN_DUPLICATE,
)
from app.domain.models import OrderState

router = APIRouter(tags=["finance"])

VN_TZ = timezone(timedelta(hours=7))


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    nfd = unicodedata.normalize("NFD", text.strip().lower())
    nfd = nfd.replace("đ", "d").replace("Đ", "d")
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")



def parse_date_to_utc_timestamp(date_str: str | None, is_end_of_day: bool = False) -> float | None:
    if not date_str or not str(date_str).strip():
        return None
    try:
        s = str(date_str).strip()
        if len(s) == 10:  # "YYYY-MM-DD"
            if is_end_of_day:
                s = f"{s}T23:59:59.999999+07:00"
            else:
                s = f"{s}T00:00:00+07:00"
        elif "T" in s and not ("+" in s or "-" in s[10:] or s.endswith("Z")):
            s = f"{s}+07:00"

        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=VN_TZ)
        return dt.timestamp()
    except Exception:
        return None


def get_task_submission_timestamp(task: dict[str, Any]) -> float | None:
    dt = task.get("first_submitted_at") or task.get("review_submitted_at") or task.get("status_changed_at")
    if not dt:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()



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


class SupportOrderOut(BaseModel):
    """One order a Support tagged Trùng lặp (the detail behind the count)."""

    id: str
    external_order_id: str
    product_name: str | None = None
    thumbnail_url: str | None = None
    classified_at: datetime | None = None


class SupportSummaryOut(BaseModel):
    support_id: str
    support_name: str
    username: str | None = None
    classified_tasks: int = 0
    first_classified_at: datetime | None = None
    latest_classified_at: datetime | None = None


class CreditedTaskOut(BaseModel):
    order_id: str
    order_version: int
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
    # Support classification work is counted separately from Designer
    # submissions. It has no payment state; Admin uses the summary to calculate
    # the Support's workload, while Support sees only their own count.
    support_classified_count: int = 0
    support_summary: list[SupportSummaryOut] = Field(default_factory=list)
    # Only filled for a Support looking at their own work.
    support_orders: list[SupportOrderOut] = Field(default_factory=list)


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
    order_ids: list[str] = []
    designer_id: str | None = None
    expected_versions: dict[uuid.UUID, int] | None = None



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
    page_size: int = Query(50, ge=1, le=10000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p_uuid = None
    if user.role == ROLE_SUPPORT:
        # Support accounts are permanently scoped to their assigned platform;
        # never trust a browser-supplied X-Platform-Id for this role.
        if user.platform_id is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Tài khoản Support chưa được gán vào Acc Mẹ Printerval.",
            )
        p_uuid = user.platform_id
    else:
        header_platform_id = request.headers.get("X-Platform-Id")
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
    user_map_by_any: dict[str, User] = {}
    for u in all_users:
        if u.username:
            user_map_by_any[u.username.lower().strip()] = u
            user_map_by_any[normalize_text(u.username)] = u
        if u.full_name:
            user_map_by_any[u.full_name.lower().strip()] = u
            user_map_by_any[normalize_text(u.full_name)] = u
        if u.printerval_designer_option:
            user_map_by_any[u.printerval_designer_option.lower().strip()] = u
            user_map_by_any[normalize_text(u.printerval_designer_option)] = u

    def resolve_designer_user(candidate: str | None) -> User | None:
        if not candidate:
            return None
        cand_str = str(candidate).strip()
        if not cand_str:
            return None
        try:
            u_id = uuid.UUID(cand_str)
            if u_id in user_map_by_id:
                return user_map_by_id[u_id]
        except ValueError:
            pass

        norm_cand = normalize_text(cand_str)
        if cand_str.lower() in user_map_by_any:
            return user_map_by_any[cand_str.lower()]
        if norm_cand in user_map_by_any:
            return user_map_by_any[norm_cand]

        return None



    # 2. Gather candidate orders
    orders_query = db.query(Order)
    if p_uuid:
        orders_query = orders_query.filter(Order.platform_id == p_uuid)
    orders = orders_query.all()
    orders_by_id: dict[uuid.UUID, Order] = {o.id: o for o in orders}

    # Classification work is credited by the timestamp at which Support made
    # the decision, not by the Designer's later submission/payment timeline.
    start_ts = parse_date_to_utc_timestamp(start_date, is_end_of_day=False)
    end_ts = parse_date_to_utc_timestamp(end_date, is_end_of_day=True)

    def is_in_date_range(value: datetime | None) -> bool:
        if value is None:
            return False
        timestamp = value.timestamp()
        return (start_ts is None or timestamp >= start_ts) and (
            end_ts is None or timestamp <= end_ts
        )

    support_classified_orders = [
        order
        for order in orders
        if order.duplicate_check_status == DUPLICATE_CHECK_DUPLICATE
        and order.support_classified_by_id
        and is_in_date_range(order.support_classified_at)
    ]

    support_summary_by_id: dict[uuid.UUID, dict[str, Any]] = {}
    for order in support_classified_orders:
        support_user = user_map_by_id.get(order.support_classified_by_id)
        if support_user is None or support_user.role != ROLE_SUPPORT:
            continue
        record = support_summary_by_id.setdefault(
            support_user.id,
            {
                "support_id": str(support_user.id),
                "support_name": support_user.full_name or support_user.username,
                "username": support_user.username,
                "classified_tasks": 0,
                "first_classified_at": order.support_classified_at,
                "latest_classified_at": order.support_classified_at,
            },
        )
        record["classified_tasks"] += 1
        if order.support_classified_at and (
            record["first_classified_at"] is None
            or order.support_classified_at < record["first_classified_at"]
        ):
            record["first_classified_at"] = order.support_classified_at
        if order.support_classified_at and (
            record["latest_classified_at"] is None
            or order.support_classified_at > record["latest_classified_at"]
        ):
            record["latest_classified_at"] = order.support_classified_at

    support_summary = [
        SupportSummaryOut(**record)
        for record in sorted(
            support_summary_by_id.values(),
            key=lambda item: (-item["classified_tasks"], item["support_name"]),
        )
    ]

    if user.role == ROLE_SUPPORT:
        own_count = sum(
            1
            for order in support_classified_orders
            if order.support_classified_by_id == user.id
        )
        own_summary = [
            item for item in support_summary if item.support_id == str(user.id)
        ]
        own_orders = sorted(
            (order for order in support_classified_orders if order.support_classified_by_id == user.id),
            key=lambda order: order.support_classified_at,
            reverse=True,
        )
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
            support_classified_count=own_count,
            support_summary=own_summary,
            support_orders=[
                SupportOrderOut(
                    id=str(order.id),
                    external_order_id=order.external_order_id,
                    product_name=order.product_name,
                    thumbnail_url=order.thumbnail_url,
                    classified_at=order.support_classified_at,
                )
                for order in own_orders
            ],
        )

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
        .order_by(Assignment.created_at.desc())
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
    rv_by_asgn: dict[uuid.UUID, list[ResultVersion]] = {}
    rv_by_order: dict[uuid.UUID, list[ResultVersion]] = {}
    for rv in result_versions:
        rv_by_asgn.setdefault(rv.assignment_id, []).append(rv)
        asg = asgn_by_id.get(rv.assignment_id)
        if asg:
            rv_by_order.setdefault(asg.order_id, []).append(rv)

    # 6. Build submission records per (designer_key, order_id)
    # 6. Build submission records strictly keyed by order.id (single order count rule)
    submissions_by_order: dict[uuid.UUID, dict[str, Any]] = {}

    # Map order.id -> list of submission records: (timestamp, des_user, drive_link)
    order_submission_candidates: dict[uuid.UUID, list[tuple[datetime, User | None, str | None]]] = {}

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

        des_user: User | None = None
        if ev.actor_id and ev.actor_id in user_map_by_id:
            u_act = user_map_by_id[ev.actor_id]
            if u_act.role in (ROLE_DESIGNER, ROLE_DESIGNER_TRELLO):
                des_user = u_act

        if not des_user and ev_evidence.get("designer_name"):
            des_user = resolve_designer_user(ev_evidence["designer_name"])

        if not des_user and ev.order_id in asgns_by_order:
            for asg in asgns_by_order[ev.order_id]:
                if asg.status != "cancelled" and asg.designer_id and asg.designer_id in user_map_by_id:
                    des_user = user_map_by_id[asg.designer_id]
                    break

        ev_drive = ev_evidence.get("drive_link")
        order_submission_candidates.setdefault(order.id, []).append((ev.created_at, des_user, ev_drive))

    for rv in result_versions:
        asg = asgn_by_id.get(rv.assignment_id)
        if not asg:
            continue
        order = orders_by_id.get(asg.order_id)
        if not order:
            continue

        des_user = user_map_by_id.get(asg.designer_id) if asg.designer_id else None
        sub_time = rv.submitted_at or rv.created_at or order.created_at
        order_submission_candidates.setdefault(order.id, []).append((sub_time, des_user, rv.drive_url))

    # Process each order in system ONCE
    for order in orders:
        cands = order_submission_candidates.get(order.id, [])
        cands_sorted = sorted(cands, key=lambda x: x[0], reverse=True)  # latest first

        des_user: User | None = None
        latest_drive_link: str | None = None
        first_submitted_at: datetime | None = None
        latest_submitted_at: datetime | None = None

        if cands_sorted:
            # Credit goes to the designer who submitted most recently ("sau cùng")
            latest_sub = cands_sorted[0]
            des_user = latest_sub[1]
            latest_submitted_at = latest_sub[0]
            first_submitted_at = cands_sorted[-1][0]
            for _, d_u, d_link in cands_sorted:
                if d_link and not latest_drive_link:
                    latest_drive_link = d_link
                if not des_user and d_u:
                    des_user = d_u

        # Fallback to current assignment if no submission candidate designer
        if not des_user and order.id in asgns_by_order:
            for asg in asgns_by_order[order.id]:
                if asg.status != "cancelled" and asg.designer_id and asg.designer_id in user_map_by_id:
                    des_user = user_map_by_id[asg.designer_id]
                    break

        des_key = str(des_user.id) if des_user else "unassigned"
        des_display_name = (des_user.full_name or des_user.username) if des_user else "Chưa phân công"
        des_username = des_user.username if des_user else None
        des_id_str = str(des_user.id) if des_user else None

        raw_note = (order.note_outsource or "").strip()
        has_note_url = bool("http://" in raw_note or "https://" in raw_note or "drive.google" in raw_note or "docs.google" in raw_note)
        order_rvs = rv_by_order.get(order.id, [])
        drive_link = latest_drive_link or (order_rvs[0].drive_url if order_rvs else (raw_note if has_note_url else None))
        is_valid_url = bool(drive_link and ("http://" in str(drive_link) or "https://" in str(drive_link) or "drive.google" in str(drive_link) or "docs.google" in str(drive_link)))

        time_anchor = order.status_changed_at or order.updated_at or order.created_at
        review_sub_time = order.review_submitted_at or latest_submitted_at or time_anchor
        f_sub = first_submitted_at or order.review_submitted_at or time_anchor
        l_sub = latest_submitted_at or order.review_submitted_at or time_anchor

        task_domain = order.work_domain or "standard"
        task_rate = order.custom_rate if order.custom_rate is not None else (
            duplicate_rate if task_domain == WORK_DOMAIN_DUPLICATE else standard_rate
        )

        submissions_by_order[order.id] = {
            "order_id": str(order.id),
            "order_version": order.version,
            "external_order_id": order.external_order_id,
            "product_name": order.product_name,
            "thumbnail_url": order.thumbnail_url,
            "designer_id": des_id_str,
            "designer_name": des_display_name,
            "designer_username": des_username,
            "designer_key": des_key,
            "current_state": order.state,
            "printerval_status": order.printerval_status,
            "drive_link": drive_link if is_valid_url else None,
            "placeholder_filled": is_valid_url,
            "status_changed_at": time_anchor,
            "review_submitted_at": review_sub_time,
            "first_submitted_at": f_sub,
            "latest_submitted_at": l_sub,
            "submission_count": max(1, len(cands)),
            "order_created_at": order.created_at,
            "notes_count": order_notes_count.get(order.id, 0),
            "is_paid": bool(order.is_paid),
            "paid_at": order.paid_at,
            "paid_by_id": str(order.paid_by_id) if order.paid_by_id else None,
            "work_domain": task_domain,
            "custom_rate": order.custom_rate,
            "rate": task_rate,
        }

    all_tasks = list(submissions_by_order.values())

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

    # Date filter: filter by task's submission timestamp (review_submitted_at / first_submitted_at / status_changed_at)
    if start_ts is not None or end_ts is not None:
        new_filtered = []
        for t in all_tasks:
            task_ts = get_task_submission_timestamp(t)
            if start_ts is not None and (task_ts is None or task_ts < start_ts):
                continue
            if end_ts is not None and (task_ts is None or task_ts > end_ts):
                continue
            new_filtered.append(t)
        filtered_tasks = new_filtered
    else:
        filtered_tasks = all_tasks


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
        if task.get("placeholder_filled") or task.get("is_paid"):
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

    # Global KPI counts (only credited tasks with placeholder_filled=True or is_paid=True)
    credited_tasks = [t for t in filtered_tasks if t.get("placeholder_filled") or t.get("is_paid")]
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
        raw_filter = designer_id.strip()
        matched_user = resolve_designer_user(raw_filter)
        if matched_user:
            # The modal always supplies this canonical ID.  Matching by name
            # fragments (e.g. "Anh" or "Trello") cross-credited orders between
            # different Designers, so this path must be identity-only.
            target_designer_id = str(matched_user.id).lower()
            tasks_to_render = [
                t for t in tasks_to_render
                if str(t.get("designer_id") or "").lower() == target_designer_id
                or str(t.get("designer_key") or "").lower() == target_designer_id
            ]
        else:
            # Keep compatibility for an older caller that may send an unknown
            # display identifier, but require an exact normalized match. Never
            # match individual name words or substrings.
            exact_targets = {raw_filter.lower(), normalize_text(raw_filter)}
            tasks_to_render = [
                t for t in tasks_to_render
                if str(t.get("designer_id") or "").lower().strip() in exact_targets
                or str(t.get("designer_key") or "").lower().strip() in exact_targets
                or str(t.get("designer_name") or "").lower().strip() in exact_targets
                or normalize_text(t.get("designer_name")) in exact_targets
                or str(t.get("designer_username") or "").lower().strip() in exact_targets
                or normalize_text(t.get("designer_username")) in exact_targets
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
        support_classified_count=sum(item.classified_tasks for item in support_summary),
        support_summary=support_summary,
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

    parsed_ids = []
    if payload.order_ids:
        for oid in payload.order_ids:
            try:
                parsed_ids.append(uuid.UUID(oid))
            except ValueError:
                pass

    if not parsed_ids and payload.designer_id:
        try:
            stats = get_finance_stats(
                request=Request({"type": "http"}),
                designer_id=payload.designer_id,
                is_paid=False,
                page=1,
                page_size=10000,
                user=user,
                db=db,
            )
            for task in stats.tasks:
                try:
                    parsed_ids.append(uuid.UUID(task.order_id))
                except ValueError:
                    pass
        except Exception:
            pass

    if not parsed_ids:
        return {"ok": True, "updated_count": 0}


    now_utc = datetime.now(UTC)
    orders = (
        db.query(Order)
        .filter(Order.id.in_(parsed_ids), Order.platform_id == platform_id)
        .order_by(Order.id)
        .with_for_update()
        .all()
    )
    for o in orders:
        require_expected_order_version(o, (payload.expected_versions or {}).get(o.id))
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
        from app.workers.telegram_tasks import (
            async_notify_designer_payment,
            safe_dispatch_telegram_task,
        )

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
    platform_id: uuid.UUID = Depends(get_current_platform_id),
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

    orders = (
        db.query(Order)
        .filter(Order.id.in_(parsed_ids), Order.platform_id == platform_id)
        .order_by(Order.id)
        .with_for_update()
        .all()
    )
    for o in orders:
        require_expected_order_version(o, (payload.expected_versions or {}).get(o.id))
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
    if user.role in (ROLE_DESIGNER, ROLE_DESIGNER_TRELLO, ROLE_SUPPORT):
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

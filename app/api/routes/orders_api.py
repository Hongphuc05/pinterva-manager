from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.adapters.db.models import Assignment, Order, Platform, PrintervalAssignmentRequest, ResultVersion, User, WorkflowEvent
from app.adapters.printerval import login_session
from app.adapters.printerval.api_adapter import PrintervalApiAdapter
from app.adapters.printerval.api_client import (
    PrintervalApiClient,
    PrintervalApiConfigurationError,
    PrintervalApiError,
)
from app.adapters.printerval.interface import ALL_JOB_TYPES
from app.api.deps import (
    DEFAULT_PLATFORM_ID,
    get_current_platform_id,
    get_current_user,
    get_db,
    require_role,
)
from app.application.crawl import DiscoverFailedError, refresh_order_detail, scan_orders_fast
from app.application.order_queries import (
    get_order_detail_for_user,
    get_order_history,
    list_orders_for_user,
)
from app.application.printerval_assignment_requests import (
    PRINTERVAL_STATUSES,
    PrintervalAssignmentValidationError,
    create_request,
)
from app.config import get_settings
from app.domain.models import OrderState

router = APIRouter()


class OrderSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    external_order_id: str
    state: str
    batch_id: uuid.UUID | None
    product_name: str | None = None
    sku: str | None = None
    thumbnail_url: str | None = None
    assigned_designer_name: str | None = None
    template_jobs: list[dict] | None = None
    deadline_at_ext: datetime | None = None
    created_at: datetime
    # Read-only mirror of Printerval's own site status — never written back to the
    # site from here (see app/application/status_sync.py).
    printerval_status: str | None = None
    printerval_status_synced_at: datetime | None = None
    note_outsource: str = ""
    previous_note_outsource: str | None = None
    fix_approved_by_admin: bool = False
    sku_image_url: str | None = None
    external_order_url: str | None = None
    source_files: list[dict] | None = None
    source_download_all_url: str | None = None
    printerval_designer: str | None = None
    printerval_assignment_lifecycle: str | None = None
    printerval_assignment_error: str | None = None


class OrdersListResponse(BaseModel):
    orders: list[OrderSummaryOut]


class ResultVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    drive_url: str
    version_marker: int
    submitted_at: datetime | None = None
    qc_feedback: str | None = None


class OrderDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    external_order_id: str
    state: str
    batch_id: uuid.UUID | None
    product_name: str | None
    thumbnail_url: str | None
    sku: str | None
    product_category: str | None
    product_variants: list[dict] | None
    has_template: bool
    multiple_design: bool
    double_sided: bool
    priority_label: str | None
    deadline_at_ext: datetime | None
    note_outsource: str
    previous_note_outsource: str | None = None
    fix_approved_by_admin: bool = False
    order_note: str
    custom_config: dict | None
    template_jobs: list[dict] | None = None
    assigned_designer_name: str | None = None
    assignment_id: uuid.UUID | None = None
    sub_status: str | None = None
    result_versions: list[ResultVersionOut] = []
    design_tool_url: str | None
    sku_image_url: str | None = None
    external_order_url: str | None = None
    source_files: list[dict] | None = None
    source_download_all_url: str | None = None
    printerval_designer: str | None = None
    printerval_status: str | None = None
    created_at: datetime



class WorkflowEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str | None = None
    created_at: datetime
    from_state: str | None = None
    to_state: str
    actor_id: str | None = None
    actor_name: str | None = None
    actor_role: str | None = None
    action: str | None = None
    description: str | None = None
    designer_name: str | None = None
    evidence: dict | None = None


class OrderHistoryItemOut(BaseModel):
    id: str
    created_at: datetime
    order_id: str
    external_order_id: str
    product_name: str | None = None
    thumbnail_url: str | None = None
    from_state: str | None = None
    to_state: str
    actor_id: str | None = None
    actor_name: str | None = None
    actor_role: str | None = None
    action: str | None = None
    description: str | None = None
    designer_name: str | None = None
    evidence: dict | None = None


class OrderHistoryListResponse(BaseModel):
    items: list[OrderHistoryItemOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class OrderDetailResponse(BaseModel):
    order: OrderDetailOut
    history: list[WorkflowEventOut]


class RefreshResponse(BaseModel):
    flash: str
    summary: dict | None = None


class SyncStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    is_running: bool
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_result: dict | None = None
    last_error: str | None = None


class RefreshRequest(BaseModel):
    # Mirrors Printerval's own filter bar (Loại design job). Only "Tất cả 2D & 3D" is
    # confirmed safe on the fast HTTP API path (docs/phase0-field-map.md §4); any other
    # value routes this crawl through the slower, DOM-verified Playwright fallback
    # instead of guessing an unconfirmed HTTP query value for it (a real past incident:
    # a wrong filter string silently returned 0 orders instead of erroring).
    job_type: str = ALL_JOB_TYPES
    printerval_status: str = "Waiting"
    printerval_designer: str | None = None
    # Plain "YYYY-MM-DD" from the date picker (filters on created_at) — live-confirmed
    # 2026-09-08 against the real site's own find endpoint (date_from/date_to,
    # "YYYY-MM-DD HH:MM:SS"). Only applies on the fast HTTP path (job_type == default).
    date_from: str | None = None
    date_to: str | None = None


class PrintervalLoginStatus(BaseModel):
    session_open: bool


class OrderStatesResponse(BaseModel):
    states: list[str]


class PrintervalOptionsResponse(BaseModel):
    designers: list[str]
    statuses: list[str]
    synced_at: datetime | None = None


class PrintervalAssignmentPayload(BaseModel):
    # Optional: a quick Printerval-only edit (e.g. from the read-only status mirror
    # tab) doesn't need to also assign this order to an internal designer — only the
    # site-side Designer/Status actually change then. When given, the internal
    # Assignment/state are updated too, same as before.
    designer_id: str | None = None
    printerval_designer: str
    printerval_status: str = "Doing"


class PrintervalAssignmentResponse(BaseModel):
    request_id: uuid.UUID
    lifecycle: str


class BulkPrintervalAssignmentPayload(BaseModel):
    order_ids: list[str]
    designer_id: str | None = None
    printerval_designer: str | None = None
    printerval_status: str = "Doing"


class BulkPrintervalAssignmentResponse(BaseModel):
    request_ids: list[uuid.UUID]
    queued_count: int


@router.get("/order-states", response_model=OrderStatesResponse)
def api_order_states(user: User = Depends(get_current_user)):
    return OrderStatesResponse(states=[s.value for s in OrderState])


@router.get("/orders", response_model=OrdersListResponse)
def api_orders_list(
    status_filter: str | None = Query(default=None, alias="status"),
    batch_id: str | None = None,
    designer_id: str | None = None,
    user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    orders = list_orders_for_user(
        db, user, status=status_filter, batch_id=batch_id, designer_id=designer_id, platform_id=platform_id
    )
    order_ids = [o.id for o in orders]
    assignments = (
        db.query(Assignment, User)
        .join(User, User.id == Assignment.designer_id)
        .filter(Assignment.order_id.in_(order_ids), Assignment.status == "approved")
        .all()
        if order_ids
        else []
    )
    designer_map = {a.order_id: u.full_name or u.username for a, u in assignments}
    requests = (
        db.query(PrintervalAssignmentRequest)
        .filter(PrintervalAssignmentRequest.order_id.in_(order_ids))
        .order_by(PrintervalAssignmentRequest.created_at.desc())
        .all()
        if order_ids
        else []
    )
    request_map = {}
    for request in requests:
        request_map.setdefault(request.order_id, request)

    out_list = []
    for o in orders:
        item = OrderSummaryOut.model_validate(o)
        item.assigned_designer_name = designer_map.get(o.id)
        latest_request = request_map.get(o.id)
        item.printerval_assignment_lifecycle = latest_request.lifecycle if latest_request else None
        if latest_request and latest_request.lifecycle in ("failed", "unknown_outcome"):
            item.printerval_assignment_error = (
                f"{latest_request.error_class}: {latest_request.error_message}"
                if latest_request.error_message
                else latest_request.error_class
            )
        out_list.append(item)

    return OrdersListResponse(orders=out_list)


# Declared before /orders/{order_id} — a literal path segment after a path-param
# route of the same method would otherwise never be reached (FastAPI/Starlette
# matches routes in declaration order; "sync-status" would be swallowed as order_id).
@router.get("/orders/sync-status", response_model=SyncStatusResponse)
def api_orders_sync_status(
    user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    from app.adapters.db.models import PlatformSyncState

    state = db.get(PlatformSyncState, platform_id)
    if state is None:
        return SyncStatusResponse(is_running=False)
    return SyncStatusResponse.model_validate(state)


@router.post("/orders/sync-status/run", response_model=SyncStatusResponse)
def api_orders_sync_status_run(
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    """Manual "refresh now" — syncs the current platform's order statuses and details
    immediately, then dispatches background job."""
    from app.application.status_sync import sync_platform_order_statuses
    platform = db.get(Platform, platform_id)
    if platform:
        sync_platform_order_statuses(db, platform)

    from app.workers.status_sync_tasks import sync_order_statuses

    sync_order_statuses.delay()
    return api_orders_sync_status(user=user, platform_id=platform_id, db=db)


class RefreshOrderDetailResponse(BaseModel):
    ok: bool
    message: str


@router.post("/orders/{order_id}/refresh-detail", response_model=RefreshOrderDetailResponse)
def api_refresh_order_detail(
    order_id: str,
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    """"Cập nhật toàn bộ" for one order from the "Trạng Thái Đơn" tab — re-fetches
    everything the crawl's one-time import would have captured (template, source
    files, images, deadline, product info...), for an order that's already past
    that point. import_claimed_orders only ever runs once per order (gated on state);
    this exists because the mother site can add/change a template *after* that (the
    exact scenario the operator flagged), and nothing else ever picks that up.
    Synchronous, same shape as /orders/refresh — a single order's detail fetch is
    normally sub-second on the fast HTTP path."""
    order = get_order_detail_for_user(db, user, order_id)
    if order is None or order.platform_id != platform_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found for active platform")
    platform = db.get(Platform, platform_id)
    if platform is None or not (platform.account_password or platform.session_cookie) or not platform.team_outsource:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Platform chưa có Session Cookie hoặc mật khẩu, hoặc chưa có Team Outsource Printerval.",
        )
    settings = get_settings()
    with PrintervalApiClient(
        base_url=settings.printerval_api_base_url,
        username=platform.account_username,
        password=platform.account_password,
        team_outsource=platform.team_outsource,
        session_cookie=platform.session_cookie,
    ) as api_client:
        adapter = PrintervalApiAdapter(api_client=api_client, download_images=True)
        result = refresh_order_detail(db, adapter, order)
    if not result["success"]:
        return RefreshOrderDetailResponse(
            ok=False,
            message=f"Không cập nhật được đơn {order.external_order_id} (lỗi ở bước {result['stage']}) — xem dead_letters.",
        )
    return RefreshOrderDetailResponse(ok=True, message=f"Đã cập nhật toàn bộ thông tin đơn {order.external_order_id}.")


@router.get("/orders/{order_id}/printerval-options", response_model=PrintervalOptionsResponse)
def api_printerval_options(
    order_id: str,
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    order = get_order_detail_for_user(db, user, order_id)
    if order is None or order.platform_id != platform_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found for active platform")
    platform = db.get(Platform, platform_id)
    if platform is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform not found")
    return PrintervalOptionsResponse(
        designers=platform.printerval_designer_options or [],
        statuses=platform.printerval_status_options or list(PRINTERVAL_STATUSES),
        synced_at=platform.printerval_options_synced_at,
    )


@router.post("/platforms/printerval-options/refresh", response_model=PrintervalOptionsResponse)
def api_refresh_printerval_options(
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    platform = db.get(Platform, platform_id)
    if platform is None or not (platform.account_password or platform.session_cookie) or not platform.team_outsource:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Platform needs a Printerval session cookie or password and team scope",
        )
    settings = get_settings()
    try:
        with PrintervalApiClient(
            base_url=settings.printerval_api_base_url,
            username=platform.account_username,
            password=platform.account_password,
            team_outsource=platform.team_outsource,
            session_cookie=platform.session_cookie,
        ) as client:
            designers = client.list_designer_options()
    except (PrintervalApiConfigurationError, PrintervalApiError) as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Could not load Printerval Designer options",
        ) from exc
    platform.printerval_designer_options = designers
    platform.printerval_status_options = list(PRINTERVAL_STATUSES)
    platform.printerval_options_synced_at = datetime.now(UTC)
    db.commit()
    return PrintervalOptionsResponse(
        designers=designers,
        statuses=platform.printerval_status_options,
        synced_at=platform.printerval_options_synced_at,
    )


@router.post(
    "/orders/{order_id}/printerval-assignment",
    response_model=PrintervalAssignmentResponse,
)
def api_printerval_assignment(
    order_id: str,
    payload: PrintervalAssignmentPayload,
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    order = get_order_detail_for_user(db, user, order_id)
    if order is None or order.platform_id != platform_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found for active platform")
    designer: User | None = None
    if payload.designer_id:
        try:
            designer = db.get(User, uuid.UUID(payload.designer_id))
        except ValueError:
            designer = None
        if designer is None or not designer.active:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Designer not found")
    if not payload.printerval_designer.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Printerval Designer is required")
    if payload.printerval_status not in PRINTERVAL_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Printerval status")
    if designer is not None:
        assignment = db.query(Assignment).filter(Assignment.order_id == order.id).one_or_none()
        if assignment is None:
            assignment = Assignment(order_id=order.id, designer_id=designer.id, status="approved")
            db.add(assignment)
        else:
            assignment.designer_id = designer.id
            assignment.status = "approved"
        order.state = OrderState.WAITING.value
    try:
        request = create_request(
            db,
            order=order,
            # A pure Printerval-only edit (no internal designer chosen) still needs an
            # internal_designer_id for the audit trail (NOT NULL) — the acting admin
            # is the correct "who did this", not a guessed/forced designer pick.
            internal_designer=designer or user,
            platform_id=platform_id,
            designer_option=payload.printerval_designer,
            target_status=payload.printerval_status,
        )
    except PrintervalAssignmentValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    from app.workers.assignment_sync_tasks import sync_printerval_assignment_request

    sync_printerval_assignment_request.delay(str(request.id))
    return PrintervalAssignmentResponse(request_id=request.id, lifecycle=request.lifecycle)


@router.post(
    "/orders/bulk-printerval-assignment",
    response_model=BulkPrintervalAssignmentResponse,
)
def api_bulk_printerval_assignment(
    payload: BulkPrintervalAssignmentPayload,
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    if not payload.order_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Danh sách đơn hàng không được để trống")
    designer: User | None = None
    if payload.designer_id:
        try:
            designer_id = uuid.UUID(payload.designer_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid designer ID") from exc
        designer = db.get(User, designer_id)
        if designer is None or not designer.active:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Designer not found")

    has_printerval_designer = bool(payload.printerval_designer and payload.printerval_designer.strip())
    if payload.printerval_status not in PRINTERVAL_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Printerval status")
    try:
        order_ids = [uuid.UUID(order_id) for order_id in payload.order_ids]
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid order ID") from exc
    if len(set(order_ids)) != len(order_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Danh sách đơn hàng bị trùng")
    orders = db.query(Order).filter(Order.id.in_(order_ids)).all()
    if len(orders) != len(order_ids) or any(order.platform_id != platform_id for order in orders):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Mỗi đơn phải thuộc platform đang chọn",
        )

    # If Printerval Designer is provided, use the full request lifecycle
    if has_printerval_designer:
        requests: list[PrintervalAssignmentRequest] = []
        for order in orders:
            if designer is not None:
                assignment = db.query(Assignment).filter(Assignment.order_id == order.id).one_or_none()
                if assignment is None:
                    db.add(Assignment(order_id=order.id, designer_id=designer.id, status="approved"))
                else:
                    assignment.designer_id = designer.id
                    assignment.status = "approved"
                order.state = OrderState.WAITING.value
            try:
                requests.append(
                    create_request(
                        db,
                        order=order,
                        internal_designer=designer or user,
                        platform_id=platform_id,
                        designer_option=payload.printerval_designer.strip(),
                        target_status=payload.printerval_status,
                    )
                )
            except PrintervalAssignmentValidationError as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

        from app.workers.assignment_sync_tasks import sync_printerval_assignment_request

        for request in requests:
            sync_printerval_assignment_request.delay(str(request.id))
        return BulkPrintervalAssignmentResponse(
            request_ids=[request.id for request in requests],
            queued_count=len(requests),
        )

    # Status-only update (or with optional internal designer change)
    from app.workers.assignment_sync_tasks import sync_order_review_to_printerval_task

    status_state_map = {
        "Doing": OrderState.IN_PROGRESS,
        "Review": OrderState.QC_PENDING,
        "Fix": OrderState.REVISION,
        "Done": OrderState.DONE,
        "Waiting": OrderState.WAITING,
        "Skipped": OrderState.DONE,
    }
    mapped_state = status_state_map.get(payload.printerval_status)

    for order in orders:
        if designer is not None:
            assignment = db.query(Assignment).filter(Assignment.order_id == order.id).one_or_none()
            if assignment is None:
                db.add(Assignment(order_id=order.id, designer_id=designer.id, status="approved"))
            else:
                assignment.designer_id = designer.id
                assignment.status = "approved"
        if mapped_state:
            order.state = mapped_state.value
        order.printerval_status = payload.printerval_status.lower()
        order.printerval_status_synced_at = datetime.now(UTC)

        # Trigger background task to push status to Printerval via direct HTTP API
        sync_order_review_to_printerval_task.delay(str(order.id), None, payload.printerval_status)

    db.commit()
    return BulkPrintervalAssignmentResponse(
        request_ids=[],
        queued_count=len(orders),
    )


@router.get("/orders/{order_id}", response_model=OrderDetailResponse)
def api_order_detail(
    order_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    order = get_order_detail_for_user(db, user, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    history = get_order_history(db, order_id)

    assignment = (
        db.query(Assignment, User)
        .join(User, User.id == Assignment.designer_id)
        .filter(Assignment.order_id == order.id, Assignment.status != "cancelled")
        .first()
    )
    order_out = OrderDetailOut.model_validate(order)
    if assignment:
        asgn_obj, des_user = assignment
        order_out.assigned_designer_name = des_user.full_name or des_user.username
        order_out.assignment_id = asgn_obj.id
        order_out.sub_status = asgn_obj.sub_status
        versions = (
            db.query(ResultVersion)
            .filter(ResultVersion.assignment_id == asgn_obj.id)
            .order_by(ResultVersion.version_marker.asc())
            .all()
        )
        order_out.result_versions = [
            ResultVersionOut.model_validate(v) for v in versions
        ]


    actor_ids = {e.actor_id for e in history if e.actor_id}
    actors_map = {}
    if actor_ids:
        users = db.query(User).filter(User.id.in_(actor_ids)).all()
        actors_map = {u.id: (u.full_name or u.username, u.role) for u in users}

    history_out = []
    for e in history:
        actor_info = actors_map.get(e.actor_id)
        actor_name = (e.evidence or {}).get("actor_name") or (actor_info[0] if actor_info else None)
        actor_role = (e.evidence or {}).get("actor_role") or (actor_info[1] if actor_info else None)
        action = (e.evidence or {}).get("action")
        designer_name = (e.evidence or {}).get("designer_name")
        description = (e.evidence or {}).get("description")

        if not description:
            from_st = e.from_state or "Mới"
            to_st = e.to_state
            if action == "ASSIGN":
                description = f"{actor_name or 'Admin'} phân công đơn hàng cho {designer_name or 'Designer'}"
            else:
                actor_label = f" ({actor_name})" if actor_name else ""
                description = f"Chuyển trạng thái từ {from_st} sang {to_st}{actor_label}"

        history_out.append(
            WorkflowEventOut(
                id=str(e.id),
                created_at=e.created_at,
                from_state=e.from_state,
                to_state=e.to_state,
                actor_id=str(e.actor_id) if e.actor_id else None,
                actor_name=actor_name,
                actor_role=actor_role,
                action=action,
                description=description,
                designer_name=designer_name,
                evidence=e.evidence,
            )
        )

    return OrderDetailResponse(
        order=order_out,
        history=history_out,
    )


@router.post("/orders/refresh", response_model=RefreshResponse)
def api_orders_refresh(
    payload: RefreshRequest = RefreshRequest(),
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    try:
        settings = get_settings()
        platform = db.get(Platform, platform_id)
        if (
            platform is None
            or not platform.account_username
            or not (platform.account_password or platform.session_cookie)
            or not platform.team_outsource
        ):
            return RefreshResponse(
                flash="Platform chưa có Session Cookie hoặc mật khẩu, hoặc chưa có Team Outsource Printerval."
            )
        crawl_username = platform.account_username
        crawl_password = platform.account_password
        crawl_team_outsource = platform.team_outsource

        with PrintervalApiClient(
            base_url=settings.printerval_api_base_url,
            username=crawl_username,
            password=crawl_password,
            team_outsource=crawl_team_outsource,
            session_cookie=platform.session_cookie,
        ) as api_client:
            adapter = PrintervalApiAdapter(api_client=api_client, download_images=False)
            summary = scan_orders_fast(
                db,
                adapter,
                platform_id=platform_id,
                status=payload.printerval_status,
                designer=payload.printerval_designer,
                job_type=payload.job_type,
                date_from=f"{payload.date_from} 00:00:00" if payload.date_from else None,
                date_to=f"{payload.date_to} 23:59:59" if payload.date_to else None,
            )
        flash = (
            f"Đã quét nhanh qua API ({crawl_username}): {summary['scanned']} đơn khớp bộ lọc, "
            f"{summary['added']} đơn mới"
        )
        flash += "."
        return RefreshResponse(flash=flash, summary=summary)
    except DiscoverFailedError:
        db.rollback()
        flash = (
            f"Crawl thất bại khi tìm đơn mới cho tài khoản '{crawl_username}' — "
            "có thể tài khoản/mật khẩu chưa đúng hoặc team_outsource không khớp. "
            "Xem bảng dead_letters (source=crawl.discover_waiting_orders) để biết chi tiết lỗi."
        )
        return RefreshResponse(flash=flash)
    except Exception as exc:
        db.rollback()
        flash = f"Crawl thất bại ({crawl_username}): {str(exc)}"
        return RefreshResponse(flash=flash)


@router.get("/printerval-login/status", response_model=PrintervalLoginStatus)
def api_printerval_login_status(user: User = Depends(require_role("admin"))):
    return PrintervalLoginStatus(session_open=login_session.is_session_open())


@router.post("/printerval-login/start", response_model=PrintervalLoginStatus)
def api_printerval_login_start(user: User = Depends(require_role("admin"))):
    login_session.start_session()
    return PrintervalLoginStatus(session_open=True)


@router.post("/printerval-login/done", response_model=PrintervalLoginStatus)
def api_printerval_login_done(user: User = Depends(require_role("admin"))):
    login_session.close_session()
    return PrintervalLoginStatus(session_open=False)


class AssignOrderRequest(BaseModel):
    designer_id: str


def _trigger_printerval_assignment_sync(order: Order, designer: User) -> str:
    """Enqueues the background job that mirrors this assignment onto Printerval (set
    Designer + status=Doing) — never runs inline (Playwright is slow), never touches
    our own state machine (claude.md §5 — the designer's own "Bắt đầu" action still
    owns ASSIGNED -> IN_PROGRESS). Returns a short status message for the response,
    it does not wait for the sync itself to finish."""
    if not designer.printerval_designer_option:
        return (
            f"Đã phân công nội bộ cho {designer.full_name or designer.username}. "
            "Designer này CHƯA có tên đăng ký trên Printerval (xem Quản Lý Tài Khoản) "
            "nên KHÔNG đồng bộ sang Printerval — chỉ lưu nội bộ."
        )
    from app.workers.assignment_sync_tasks import sync_assignment_to_printerval_task

    sync_assignment_to_printerval_task.delay(str(order.id), str(designer.id))
    return "Đã phân công nội bộ, đang đồng bộ sang Printerval trong nền (Doing + đổi Designer)."


@router.post("/orders/{order_id}/assign")
def api_assign_order(
    order_id: str,
    payload: AssignOrderRequest,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    order = get_order_detail_for_user(db, user, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    try:
        designer_uuid = uuid.UUID(payload.designer_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid designer ID")

    designer = db.get(User, designer_uuid)
    if designer is None or not designer.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Designer not found or inactive")

    # Update or create assignment
    existing_assignment = (
        db.query(Assignment)
        .filter(Assignment.order_id == order.id)
        .one_or_none()
    )
    old_designer_name = None
    if existing_assignment:
        if existing_assignment.designer_id:
            old_des = db.get(User, existing_assignment.designer_id)
            if old_des:
                old_designer_name = old_des.full_name or old_des.username
        existing_assignment.designer_id = designer.id
        existing_assignment.status = "approved"
    else:
        new_assignment = Assignment(
            order_id=order.id,
            designer_id=designer.id,
            status="approved",
        )
        db.add(new_assignment)

    old_state = order.state
    order.state = OrderState.WAITING.value

    des_name = designer.full_name or designer.username
    admin_name = user.full_name or user.username
    is_reassign = existing_assignment is not None and old_designer_name and old_designer_name != des_name
    action_type = "REASSIGN" if is_reassign else "ASSIGN"
    if is_reassign:
        desc = f"Admin {admin_name} phân công lại từ {old_designer_name} sang {des_name} (chuyển về Waiting)"
    else:
        desc = f"Admin {admin_name} phân công đơn cho {des_name} (chuyển về Waiting)"

    event = WorkflowEvent(
        order_id=order.id,
        from_state=old_state,
        to_state=OrderState.WAITING.value,
        actor_id=user.id,
        evidence={
            "action": action_type,
            "actor_name": admin_name,
            "actor_role": user.role,
            "designer_id": str(designer.id),
            "designer_name": des_name,
            "old_designer_name": old_designer_name,
            "description": desc,
        },
    )
    db.add(event)
    db.commit()

    synced_message = _trigger_printerval_assignment_sync(order, designer)
    return {
        "ok": True,
        "assigned_designer_name": designer.full_name or designer.username,
        "printerval_sync_message": synced_message,
    }


class BulkAssignOrdersRequest(BaseModel):
    order_ids: list[str]
    designer_id: str


@router.post("/orders/bulk-assign")
def api_bulk_assign_orders(
    payload: BulkAssignOrdersRequest,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if not payload.order_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Danh sách đơn hàng không được để trống")

    try:
        designer_uuid = uuid.UUID(payload.designer_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid designer ID")

    designer = db.get(User, designer_uuid)
    if designer is None or not designer.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Designer not found or inactive")

    # Fetch orders (accepting either internal UUID or external_order_id)
    valid_uuids = []
    for oid in payload.order_ids:
        try:
            valid_uuids.append(uuid.UUID(oid))
        except ValueError:
            pass

    if valid_uuids:
        orders = db.query(Order).filter(Order.id.in_(valid_uuids)).all()
    else:
        orders = db.query(Order).filter(Order.external_order_id.in_(payload.order_ids)).all()

    if not orders:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng phù hợp")

    updated_count = 0
    des_name = designer.full_name or designer.username
    admin_name = user.full_name or user.username

    for order in orders:
        existing_assignment = (
            db.query(Assignment)
            .filter(Assignment.order_id == order.id)
            .one_or_none()
        )
        old_designer_name = None
        if existing_assignment:
            if existing_assignment.designer_id:
                old_des = db.get(User, existing_assignment.designer_id)
                if old_des:
                    old_designer_name = old_des.full_name or old_des.username
            existing_assignment.designer_id = designer.id
            existing_assignment.status = "approved"
        else:
            new_assignment = Assignment(
                order_id=order.id,
                designer_id=designer.id,
                status="approved",
            )
            db.add(new_assignment)

        old_state = order.state
        order.state = OrderState.WAITING.value
        updated_count += 1

        is_reassign = existing_assignment is not None and old_designer_name and old_designer_name != des_name
        action_type = "REASSIGN" if is_reassign else "ASSIGN"
        if is_reassign:
            desc = f"Admin {admin_name} phân công lại từ {old_designer_name} sang {des_name} (chuyển về Waiting)"
        else:
            desc = f"Admin {admin_name} phân công hàng loạt cho {des_name} (chuyển về Waiting)"

        event = WorkflowEvent(
            order_id=order.id,
            from_state=old_state,
            to_state=OrderState.WAITING.value,
            actor_id=user.id,
            evidence={
                "action": action_type,
                "actor_name": admin_name,
                "actor_role": user.role,
                "designer_id": str(designer.id),
                "designer_name": des_name,
                "old_designer_name": old_designer_name,
                "description": desc,
            },
        )
        db.add(event)

    db.commit()

    message = f"Đã phân công thành công {updated_count} đơn hàng cho {designer.full_name or designer.username}."
    if designer.printerval_designer_option:
        for order in orders:
            _trigger_printerval_assignment_sync(order, designer)
        message += " Đang đồng bộ sang Printerval trong nền (Doing + đổi Designer)."
    else:
        message += (
            " Designer này CHƯA có tên đăng ký trên Printerval nên KHÔNG đồng bộ sang site — chỉ lưu nội bộ."
        )
    return {
        "ok": True,
        "assigned_count": updated_count,
        "designer_name": designer.full_name or designer.username,
        "message": message,
    }


class UpdatePrintervalCredentialsRequest(BaseModel):
    username: str
    password: str | None = None
    team_outsource: str | None = None
    session_cookie: str | None = None


@router.post("/orders/printerval-credentials")
def api_update_printerval_credentials(
    payload: UpdatePrintervalCredentialsRequest,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    from app.adapters.db.models import Platform

    username_clean = payload.username.strip()
    password_clean = payload.password.strip() if payload.password else None
    team_outsource_clean = payload.team_outsource.strip() if payload.team_outsource else None
    session_cookie_clean = payload.session_cookie.strip() if payload.session_cookie else None

    # Verify these credentials actually work against the real site BEFORE saving
    settings = get_settings()
    probe_client = PrintervalApiClient(
        base_url=settings.printerval_api_base_url,
        username=username_clean,
        password=password_clean,
        team_outsource=team_outsource_clean,
        session_cookie=session_cookie_clean,
    )
    try:
        probe_client.login()
    except PrintervalApiConfigurationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except PrintervalApiError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Xác thực Printerval cho tài khoản '{username_clean}' không thành công: {exc}. "
            "Kiểm tra lại Session Cookie hoặc username/mật khẩu.",
        )
    try:
        probe_client.discover_waiting_page(page_size=1)
    except PrintervalApiError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Xác thực thành công nhưng Team Outsource có vẻ không đúng: {exc}",
        )
    finally:
        probe_client.close()

    platform = (
        db.query(Platform)
        .filter(Platform.account_username == username_clean)
        .first()
    )
    if not platform:
        platform = Platform(
            name=f"Acc Mẹ: {username_clean}",
            account_username=username_clean,
            account_password=password_clean,
            team_outsource=team_outsource_clean,
            session_cookie=session_cookie_clean,
            is_active=True,
        )
        db.add(platform)
    else:
        if password_clean:
            platform.account_password = password_clean
        if team_outsource_clean:
            platform.team_outsource = team_outsource_clean
        if session_cookie_clean:
            platform.session_cookie = session_cookie_clean
        platform.is_active = True

    db.commit()
    db.refresh(platform)

    return {
        "ok": True,
        "platform_id": str(platform.id),
        "platform_name": platform.name,
        "account_username": platform.account_username,
        "message": f"Đã đăng nhập tài khoản Printerval thành công: {username_clean}",
    }


class UpdateOrderStateRequest(BaseModel):
    state: str
    drive_url: str | None = None
    note_outsource: str | None = None


@router.patch("/orders/{order_id}/state")
def api_update_order_state(
    order_id: str,
    payload: UpdateOrderStateRequest,
    user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    order = None
    try:
        order_uuid = uuid.UUID(order_id)
        order = db.get(Order, order_uuid)
    except ValueError:
        pass
    if order is None:
        order = db.query(Order).filter(Order.external_order_id == order_id).first()

    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")

    raw_state = payload.state.strip().upper()
    state_mapping = {
        "WAITING": OrderState.WAITING,
        "ASSIGNED": OrderState.WAITING,
        "DOING": OrderState.IN_PROGRESS,
        "IN_PROGRESS": OrderState.IN_PROGRESS,
        "REVIEW": OrderState.QC_PENDING,
        "QC_PENDING": OrderState.QC_PENDING,
        "FIX": OrderState.REVISION,
        "REVISION": OrderState.REVISION,
        "DONE": OrderState.DONE,
    }
    if raw_state not in state_mapping:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Trạng thái không hợp lệ: {payload.state}. Chỉ chấp nhận Waiting, Doing, Review, Fix, Done.",
        )
    target_state = state_mapping[raw_state]

    if user.role == "designer":
        if target_state not in (OrderState.WAITING, OrderState.IN_PROGRESS, OrderState.QC_PENDING):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Designer chỉ có quyền chuyển đơn sang Waiting, Doing (Đang làm) hoặc Review (Chờ duyệt). Chỉ Admin mới có quyền duyệt Done hoặc yêu cầu Fix.",
            )
        is_assigned = (
            db.query(Assignment)
            .filter(
                Assignment.order_id == order.id,
                Assignment.designer_id == user.id,
                Assignment.status != "cancelled",
            )
            .first()
            is not None
        )
        is_printerval_assigned = (
            bool(user.printerval_designer_option and order.printerval_designer == user.printerval_designer_option)
            or bool(user.full_name and order.printerval_designer == user.full_name)
        )
        if not (is_assigned or is_printerval_assigned):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Bạn chỉ có thể cập nhật trạng thái các đơn hàng được phân công cho bạn.",
            )

    old_state = order.state
    order.state = target_state.value

    submitted_link = (payload.drive_url or "").strip()
    submitted_note = (payload.note_outsource or "").strip()
    if submitted_link:
        order.note_outsource = submitted_link
    elif submitted_note:
        order.note_outsource = submitted_note

    actor_name = user.full_name or user.username
    des_name = None
    curr_assignment = (
        db.query(Assignment)
        .filter(Assignment.order_id == order.id, Assignment.status != "cancelled")
        .first()
    )
    if curr_assignment and curr_assignment.designer_id:
        des_user = db.get(User, curr_assignment.designer_id)
        if des_user:
            des_name = des_user.full_name or des_user.username
    if not des_name and order.printerval_designer:
        des_name = order.printerval_designer

    # Record submitted version if drive link provided
    if submitted_link and curr_assignment:
        v_count = db.query(ResultVersion).filter(ResultVersion.assignment_id == curr_assignment.id).count()
        rv = ResultVersion(
            assignment_id=curr_assignment.id,
            drive_url=submitted_link,
            version_marker=v_count + 1,
            submitted_at=datetime.now(UTC),
            validated=True,
        )
        db.add(rv)

    if target_state == OrderState.IN_PROGRESS:
        if old_state in (OrderState.QC_PENDING.value, "REVIEW"):
            action_type = "REVERT_TO_DOING"
            desc = f"{'Designer ' + actor_name if user.role == 'designer' else actor_name} chuyển lại về Doing (Đang làm) để chỉnh sửa bài"
        else:
            action_type = "START_DOING"
            desc = f"{'Designer ' + actor_name if user.role == 'designer' else actor_name} bắt đầu làm thiết kế (Doing)"
    elif target_state == OrderState.QC_PENDING:
        action_type = "SUBMIT_REVIEW"
        desc = f"{'Designer ' + actor_name if user.role == 'designer' else actor_name} nộp bài và chuyển sang Review (Chờ duyệt)"
        order.fix_approved_by_admin = False
        # Sync Review status & Note outsource to Printerval
        try:
            from app.workers.assignment_sync_tasks import sync_order_review_to_printerval_task
            sync_order_review_to_printerval_task.delay(str(order.id), order.note_outsource, "Review")
        except Exception:
            pass
    elif target_state == OrderState.REVISION:
        action_type = "REQUEST_FIX"
        desc = f"{'Admin ' + actor_name if user.role == 'admin' else actor_name} kiểm tra bài và yêu cầu sửa lại (Fix)"
        order.fix_approved_by_admin = False
    elif target_state == OrderState.DONE:
        action_type = "APPROVE_DONE"
        desc = f"{'Admin ' + actor_name if user.role == 'admin' else actor_name} kiểm tra và duyệt hoàn thành đơn hàng (Done)"
    elif target_state == OrderState.WAITING:
        action_type = "SET_WAITING"
        desc = f"{actor_name} chuyển trạng thái đơn về Waiting (Chờ làm)"
    else:
        action_type = "CHANGE_STATE"
        desc = f"{actor_name} chuyển trạng thái từ {old_state or 'Mới'} sang {target_state.value}"

    evidence_payload = {
        "action": action_type,
        "actor_name": actor_name,
        "actor_role": user.role,
        "designer_name": des_name,
        "description": desc,
        "source": "status_update",
    }
    if submitted_link:
        evidence_payload["drive_link"] = submitted_link
    elif order.note_outsource:
        evidence_payload["drive_link"] = order.note_outsource

    event = WorkflowEvent(
        order_id=order.id,
        from_state=old_state,
        to_state=target_state.value,
        actor_id=user.id,
        evidence=evidence_payload,
    )
    db.add(event)
    db.commit()
    db.refresh(order)

    return {
        "ok": True,
        "order_id": str(order.id),
        "external_order_id": order.external_order_id,
        "state": order.state,
        "note_outsource": order.note_outsource,
        "message": f"Đã chuyển trạng thái đơn {order.external_order_id} sang {target_state.value}",
    }


class ApproveFixRequest(BaseModel):
    note_outsource: str | None = None


@router.post("/orders/{order_id}/approve-fix")
def api_approve_fix(
    order_id: str,
    payload: ApproveFixRequest,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    order = None
    try:
        order_uuid = uuid.UUID(order_id)
        order = db.get(Order, order_uuid)
    except ValueError:
        pass
    if order is None:
        order = db.query(Order).filter(Order.external_order_id == order_id).first()

    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")

    if payload.note_outsource is not None:
        order.note_outsource = payload.note_outsource.strip()

    order.state = OrderState.REVISION.value
    order.fix_approved_by_admin = True

    admin_name = user.full_name or user.username
    event = WorkflowEvent(
        order_id=order.id,
        from_state=OrderState.REVISION.value,
        to_state=OrderState.REVISION.value,
        actor_id=user.id,
        evidence={
            "action": "APPROVE_FIX_FOR_DESIGNER",
            "actor_name": admin_name,
            "actor_role": user.role,
            "description": f"Admin {admin_name} check & duyệt note sửa cho Designer: {order.note_outsource or 'Không có note'}",
            "note_outsource": order.note_outsource,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(order)

    return {
        "ok": True,
        "order_id": str(order.id),
        "external_order_id": order.external_order_id,
        "fix_approved_by_admin": True,
        "note_outsource": order.note_outsource,
        "message": "Đã check & duyệt và gửi yêu cầu sửa bài xuống cho Designer.",
    }


class RejectFixRequest(BaseModel):
    note_outsource: str | None = None


@router.post("/orders/{order_id}/reject-fix-to-review")
def api_reject_fix_to_review(
    order_id: str,
    payload: RejectFixRequest,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    order = None
    try:
        order_uuid = uuid.UUID(order_id)
        order = db.get(Order, order_uuid)
    except ValueError:
        pass
    if order is None:
        order = db.query(Order).filter(Order.external_order_id == order_id).first()

    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")

    order.previous_note_outsource = order.note_outsource
    if payload.note_outsource is not None:
        order.note_outsource = payload.note_outsource.strip()

    old_state = order.state
    order.state = OrderState.QC_PENDING.value
    order.fix_approved_by_admin = False

    admin_name = user.full_name or user.username
    event = WorkflowEvent(
        order_id=order.id,
        from_state=old_state,
        to_state=OrderState.QC_PENDING.value,
        actor_id=user.id,
        evidence={
            "action": "REJECT_FIX_TO_REVIEW",
            "actor_name": admin_name,
            "actor_role": user.role,
            "description": f"Admin {admin_name} hủy Fix, chỉnh lại note outsource và trả về Review trên Printerval",
            "note_outsource": order.note_outsource,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(order)

    # Sync to Printerval in background
    try:
        from app.workers.assignment_sync_tasks import sync_order_review_to_printerval_task
        sync_order_review_to_printerval_task.delay(str(order.id), order.note_outsource, "Review")
    except Exception:
        pass

    return {
        "ok": True,
        "order_id": str(order.id),
        "external_order_id": order.external_order_id,
        "state": order.state,
        "note_outsource": order.note_outsource,
        "message": "Đã hủy Fix, cập nhật note outsource và chuyển lại trạng thái Review trên Printerval.",
    }


class SyncPrintervalStatusPayload(BaseModel):
    order_ids: list[str] | None = None
    state: str | None = None


@router.post("/orders/sync-printerval-status")
def api_sync_printerval_status(
    payload: SyncPrintervalStatusPayload,
    user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    from app.adapters.printerval.api_client import PrintervalApiClient
    from app.application.status_sync import _status_guess_order

    platform = db.get(Platform, platform_id)
    if platform is None or not (platform.account_username and (platform.account_password or platform.session_cookie)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Chưa cấu hình tài khoản hoặc cookie Printerval cho platform hiện tại.",
        )

    # Build query for target orders
    query = db.query(Order).filter(Order.platform_id == platform_id)
    if user.role == "designer":
        asgn_order_ids = (
            db.query(Assignment.order_id)
            .filter(Assignment.designer_id == user.id, Assignment.status != "cancelled")
            .subquery()
        )
        query = query.filter(
            or_(
                Order.id.in_(asgn_order_ids),
                Order.printerval_designer == user.printerval_designer_option,
                Order.printerval_designer == user.full_name,
            )
        )

    if payload.order_ids:
        raw_ids = [s.strip() for s in payload.order_ids if s.strip()]
        u_ids = []
        ext_ids = []
        for rid in raw_ids:
            try:
                u_ids.append(uuid.UUID(rid))
            except ValueError:
                ext_ids.append(rid)
        query = query.filter(or_(Order.id.in_(u_ids), Order.external_order_id.in_(ext_ids)))
    elif payload.state:
        st = payload.state.strip().upper()
        if st in ("REVIEW", "QC_PENDING"):
            query = query.filter(Order.state == OrderState.QC_PENDING.value)
        elif st in ("FIX", "REVISION"):
            query = query.filter(Order.state == OrderState.REVISION.value)
        elif st in ("DOING", "IN_PROGRESS"):
            query = query.filter(Order.state == OrderState.IN_PROGRESS.value)
        elif st in ("WAITING", "ASSIGNED"):
            query = query.filter(Order.state.in_([OrderState.WAITING.value, "ASSIGNED"]))
        elif st == "TODO":
            query = query.filter(
                or_(
                    Order.state.in_([OrderState.WAITING.value, "ASSIGNED"]),
                    (Order.state.in_([OrderState.REVISION.value, "FIX"]) & (Order.fix_approved_by_admin == True)),
                )
            )

    orders = query.all()
    if not orders:
        return {"ok": True, "checked_count": 0, "updated_count": 0, "message": "Không có đơn hàng nào cần kiểm tra."}

    client = PrintervalApiClient(
        base_url="https://printerval.com",
        username=platform.account_username,
        password=platform.account_password,
        team_outsource=platform.team_outsource,
        session_cookie=platform.session_cookie,
    )
    updated_count = 0
    now_utc = datetime.now(UTC)
    try:
        for o in orders:
            try:
                row = client.find_order(o.external_order_id, statuses=_status_guess_order(o.printerval_status))
            except Exception:
                continue
            if row is None:
                continue

            found_status = row.get("status")
            attributes = row.get("attributes") or {}
            found_outsource_note = str(attributes.get("outsource_note") or row.get("note") or "").strip()

            norm_status = (found_status or "").upper()
            state_changed = False
            old_st = o.state

            # If Printerval returns Done -> Done
            if norm_status == "DONE" and o.state != OrderState.DONE.value:
                o.state = OrderState.DONE.value
                state_changed = True
                event = WorkflowEvent(
                    order_id=o.id,
                    from_state=old_st,
                    to_state=OrderState.DONE.value,
                    actor_id=user.id,
                    evidence={
                        "action": "APPROVE_DONE",
                        "actor_name": "Printerval",
                        "description": "Printerval đã duyệt hoàn thành đơn hàng (Done)",
                    },
                )
                db.add(event)

            # If Printerval returns Fix -> Fix (needs Admin review)
            elif norm_status == "FIX" and o.state != OrderState.REVISION.value:
                o.state = OrderState.REVISION.value
                o.previous_note_outsource = o.note_outsource
                if found_outsource_note:
                    o.note_outsource = found_outsource_note
                o.fix_approved_by_admin = False
                state_changed = True
                event = WorkflowEvent(
                    order_id=o.id,
                    from_state=old_st,
                    to_state=OrderState.REVISION.value,
                    actor_id=user.id,
                    evidence={
                        "action": "REQUEST_FIX",
                        "actor_name": "Printerval",
                        "description": f"Printerval trả về Fix với note: {found_outsource_note or 'Không có note'}",
                        "note_outsource": found_outsource_note,
                    },
                )
                db.add(event)

            elif found_outsource_note and found_outsource_note != o.note_outsource:
                if norm_status == "FIX":
                    o.previous_note_outsource = o.note_outsource
                    o.note_outsource = found_outsource_note
                    updated_count += 1
                elif not o.note_outsource:
                    o.note_outsource = found_outsource_note
                    updated_count += 1

            if found_status and found_status.lower() != o.printerval_status:
                o.printerval_status = found_status.lower()
                o.printerval_status_synced_at = now_utc
                updated_count += 1
            elif state_changed:
                o.printerval_status_synced_at = now_utc
                updated_count += 1

        db.commit()
    finally:
        client.close()

    return {
        "ok": True,
        "checked_count": len(orders),
        "updated_count": updated_count,
        "message": f"Đã kiểm tra {len(orders)} đơn hàng từ Printerval, cập nhật {updated_count} thay đổi.",
    }


class DesignerWorkloadOrderOut(BaseModel):
    id: str
    external_order_id: str
    state: str
    thumbnail_url: str | None = None
    deadline_at_ext: str | None = None
    product_name: str | None = None
    printerval_designer: str | None = None
    note_outsource: str = ""
    previous_note_outsource: str | None = None
    fix_approved_by_admin: bool = False


class DesignerWorkloadOut(BaseModel):
    id: str
    username: str
    full_name: str
    printerval_designer_option: str | None = None
    total_orders: int
    waiting_count: int = 0
    doing_count: int
    review_count: int
    fix_count: int
    done_count: int
    orders: list[DesignerWorkloadOrderOut]


@router.get("/designers/workload", response_model=list[DesignerWorkloadOut])
def api_designers_workload(
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    designers = (
        db.query(User)
        .filter(
            User.role == "designer",
            User.active == True,
            (User.platform_id == platform_id) | (User.platform_id.is_(None)),
        )
        .order_by(User.full_name)
        .all()
    )

    platform_orders = (
        db.query(Order)
        .filter(Order.platform_id == platform_id)
        .order_by(Order.created_at.desc())
        .all()
    )

    assignments = (
        db.query(Assignment)
        .filter(Assignment.status == "approved")
        .all()
    )
    order_designer_assignment = {a.order_id: a.designer_id for a in assignments}

    results = []
    for des in designers:
        des_orders = []
        for o in platform_orders:
            assigned_des_id = order_designer_assignment.get(o.id)
            is_match = (
                (assigned_des_id == des.id)
                or (des.printerval_designer_option and o.printerval_designer == des.printerval_designer_option)
                or (des.full_name and o.printerval_designer == des.full_name)
            )
            if is_match:
                des_orders.append(o)

        waiting_count = sum(1 for o in des_orders if o.state in ("WAITING", "OPEN"))
        doing_count = sum(1 for o in des_orders if o.state in ("IN_PROGRESS", "ASSIGNED") and o.state != "WAITING")
        review_count = sum(1 for o in des_orders if o.state in ("QC_PENDING", "RESULT_SUBMITTED", "SUBMITTING_TO_SITE"))
        fix_count = sum(1 for o in des_orders if o.state in ("REVISION", "REVISION_REQUESTED"))
        done_count = sum(1 for o in des_orders if o.state in ("DONE", "SKIPPED"))

        def state_priority(s: str) -> int:
            if s in ("QC_PENDING", "RESULT_SUBMITTED"):
                return 0
            if s in ("REVISION", "REVISION_REQUESTED"):
                return 1
            if s == "IN_PROGRESS":
                return 2
            if s in ("WAITING", "ASSIGNED", "OPEN"):
                return 3
            return 4

        des_orders.sort(key=lambda o: state_priority(o.state))

        results.append(
            DesignerWorkloadOut(
                id=str(des.id),
                username=des.username,
                full_name=des.full_name or des.username,
                printerval_designer_option=des.printerval_designer_option,
                total_orders=len(des_orders),
                waiting_count=waiting_count,
                doing_count=doing_count,
                review_count=review_count,
                fix_count=fix_count,
                done_count=done_count,
                orders=[
                    DesignerWorkloadOrderOut(
                        id=str(o.id),
                        external_order_id=o.external_order_id,
                        state=o.state,
                        thumbnail_url=o.thumbnail_url,
                        deadline_at_ext=str(o.deadline_at_ext) if o.deadline_at_ext else None,
                        product_name=o.product_name,
                        printerval_designer=o.printerval_designer,
                        note_outsource=o.note_outsource or "",
                        previous_note_outsource=o.previous_note_outsource,
                        fix_approved_by_admin=o.fix_approved_by_admin,
                    )
                    for o in des_orders
                ],
            )
        )

    return results


@router.get("/orders-history", response_model=OrderHistoryListResponse)
def api_get_orders_history(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    search: str | None = None,
    order_id: str | None = None,
    designer_id: str | None = None,
    action: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(WorkflowEvent, Order)
        .join(Order, Order.id == WorkflowEvent.order_id)
    )

    header_platform_id = request.headers.get("X-Platform-Id")
    if header_platform_id and header_platform_id != "ALL":
        try:
            p_uuid = uuid.UUID(header_platform_id)
            if p_uuid != DEFAULT_PLATFORM_ID:
                query = query.filter(Order.platform_id == p_uuid)
        except ValueError:
            pass

    if user.role == "designer":
        asgn_order_ids = (
            db.query(Assignment.order_id)
            .filter(Assignment.designer_id == user.id, Assignment.status != "cancelled")
            .subquery()
        )
        query = query.filter(
            or_(
                Order.id.in_(asgn_order_ids),
                Order.printerval_designer == user.printerval_designer_option,
                Order.printerval_designer == user.full_name,
            )
        )

    if order_id and order_id.strip():
        clean_oid = order_id.strip()
        try:
            o_uuid = uuid.UUID(clean_oid)
            query = query.filter(Order.id == o_uuid)
        except ValueError:
            query = query.filter(Order.external_order_id.ilike(f"%{clean_oid}%"))

    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Order.external_order_id.ilike(term),
                Order.product_name.ilike(term),
                WorkflowEvent.from_state.ilike(term),
                WorkflowEvent.to_state.ilike(term),
                WorkflowEvent.evidence["description"].astext.ilike(term),
                WorkflowEvent.evidence["actor_name"].astext.ilike(term),
                WorkflowEvent.evidence["designer_name"].astext.ilike(term),
            )
        )

    if action and action.strip() and action != "ALL":
        query = query.filter(WorkflowEvent.evidence["action"].astext == action.strip())

    if designer_id and designer_id.strip() and designer_id != "ALL":
        try:
            d_uuid = uuid.UUID(designer_id.strip())
            d_user = db.get(User, d_uuid)
            if d_user:
                d_name = d_user.full_name or d_user.username
                query = query.filter(
                    or_(
                        WorkflowEvent.evidence["designer_id"].astext == str(d_uuid),
                        WorkflowEvent.evidence["designer_name"].astext == d_name,
                        WorkflowEvent.actor_id == d_uuid,
                    )
                )
        except ValueError:
            pass

    total = query.count()
    offset = (page - 1) * page_size
    results = query.order_by(WorkflowEvent.created_at.desc()).offset(offset).limit(page_size).all()

    actor_ids = {event.actor_id for event, _ in results if event.actor_id}
    actors_map = {}
    if actor_ids:
        users = db.query(User).filter(User.id.in_(actor_ids)).all()
        actors_map = {u.id: (u.full_name or u.username, u.role) for u in users}

    items = []
    for event, order in results:
        actor_info = actors_map.get(event.actor_id)
        actor_name = (event.evidence or {}).get("actor_name") or (actor_info[0] if actor_info else None)
        actor_role = (event.evidence or {}).get("actor_role") or (actor_info[1] if actor_info else None)
        action_type = (event.evidence or {}).get("action")
        designer_name = (event.evidence or {}).get("designer_name")
        desc = (event.evidence or {}).get("description")
        if not desc:
            from_st = event.from_state or "Mới"
            desc = f"Chuyển trạng thái từ {from_st} sang {event.to_state}"
            if actor_name:
                desc += f" bởi {actor_name}"

        items.append(
            OrderHistoryItemOut(
                id=str(event.id),
                created_at=event.created_at,
                order_id=str(order.id),
                external_order_id=order.external_order_id,
                product_name=order.product_name,
                thumbnail_url=order.thumbnail_url,
                from_state=event.from_state,
                to_state=event.to_state,
                actor_id=str(event.actor_id) if event.actor_id else None,
                actor_name=actor_name,
                actor_role=actor_role,
                action=action_type,
                description=desc,
                designer_name=designer_name,
                evidence=event.evidence,
            )
        )

    total_pages = max(1, math.ceil(total / page_size))
    return OrderHistoryListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/orders/{order_id}/history", response_model=list[WorkflowEventOut])
def api_get_single_order_history(
    order_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = None
    try:
        order_uuid = uuid.UUID(order_id)
        order = db.get(Order, order_uuid)
    except ValueError:
        pass
    if order is None:
        order = db.query(Order).filter(Order.external_order_id == order_id).first()

    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")

    # If designer, ensure they have access to this order
    if user.role == "designer":
        asgn = (
            db.query(Assignment)
            .filter(
                Assignment.order_id == order.id,
                Assignment.designer_id == user.id,
                Assignment.status != "cancelled",
            )
            .first()
        )
        is_assigned_name = (
            (user.printerval_designer_option and order.printerval_designer == user.printerval_designer_option)
            or (user.full_name and order.printerval_designer == user.full_name)
        )
        if not asgn and not is_assigned_name:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Bạn không có quyền xem lịch sử đơn hàng này")

    history = get_order_history(db, str(order.id))
    actor_ids = {e.actor_id for e in history if e.actor_id}
    actors_map = {}
    if actor_ids:
        users = db.query(User).filter(User.id.in_(actor_ids)).all()
        actors_map = {u.id: (u.full_name or u.username, u.role) for u in users}

    history_out = []
    for e in history:
        actor_info = actors_map.get(e.actor_id)
        actor_name = (e.evidence or {}).get("actor_name") or (actor_info[0] if actor_info else None)
        actor_role = (e.evidence or {}).get("actor_role") or (actor_info[1] if actor_info else None)
        action = (e.evidence or {}).get("action")
        designer_name = (e.evidence or {}).get("designer_name")
        description = (e.evidence or {}).get("description")

        if not description:
            from_st = e.from_state or "Mới"
            to_st = e.to_state
            if action == "ASSIGN":
                description = f"{actor_name or 'Admin'} phân công đơn hàng cho {designer_name or 'Designer'}"
            else:
                actor_label = f" ({actor_name})" if actor_name else ""
                description = f"Chuyển trạng thái từ {from_st} sang {to_st}{actor_label}"

        history_out.append(
            WorkflowEventOut(
                id=str(e.id),
                created_at=e.created_at,
                from_state=e.from_state,
                to_state=e.to_state,
                actor_id=str(e.actor_id) if e.actor_id else None,
                actor_name=actor_name,
                actor_role=actor_role,
                action=action,
                description=description,
                designer_name=designer_name,
                evidence=e.evidence,
            )
        )

    return history_out

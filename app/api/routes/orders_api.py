from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.adapters.db.models import Assignment, Order, Platform, PrintervalAssignmentRequest, ResultVersion, User
from app.adapters.printerval import login_session
from app.adapters.printerval.api_adapter import PrintervalApiAdapter
from app.adapters.printerval.api_client import (
    PrintervalApiClient,
    PrintervalApiConfigurationError,
    PrintervalApiError,
)
from app.adapters.printerval.interface import ALL_JOB_TYPES
from app.api.deps import (
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
    created_at: datetime
    from_state: str | None
    to_state: str


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


class BulkPrintervalAssignmentPayload(PrintervalAssignmentPayload):
    order_ids: list[str]


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
    if platform is None or not platform.account_password or not platform.team_outsource:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Platform chưa có đủ tài khoản, mật khẩu hoặc Team Outsource Printerval.",
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
    if platform is None or not platform.account_password or not platform.team_outsource:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Platform needs Printerval credentials and team scope",
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
        order.state = OrderState.IN_PROGRESS.value
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
    if not payload.printerval_designer.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Printerval Designer is required")
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

    requests: list[PrintervalAssignmentRequest] = []
    for order in orders:
        if designer is not None:
            assignment = db.query(Assignment).filter(Assignment.order_id == order.id).one_or_none()
            if assignment is None:
                db.add(Assignment(order_id=order.id, designer_id=designer.id, status="approved"))
            else:
                assignment.designer_id = designer.id
                assignment.status = "approved"
            order.state = OrderState.IN_PROGRESS.value
        try:
            requests.append(
                create_request(
                    db,
                    order=order,
                    internal_designer=designer or user,
                    platform_id=platform_id,
                    designer_option=payload.printerval_designer,
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


    return OrderDetailResponse(
        order=order_out,
        history=[WorkflowEventOut.model_validate(e) for e in history],
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
            or not platform.account_password
            or not platform.team_outsource
        ):
            return RefreshResponse(
                flash="Platform chưa có đủ tài khoản, mật khẩu hoặc Team Outsource Printerval."
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
    if existing_assignment:
        existing_assignment.designer_id = designer.id
        existing_assignment.status = "approved"
    else:
        new_assignment = Assignment(
            order_id=order.id,
            designer_id=designer.id,
            status="approved",
        )
        db.add(new_assignment)

    order.state = OrderState.IN_PROGRESS.value
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
    for order in orders:
        existing_assignment = (
            db.query(Assignment)
            .filter(Assignment.order_id == order.id)
            .one_or_none()
        )
        if existing_assignment:
            existing_assignment.designer_id = designer.id
            existing_assignment.status = "approved"
        else:
            new_assignment = Assignment(
                order_id=order.id,
                designer_id=designer.id,
                status="approved",
            )
            db.add(new_assignment)
        order.state = OrderState.IN_PROGRESS.value
        updated_count += 1

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

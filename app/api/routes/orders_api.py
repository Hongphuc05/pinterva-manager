from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.adapters.db.models import Assignment, Order, User
from app.adapters.playwright_support import playwright_session
from app.adapters.printerval import login_session
from app.adapters.printerval.api_adapter import PrintervalApiAdapter
from app.adapters.printerval.api_client import (
    PrintervalApiClient,
    PrintervalApiConfigurationError,
    PrintervalApiError,
)
from app.adapters.printerval.interface import ALL_JOB_TYPES
from app.adapters.printerval.playwright_adapter import PlaywrightPrintervalAdapter
from app.api.deps import DEFAULT_PLATFORM_ID, get_current_platform_id, get_current_user, get_db, require_role
from app.application.crawl import DiscoverFailedError
from app.application.order_queries import (
    get_order_detail_for_user,
    get_order_history,
    list_orders_for_user,
)
from app.config import get_settings
from app.domain.models import OrderState
from app.workers.crawl_tasks import run_crawl_cycle

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


class OrdersListResponse(BaseModel):
    orders: list[OrderSummaryOut]


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
    design_tool_url: str | None
    sku_image_url: str | None = None
    external_order_url: str | None = None
    source_files: list[dict] | None = None
    source_download_all_url: str | None = None
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
    # Plain "YYYY-MM-DD" from the date picker (filters on created_at) — live-confirmed
    # 2026-09-08 against the real site's own find endpoint (date_from/date_to,
    # "YYYY-MM-DD HH:MM:SS"). Only applies on the fast HTTP path (job_type == default).
    date_from: str | None = None
    date_to: str | None = None


class PrintervalLoginStatus(BaseModel):
    session_open: bool


class OrderStatesResponse(BaseModel):
    states: list[str]


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

    out_list = []
    for o in orders:
        item = OrderSummaryOut.model_validate(o)
        item.assigned_designer_name = designer_map.get(o.id)
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
    """Manual "refresh now" — dispatches the same read-only status-mirror job the
    background schedule runs, for the current platform's row specifically, and
    returns immediately (the frontend polls GET .../sync-status to see it finish)."""
    from app.workers.status_sync_tasks import sync_order_statuses

    sync_order_statuses.delay()
    return api_orders_sync_status(user=user, platform_id=platform_id, db=db)


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
        .filter(Assignment.order_id == order.id, Assignment.status == "approved")
        .first()
    )
    order_out = OrderDetailOut.model_validate(order)
    if assignment:
        order_out.assigned_designer_name = assignment[1].full_name or assignment[1].username

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
        from app.adapters.db.models import Platform
        platform = db.get(Platform, platform_id)
        crawl_username = platform.account_username if platform and platform.account_username else settings.printerval_username
        crawl_password = platform.account_password if platform and platform.account_password else settings.printerval_password
        # team_outsource scopes Printerval's find endpoint per mother account — it must
        # come from THIS platform's own row, never the process-wide .env value, or
        # crawling one platform silently uses another platform's team scope (root cause
        # of "crawl thất bại" after switching acc mẹ). Only the ONE original .env-
        # configured default platform (created before multi-tenant existed) falls back
        # to settings — any other platform without its own value is a real gap that
        # must be reported, not silently patched over with someone else's team.
        crawl_team_outsource = platform.team_outsource if platform else None
        if not crawl_team_outsource and platform_id == DEFAULT_PLATFORM_ID:
            crawl_team_outsource = settings.printerval_team_outsource

        if not platform or not platform.account_password:
            return RefreshResponse(
                flash=f"Tài khoản '{crawl_username}' chưa được lưu mật khẩu Printerval trong CSDL. Vui lòng vào menu 'Acc Mẹ Printerval' -> 'Đăng Nhập Acc Mẹ Mới' để đăng nhập lại."
            )
        if not crawl_team_outsource:
            # Printerval's find endpoint rejects an unscoped query — without this, the
            # API call fails, falls back to headless Playwright, and dies on Cloudflare
            # (see PrintervalApiClient docstring). Fail fast with a clear message instead
            # of paying that whole cascade for an outcome we already know is wrong.
            return RefreshResponse(
                flash=f"Tài khoản '{crawl_username}' chưa có 'Team Outsource'. Vui lòng vào 'Acc Mẹ Printerval' -> 'Đăng Nhập Acc Mẹ Mới' và điền đúng Team Outsource cho tài khoản này."
            )

        clean_user_slug = crawl_username.replace("@", "_").replace(".", "_").replace("+", "_") if crawl_username else "default"
        profile_dir = f"chrome-profile-{clean_user_slug}"

        with PrintervalApiClient(
            base_url=settings.printerval_api_base_url,
            username=crawl_username,
            password=crawl_password,
            team_outsource=crawl_team_outsource,
        ) as api_client:
            # ponytail: headless=True per explicit operator request (no visible Chrome
            # window popping up on every crawl) — accepting real risk: claude.md §16
            # documents Chromium headless getting 403'd by Cloudflare, and this exact
            # config caused a live incident (both new orders' claim_batch calls timed
            # out instead of claiming). find_unclaimed_order_ids now retries a failed
            # claim on the next cycle, so a headless-caused failure is not permanent —
            # just slower to actually land. Flip to False if claims keep failing.
            with playwright_session(profile_dir=profile_dir, headless=True) as page:
                fallback = PlaywrightPrintervalAdapter(
                    page=page,
                    crawl_username=crawl_username,
                    crawl_password=crawl_password,
                )
                adapter = PrintervalApiAdapter(api_client=api_client, fallback_adapter=fallback)
                summary = run_crawl_cycle(
                    db,
                    adapter,
                    platform_id=platform_id,
                    job_type=payload.job_type,
                    date_from=f"{payload.date_from} 00:00:00" if payload.date_from else None,
                    date_to=f"{payload.date_to} 23:59:59" if payload.date_to else None,
                )
        flash = (
            f"Đã crawl xong qua API ({crawl_username}): {summary['discovered']} đơn mới, "
            f"{summary['imported']} đơn nhập thành công"
        )
        failed_total = summary["failed_claim"] + summary["failed_import"]
        if failed_total:
            flash += f", {failed_total} lỗi (xem dead_letters)"
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

    order.state = OrderState.ASSIGNED.value
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
        order.state = OrderState.ASSIGNED.value
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
    password: str
    team_outsource: str | None = None


@router.post("/orders/printerval-credentials")
def api_update_printerval_credentials(
    payload: UpdatePrintervalCredentialsRequest,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    from app.adapters.db.models import Platform

    username_clean = payload.username.strip()
    password_clean = payload.password.strip()
    team_outsource_clean = payload.team_outsource.strip() if payload.team_outsource else None

    # Verify these credentials actually work against the real site BEFORE saving
    # anything — a real incident: a wrong password sat silently in the DB (saved with
    # no verification) and only surfaced as a mysterious "crawl thất bại" much later,
    # during an unrelated crawl attempt on a different day.
    settings = get_settings()
    probe_client = PrintervalApiClient(
        base_url=settings.printerval_api_base_url,
        username=username_clean,
        password=password_clean,
        team_outsource=team_outsource_clean,
    )
    try:
        probe_client.login()
    except PrintervalApiConfigurationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except PrintervalApiError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Không đăng nhập được vào Printerval bằng tài khoản '{username_clean}': {exc}. "
            "Kiểm tra lại username/mật khẩu.",
        )
    try:
        # login succeeding only proves username/password — team_outsource only gets
        # validated by the find endpoint, which a wrong value doesn't error on (it
        # just returns 0 rows), so this is a best-effort check, not a guarantee.
        probe_client.discover_waiting_page(page_size=1)
    except PrintervalApiError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Đăng nhập thành công nhưng Team Outsource có vẻ không đúng: {exc}",
        )
    finally:
        probe_client.close()

    # Get or create Platform for this mother account. Credentials (incl. team_outsource,
    # which scopes Printerval's find endpoint per account) are stored on the Platform row
    # itself, never in process-wide os.environ/Settings — that global state was clobbered
    # by whichever account logged in last, breaking crawl for every other platform.
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
            is_active=True,
        )
        db.add(platform)
    else:
        platform.account_password = password_clean
        if team_outsource_clean:
            platform.team_outsource = team_outsource_clean
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


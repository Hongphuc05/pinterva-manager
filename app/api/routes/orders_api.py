from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.adapters.playwright_support import playwright_session
from app.adapters.printerval import login_session
from app.adapters.printerval.playwright_adapter import PlaywrightPrintervalAdapter
from app.api.deps import get_current_user, get_db, require_role
from app.application.crawl import DiscoverFailedError
from app.application.order_queries import (
    get_order_detail_for_user,
    get_order_history,
    list_orders_for_user,
)
from app.domain.models import OrderState
from app.workers.crawl_tasks import run_crawl_cycle

router = APIRouter()


class OrderSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    external_order_id: str
    state: str
    batch_id: uuid.UUID | None
    sku: str | None
    thumbnail_url: str | None
    deadline_at_ext: datetime | None
    created_at: datetime


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
    design_tool_url: str | None
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
    db: Session = Depends(get_db),
):
    orders = list_orders_for_user(
        db, user, status=status_filter, batch_id=batch_id, designer_id=designer_id
    )
    return OrdersListResponse(orders=[OrderSummaryOut.model_validate(o) for o in orders])


@router.get("/orders/{order_id}", response_model=OrderDetailResponse)
def api_order_detail(
    order_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    order = get_order_detail_for_user(db, user, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    history = get_order_history(db, order_id)
    return OrderDetailResponse(
        order=OrderDetailOut.model_validate(order),
        history=[WorkflowEventOut.model_validate(e) for e in history],
    )


@router.post("/orders/refresh", response_model=RefreshResponse)
def api_orders_refresh(
    user: User = Depends(require_role("admin")), db: Session = Depends(get_db)
):
    try:
        with playwright_session() as page:
            adapter = PlaywrightPrintervalAdapter(page=page)
            summary = run_crawl_cycle(db, adapter)
        flash = (
            f"Đã crawl xong: {summary['discovered']} đơn mới, "
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
            "Crawl thất bại khi tìm đơn mới — có thể site đổi giao diện hoặc bộ lọc "
            "sai. Xem bảng dead_letters (source=crawl.discover_waiting_orders) để "
            "biết chi tiết lỗi thật."
        )
        return RefreshResponse(flash=flash)
    except Exception:
        db.rollback()
        flash = "Crawl thất bại — kiểm tra Chrome profile đã đăng nhập Printerval chưa."
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

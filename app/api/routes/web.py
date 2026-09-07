from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.adapters.playwright_support import (
    close_playwright_session,
    open_playwright_session,
    playwright_session,
)
from app.adapters.printerval.playwright_adapter import ADMIN_URL, PlaywrightPrintervalAdapter
from app.api.deps import SESSION_COOKIE_NAME, get_current_user_web, get_db
from app.application.auth import create_session_token, verify_password
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
templates = Jinja2Templates(directory="app/api/templates")

# Module-level state for the interactive "log in to Printerval" flow: one admin, one
# browser window, opened by one request and closed by a later one — a plain global is
# enough for this single-operator, rare, admin-only action (matches the same "1
# session/site, no real concurrency handling" acceptance already made for the Refresh
# button). None means no interactive login window is currently open.
_login_session: dict | None = None


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"user": None})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter_by(username=username).one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"user": None, "error": "Sai tên đăng nhập hoặc mật khẩu"},
            status_code=401,
        )
    settings = get_settings()
    token = create_session_token(str(user.id), user.role)
    response = RedirectResponse("/orders", status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_max_age_seconds,
    )
    return response


@router.post("/logout")
def logout_submit():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@router.get("/")
def index(user: User = Depends(get_current_user_web)):
    return RedirectResponse("/orders", status_code=303)


@router.get("/orders")
def orders_list(
    request: Request,
    status: str | None = None,
    batch_id: str | None = None,
    designer_id: str | None = None,
    user: User = Depends(get_current_user_web),
    db: Session = Depends(get_db),
):
    orders = list_orders_for_user(
        db, user, status=status, batch_id=batch_id, designer_id=designer_id
    )
    return templates.TemplateResponse(
        request,
        "orders_list.html",
        {
            "user": user,
            "orders": orders,
            "status": status,
            "batch_id": batch_id,
            "order_states": [s.value for s in OrderState],
        },
    )


@router.post("/orders/refresh")
def orders_refresh(
    request: Request,
    user: User = Depends(get_current_user_web),
    db: Session = Depends(get_db),
):
    """Manually trigger one crawl cycle (Phase 3's discover -> claim -> import),
    synchronously, and re-render the order list with a result summary. Admin-only —
    this opens a real Playwright session against the live Printerval site. Known,
    accepted V1 limitation: no lock against a concurrently-running Celery Beat
    schedule of the same job — see AGENT.md/roadmap for the "1 session/site" note.
    """
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Chỉ admin mới chạy được refresh")

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
    except DiscoverFailedError:
        # Distinct from the generic Playwright-session-failure case below: the
        # session opened fine, but the site's "find waiting orders" step itself
        # failed (e.g. a filter dropdown's option text changed) — already
        # dead-lettered. Must never be confused with "0 new orders" (a real incident:
        # a genuinely visible Waiting order on the live site was silently reported as
        # 0 results because this case wasn't distinguished before).
        flash = (
            "Crawl thất bại khi tìm đơn mới — có thể site đổi giao diện hoặc bộ lọc "
            "sai. Xem bảng dead_letters (source=crawl.discover_waiting_orders) để "
            "biết chi tiết lỗi thật."
        )
    except Exception:
        flash = "Crawl thất bại — kiểm tra Chrome profile đã đăng nhập Printerval chưa."

    orders = list_orders_for_user(db, user)
    return templates.TemplateResponse(
        request,
        "orders_list.html",
        {
            "user": user,
            "orders": orders,
            "status": None,
            "batch_id": None,
            "order_states": [s.value for s in OrderState],
            "flash": flash,
        },
    )


@router.get("/orders/table")
def orders_table(
    request: Request,
    status: str | None = None,
    batch_id: str | None = None,
    designer_id: str | None = None,
    user: User = Depends(get_current_user_web),
    db: Session = Depends(get_db),
):
    orders = list_orders_for_user(
        db, user, status=status, batch_id=batch_id, designer_id=designer_id
    )
    return templates.TemplateResponse(
        request, "orders_table.html", {"orders": orders}
    )


@router.get("/printerval-login")
def printerval_login_page(request: Request, user: User = Depends(get_current_user_web)):
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Chỉ admin mới thao tác được")
    return templates.TemplateResponse(
        request,
        "printerval_login.html",
        {"user": user, "session_open": _login_session is not None},
    )


@router.post("/printerval-login/start")
def printerval_login_start(user: User = Depends(get_current_user_web)):
    """Open a real, visible Chrome window on the shared persistent profile and
    navigate to Printerval's admin page, so a human can log in by hand. Stays open
    across this request's return — a second request (`/printerval-login/done`) closes
    it once the human is done. Admin-only, one window at a time.
    """
    global _login_session
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Chỉ admin mới thao tác được")

    if _login_session is not None:
        try:
            _ = _login_session["context"].pages  # cheap liveness check
        except Exception:
            # Stale — e.g. the human closed the Chrome window by hand instead of
            # clicking Done. Drop it and open a fresh one below.
            _login_session = None

    if _login_session is None:
        playwright_cm, context, page = open_playwright_session()
        page.goto(ADMIN_URL)
        _login_session = {"playwright_cm": playwright_cm, "context": context}

    return RedirectResponse("/printerval-login", status_code=303)


@router.post("/printerval-login/done")
def printerval_login_done(user: User = Depends(get_current_user_web)):
    """Close the Chrome window opened by /printerval-login/start."""
    global _login_session
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Chỉ admin mới thao tác được")

    if _login_session is not None:
        close_playwright_session(_login_session["playwright_cm"], _login_session["context"])
        _login_session = None

    return RedirectResponse("/orders", status_code=303)


@router.get("/orders/{order_id}")
def order_detail(
    request: Request,
    order_id: str,
    user: User = Depends(get_current_user_web),
    db: Session = Depends(get_db),
):
    order = get_order_detail_for_user(db, user, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    history = get_order_history(db, order_id)
    return templates.TemplateResponse(
        request,
        "order_detail.html",
        {"user": user, "order": order, "history": history},
    )

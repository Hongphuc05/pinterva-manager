from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.api.deps import SESSION_COOKIE_NAME, get_current_user_web, get_db
from app.application.auth import create_session_token, verify_password
from app.application.order_queries import list_orders_for_user
from app.config import get_settings
from app.domain.models import OrderState

router = APIRouter()
templates = Jinja2Templates(directory="app/api/templates")


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

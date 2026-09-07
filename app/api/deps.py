from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.adapters.db.session import SessionLocal
from app.application.auth import read_session_token

SESSION_COOKIE_NAME = "session"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    data = read_session_token(token)
    if data is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    user = db.get(User, uuid.UUID(data["user_id"]))
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def require_role(role: str):
    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role != role:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return _check


DEFAULT_PLATFORM_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def get_current_platform_id(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> uuid.UUID:
    from app.adapters.db.models import Platform

    header_platform_id = request.headers.get("X-Platform-Id")
    if header_platform_id and user.role == "admin":
        try:
            return uuid.UUID(header_platform_id)
        except ValueError:
            pass

    if user.platform_id:
        return user.platform_id

    # Fallback to default active platform
    default_platform = (
        db.query(Platform)
        .filter(Platform.is_active == True)  # noqa: E712
        .order_by(Platform.created_at.asc())
        .first()
    )
    if default_platform:
        return default_platform.id

    # Ensure robust fallback for unit tests and fresh DB sessions
    default_platform = Platform(
        id=DEFAULT_PLATFORM_ID,
        name="Nền tảng Mặc định (Acc Mẹ 1)",
        account_username="main_admin@printerval.com",
        is_active=True,
    )
    db.add(default_platform)
    try:
        db.commit()
    except Exception:
        db.rollback()
    return DEFAULT_PLATFORM_ID


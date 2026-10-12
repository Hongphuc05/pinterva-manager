from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.api.deps import SESSION_COOKIE_NAME, get_current_user, get_db
from app.application.auth import (
    create_session_token,
    ensure_seed_users,
    read_session_token,
    verify_password,
)
from app.application.support_worker import revoke_user_devices
from app.config import get_settings

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    ensure_seed_users(db)
    # Login has no platform selector (one username+password form for every Acc Mẹ), but a
    # username is now only unique PER platform (uq_users_platform_id_username) — two different
    # platforms may each have their own "admin". Try every candidate with that username and
    # match by password instead.
    candidates = db.query(User).filter_by(username=payload.username).all()
    user = next((u for u in candidates if verify_password(payload.password, u.password_hash)), None)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is disabled")

    settings = get_settings()
    token = create_session_token(str(user.id), user.role)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_max_age_seconds,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "username": user.username,
            "role": user.role,
            "full_name": user.full_name,
        },
        "id": str(user.id),
        "role": user.role,
    }


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    # Logging out also stops every Support machine this user allowed to compute.
    authorization = request.headers.get("authorization", "")
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
    data = read_session_token(token or request.cookies.get(SESSION_COOKIE_NAME) or "")
    if data is not None:
        revoke_user_devices(db, uuid.UUID(data["user_id"]))
        db.commit()
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "id": str(user.id),
        "username": user.username,
        "role": user.role,
        "full_name": user.full_name,
    }


from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.api.deps import SESSION_COOKIE_NAME, get_current_user, get_db
from app.application.auth import (
    create_session_token,
    ensure_seed_users,
    verify_password,
)
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
def logout(response: Response):
    # The hosting machine keeps working after its owner logs out: it is stopped from the machine.
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


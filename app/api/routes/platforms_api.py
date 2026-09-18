from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.adapters.db.models import Platform, User
from app.api.deps import get_current_platform_id, get_db, require_role
from app.application.platform_credentials import (
    PlatformCredentialsError,
    verify_and_save_platform_credentials,
)

router = APIRouter(prefix="/platforms", tags=["platforms"])


class PlatformOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    account_username: str
    team_outsource: str | None = None
    is_active: bool
    created_at: datetime


class CreatePlatformRequest(BaseModel):
    name: str
    account_username: str


class UpdatePlatformCredentialsRequest(BaseModel):
    username: str
    password: str | None = None
    team_outsource: str | None = None
    session_cookie: str | None = None


class PlatformCredentialsOut(BaseModel):
    ok: bool
    platform_id: uuid.UUID
    platform_name: str
    account_username: str
    team_outsource: str | None
    message: str


@router.get("", response_model=list[PlatformOut])
def list_platforms(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    platforms = db.query(Platform).filter(Platform.is_active == True).order_by(Platform.created_at.asc()).all()  # noqa: E712
    return platforms


@router.get("/current", response_model=PlatformOut)
def get_current_platform(
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    """Return only the caller's effective platform for display purposes."""
    platform = db.get(Platform, platform_id)
    if platform is None or not platform.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform not found")
    return platform


@router.post("", response_model=PlatformOut, status_code=status.HTTP_201_CREATED)
def create_platform(
    req: CreatePlatformRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    account_user = req.account_username.strip()
    if not account_user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Account username is required")

    existing = (
        db.query(Platform)
        .filter(Platform.account_username == account_user, Platform.is_active == True)  # noqa: E712
        .first()
    )
    if existing:
        return existing

    name = req.name.strip() if req.name and req.name.strip() else f"Acc Mẹ: {account_user}"
    platform = Platform(
        name=name,
        account_username=account_user,
        is_active=True,
    )
    db.add(platform)
    db.commit()
    db.refresh(platform)
    return platform


@router.patch("/{platform_id}/credentials", response_model=PlatformCredentialsOut)
def update_platform_credentials(
    platform_id: uuid.UUID,
    req: UpdatePlatformCredentialsRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    platform = db.get(Platform, platform_id)
    if platform is None or not platform.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform not found")
    if req.username.strip().lower() != platform.account_username.lower():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Username không khớp Acc Mẹ này. Hãy tạo hoặc chọn đúng Acc Mẹ trước khi cập nhật credential.",
        )
    try:
        platform = verify_and_save_platform_credentials(
            db,
            platform=platform,
            username=req.username,
            password=req.password,
            team_outsource=req.team_outsource,
            session_cookie=req.session_cookie,
        )
    except PlatformCredentialsError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return PlatformCredentialsOut(
        ok=True,
        platform_id=platform.id,
        platform_name=platform.name,
        account_username=platform.account_username,
        team_outsource=platform.team_outsource,
        message=f"Đã xác thực tài khoản Printerval thành công: {platform.account_username}",
    )


@router.delete("/{platform_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_platform(
    platform_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    platform = db.get(Platform, platform_id)
    if not platform or not platform.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform not found")
    
    active_count = db.query(Platform).filter(Platform.is_active == True).count()  # noqa: E712
    if active_count <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete the last remaining platform")
    
    platform.is_active = False
    db.commit()

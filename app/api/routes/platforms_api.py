from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.adapters.db.models import Platform, User
from app.api.deps import get_db, require_role

router = APIRouter(prefix="/platforms", tags=["platforms"])


class PlatformOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    account_username: str
    team_outsource: str | None = None
    session_cookie: str | None = None
    is_active: bool
    created_at: datetime


class CreatePlatformRequest(BaseModel):
    name: str
    account_username: str


@router.get("", response_model=list[PlatformOut])
def list_platforms(
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    platforms = db.query(Platform).filter(Platform.is_active == True).order_by(Platform.created_at.asc()).all()  # noqa: E712
    return platforms


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

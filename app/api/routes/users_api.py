from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.api.deps import get_current_platform_id, get_db, require_role
from app.application.auth import hash_password
from app.application.password_vault import decrypt_password, encrypt_password

router = APIRouter()


class UserOut(BaseModel):
    id: str
    username: str
    full_name: str
    role: str
    active: bool
    platform_id: str | None = None
    created_at: datetime


class CreateUserRequest(BaseModel):
    username: str
    password: str
    full_name: str
    role: str = "designer"  # "admin" | "designer" | "user"


class UserPasswordOut(BaseModel):
    password: str | None = None
    recoverable: bool


class UpdateUserPasswordRequest(BaseModel):
    password: str


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        active=user.active,
        platform_id=str(user.platform_id) if user.platform_id else None,
        created_at=user.created_at,
    )


def _target_user(db: Session, user_id: str) -> User:
    try:
        target_uuid = uuid.UUID(user_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mã người dùng không hợp lệ.") from exc
    target_user = db.get(User, target_uuid)
    if target_user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy người dùng.")
    return target_user


@router.get("/users", response_model=list[UserOut])
def list_users(
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    # Admins see all admin users + designers assigned to the current active platform (or unassigned designers)
    query = db.query(User).filter(
        (User.role == "admin") | (User.platform_id == platform_id) | (User.platform_id.is_(None))
    )
    users = query.order_by(User.created_at.desc()).all()
    return [_user_out(u) for u in users]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    current_admin: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    clean_username = payload.username.strip()
    if not clean_username or len(clean_username) < 3:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Tên tài khoản phải có ít nhất 3 ký tự."
        )

    clean_password = payload.password.strip()
    if not clean_password or len(clean_password) < 4:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Mật khẩu phải có ít nhất 4 ký tự."
        )

    role = payload.role.strip().lower()
    if role == "user":
        role = "designer"
    if role not in ("admin", "designer"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Vai trò không hợp lệ (admin hoặc designer)."
        )

    existing = db.query(User).filter_by(username=clean_username).one_or_none()
    if existing is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Tài khoản '{clean_username}' đã tồn tại."
        )

    new_user = User(
        username=clean_username,
        full_name=payload.full_name.strip() or clean_username,
        role=role,
        password_hash=hash_password(clean_password),
        password_ciphertext=encrypt_password(clean_password),
        platform_id=platform_id if role == "designer" else None,
        active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return _user_out(new_user)


@router.get("/users/{user_id}/password", response_model=UserPasswordOut)
def get_user_password(
    user_id: str,
    current_admin: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    target_user = _target_user(db, user_id)
    password = decrypt_password(target_user.password_ciphertext)
    return UserPasswordOut(password=password, recoverable=password is not None)


@router.patch("/users/{user_id}/password", response_model=UserOut)
def update_user_password(
    user_id: str,
    payload: UpdateUserPasswordRequest,
    current_admin: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    clean_password = payload.password.strip()
    if len(clean_password) < 4:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mật khẩu phải có ít nhất 4 ký tự.")
    target_user = _target_user(db, user_id)
    target_user.password_hash = hash_password(clean_password)
    target_user.password_ciphertext = encrypt_password(clean_password)
    db.commit()
    db.refresh(target_user)
    return _user_out(target_user)


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    current_admin: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    try:
        target_uuid = uuid.UUID(user_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mã người dùng không hợp lệ.") from exc

    if target_uuid == current_admin.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Không thể tự xóa tài khoản của chính mình."
        )

    target_user = _target_user(db, user_id)

    db.delete(target_user)
    db.commit()
    return {"ok": True, "message": f"Đã xóa tài khoản '{target_user.username}'."}

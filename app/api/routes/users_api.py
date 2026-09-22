from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.db.models import User, UserBankQr
from app.api.deps import (
    get_current_platform_id,
    get_current_user,
    get_db,
    require_any_role,
    require_role,
)
from app.application.auth import hash_password
from app.application.order_work_notes import PRIVATE_WORK_NOTE_ASSETS_DIR
from app.application.password_vault import decrypt_password, encrypt_password
from app.domain.access import ROLE_ADMIN, ROLE_DESIGNER, ROLE_DESIGNER_TRELLO, ROLE_SUPPORT

router = APIRouter()
logger = logging.getLogger(__name__)

BANK_QR_ASSETS_DIR = PRIVATE_WORK_NOTE_ASSETS_DIR / "bank_qr"
MAX_BANK_QR_IMAGES = 3
MAX_BANK_QR_BYTES = 10 * 1024 * 1024
BANK_QR_ROLES = (ROLE_DESIGNER, ROLE_DESIGNER_TRELLO, ROLE_SUPPORT)


def _image_type(content: bytes) -> tuple[str, str] | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


class BankQrImageOut(BaseModel):
    id: str
    filename: str
    content_type: str
    byte_size: int
    sort_order: int
    url: str


class BankQrImageListOut(BaseModel):
    images: list[BankQrImageOut]


def _bank_qr_out(image: UserBankQr) -> BankQrImageOut:
    return BankQrImageOut(
        id=str(image.id),
        filename=image.original_filename,
        content_type=image.content_type,
        byte_size=image.byte_size,
        sort_order=image.sort_order,
        # This URL is consumed directly by clients as well as through apiFetchBlob().
        # Return the canonical API path so it cannot fall through to the SPA route.
        url=f"/api/users/{image.user_id}/bank-qr/{image.id}",
    )


def _bank_qr_images(db: Session, user_id: uuid.UUID) -> list[UserBankQr]:
    return (
        db.query(UserBankQr)
        .filter(UserBankQr.user_id == user_id)
        .order_by(UserBankQr.sort_order.asc(), UserBankQr.created_at.asc())
        .all()
    )


def _bank_qr_path(image: UserBankQr) -> Path:
    root = BANK_QR_ASSETS_DIR.resolve()
    path = (root / image.storage_key).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy ảnh QR.")
    return path


@router.get("/users/me/bank-qr", response_model=BankQrImageListOut)
def list_my_bank_qr_images(
    current_user: User = Depends(require_any_role(*BANK_QR_ROLES)),
    db: Session = Depends(get_db),
):
    return BankQrImageListOut(images=[_bank_qr_out(image) for image in _bank_qr_images(db, current_user.id)])


@router.post("/users/me/bank-qr", response_model=BankQrImageOut, status_code=status.HTTP_201_CREATED)
async def upload_my_bank_qr_image(
    file: UploadFile = File(...),
    replace_image_id: uuid.UUID | None = Query(default=None),
    current_user: User = Depends(require_any_role(*BANK_QR_ROLES)),
    db: Session = Depends(get_db),
):
    existing = _bank_qr_images(db, current_user.id)
    replacing = next((image for image in existing if image.id == replace_image_id), None)
    if replace_image_id is not None and replacing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy ảnh QR cần thay.")
    if replacing is None and len(existing) >= MAX_BANK_QR_IMAGES:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Mỗi tài khoản chỉ được lưu tối đa {MAX_BANK_QR_IMAGES} ảnh QR.")

    content = await file.read(MAX_BANK_QR_BYTES + 1)
    if not content or len(content) > MAX_BANK_QR_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Mỗi ảnh QR tối đa 10 MB.")
    detected = _image_type(content)
    if detected is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Chỉ chấp nhận ảnh PNG, JPEG hoặc WebP.")
    content_type, extension = detected

    image_id = uuid.uuid4()
    sort_order = replacing.sort_order if replacing is not None else max((image.sort_order for image in existing), default=-1) + 1
    storage_key = f"{current_user.id}/{image_id}{extension}"
    target = BANK_QR_ASSETS_DIR / storage_key
    old_path = (BANK_QR_ASSETS_DIR / replacing.storage_key).resolve() if replacing is not None else None
    written = False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        written = True
        if replacing is not None:
            replacing.storage_key = storage_key
            replacing.original_filename = Path(file.filename or "bank-qr").name[:255]
            replacing.content_type = content_type
            replacing.byte_size = len(content)
            image = replacing
        else:
            image = UserBankQr(
                id=image_id,
                user_id=current_user.id,
                storage_key=storage_key,
                original_filename=Path(file.filename or "bank-qr").name[:255],
                content_type=content_type,
                byte_size=len(content),
                sort_order=sort_order,
            )
            db.add(image)
        db.commit()
        db.refresh(image)
        if old_path is not None and BANK_QR_ASSETS_DIR.resolve() in old_path.parents:
            try:
                old_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove replaced bank QR file %s", old_path, exc_info=True)
        return _bank_qr_out(image)
    except HTTPException:
        raise
    except IntegrityError as exc:
        db.rollback()
        if written:
            target.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_409_CONFLICT, "Ảnh QR vừa được cập nhật ở nơi khác. Hãy tải lại rồi thử lại.") from exc
    except Exception as exc:
        db.rollback()
        if written:
            target.unlink(missing_ok=True)
        logger.exception("Could not persist bank QR image for user %s", current_user.id)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Không thể lưu ảnh QR. Hãy kiểm tra quyền thư mục lưu trữ.") from exc


@router.delete("/users/me/bank-qr/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_bank_qr_image(
    image_id: uuid.UUID,
    current_user: User = Depends(require_any_role(*BANK_QR_ROLES)),
    db: Session = Depends(get_db),
):
    image = (
        db.query(UserBankQr)
        .filter(UserBankQr.id == image_id, UserBankQr.user_id == current_user.id)
        .one_or_none()
    )
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy ảnh QR.")
    path = (BANK_QR_ASSETS_DIR / image.storage_key).resolve()
    db.delete(image)
    db.commit()
    root = BANK_QR_ASSETS_DIR.resolve()
    if root in path.parents:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove deleted bank QR file %s", path, exc_info=True)
    return None


@router.get("/users/{user_id}/bank-qr", response_model=BankQrImageListOut)
def list_user_bank_qr_images(
    user_id: str,
    current_admin: User = Depends(require_role(ROLE_ADMIN)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    target_user = _current_platform_user(db, user_id, platform_id)
    return BankQrImageListOut(images=[_bank_qr_out(image) for image in _bank_qr_images(db, target_user.id)])


@router.get("/users/{user_id}/bank-qr/{image_id}")
def download_user_bank_qr_image(
    user_id: str,
    image_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    target_user = (
        _current_platform_user(db, user_id, platform_id)
        if current_user.role == ROLE_ADMIN
        else _target_user(db, user_id)
    )
    if current_user.role != ROLE_ADMIN and target_user.id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Chỉ được xem ảnh QR của chính mình.")
    image = (
        db.query(UserBankQr)
        .filter(UserBankQr.id == image_id, UserBankQr.user_id == target_user.id)
        .one_or_none()
    )
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy ảnh QR.")
    return FileResponse(
        _bank_qr_path(image),
        media_type=image.content_type,
        filename=image.original_filename,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


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
    role: str = ROLE_DESIGNER


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


def _current_platform_user(db: Session, user_id: str, platform_id: uuid.UUID) -> User:
    target_user = _target_user(db, user_id)
    if target_user.platform_id != platform_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy người dùng trong Acc Mẹ đang chọn.")
    return target_user


@router.get("/users", response_model=list[UserOut])
def list_users(
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    # A manager sees every account created in the currently selected mother account.
    query = db.query(User).filter(User.platform_id == platform_id)
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
        role = ROLE_DESIGNER
    if role not in (ROLE_ADMIN, ROLE_DESIGNER, ROLE_DESIGNER_TRELLO, ROLE_SUPPORT):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Vai trò không hợp lệ (admin, designer, designer-trello hoặc support).",
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
        # Every account keeps the mother account where it was created. Admin
        # role still uniquely grants the ability to switch and operate across
        # all platforms.
        platform_id=platform_id,
        active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return _user_out(new_user)


@router.get("/users/unassigned", response_model=list[UserOut])
def list_unassigned_users(
    current_admin: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Temporary migration queue for accounts created before platform scoping."""
    users = (
        db.query(User)
        .filter(User.platform_id.is_(None))
        .order_by(User.created_at.asc())
        .all()
    )
    return [_user_out(user) for user in users]


@router.patch("/users/{user_id}/platform", response_model=UserOut)
def assign_legacy_user_to_current_platform(
    user_id: str,
    current_admin: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    """Bind one legacy unassigned account to the selected platform."""
    target_user = _target_user(db, user_id)
    if target_user.platform_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tài khoản này đã được gán Acc Mẹ.")
    target_user.platform_id = platform_id
    db.commit()
    db.refresh(target_user)
    return _user_out(target_user)


@router.get("/users/{user_id}/password", response_model=UserPasswordOut)
def get_user_password(
    user_id: str,
    current_admin: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    target_user = _current_platform_user(db, user_id, platform_id)
    password = decrypt_password(target_user.password_ciphertext)
    return UserPasswordOut(password=password, recoverable=password is not None)


@router.patch("/users/{user_id}/password", response_model=UserOut)
def update_user_password(
    user_id: str,
    payload: UpdateUserPasswordRequest,
    current_admin: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    clean_password = payload.password.strip()
    if len(clean_password) < 4:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mật khẩu phải có ít nhất 4 ký tự.")
    target_user = _current_platform_user(db, user_id, platform_id)
    target_user.password_hash = hash_password(clean_password)
    target_user.password_ciphertext = encrypt_password(clean_password)
    db.commit()
    db.refresh(target_user)
    return _user_out(target_user)


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    current_admin: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
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

    target_user = _current_platform_user(db, user_id, platform_id)

    db.delete(target_user)
    db.commit()
    return {"ok": True, "message": f"Đã xóa tài khoản '{target_user.username}'."}

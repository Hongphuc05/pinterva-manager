from __future__ import annotations

import html
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.db.models import TelegramConfigurationAudit, TelegramMessageTemplate, User
from app.api.deps import get_current_platform_id, get_db, require_role
from app.application.telegram_service import (
    DEFAULT_TELEGRAM_TEMPLATES,
    TELEGRAM_DELIVERY_GROUP,
    TELEGRAM_DELIVERY_PRIVATE,
    get_bot_username,
    inspect_telegram_group,
    is_telegram_configured,
    render_telegram_template,
    resolve_designer_chat_target,
    send_message,
    template_metadata,
    validate_telegram_template_body,
)
from app.domain.access import ROLE_ADMIN, ROLE_DESIGNER, ROLE_DESIGNER_TRELLO, ROLE_SUPPORT

router = APIRouter(prefix="/telegram/admin", tags=["telegram-admin"])
DESIGNER_ROLES = (ROLE_DESIGNER, ROLE_DESIGNER_TRELLO)
TELEGRAM_RECIPIENT_ROLES = (*DESIGNER_ROLES, ROLE_SUPPORT)
CHAT_ID_PATTERN = re.compile(r"-?\d{1,64}")


class TelegramDesignerOut(BaseModel):
    id: str
    username: str
    full_name: str
    role: str
    active: bool
    private_chat_id: str | None
    private_username: str | None
    private_connected: bool
    group_chat_id: str | None
    group_title: str | None
    group_type: str | None
    group_configured: bool
    group_verified: bool
    group_verified_at: datetime | None
    group_last_error: str | None
    delivery_mode: Literal["private", "group"]
    selected_chat_id: str | None
    notifications_enabled: bool


class TelegramOverviewOut(BaseModel):
    is_configured: bool
    bot_username: str | None
    platform_id: str
    recipient_count: int
    designer_count: int
    support_count: int
    private_connected_count: int
    group_configured_count: int
    group_verified_count: int
    designers: list[TelegramDesignerOut]


class GroupChatRequest(BaseModel):
    group_chat_id: str = Field(min_length=1, max_length=64)


class DeliveryModeRequest(BaseModel):
    mode: Literal["private", "group"]


class TelegramTestRequest(BaseModel):
    message: str = Field(default="✅ Tin nhắn test từ bot des-mana.", min_length=1, max_length=4096)


class TelegramTestOut(BaseModel):
    ok: bool
    mode: Literal["private", "group"]
    chat_id: str
    message: str


class TelegramTemplateOut(BaseModel):
    template_key: str
    audience: Literal["designer", "admin", "support"]
    body: str
    active: bool
    version: int
    updated_by_id: str | None
    updated_at: datetime | None
    placeholders: list[str]


class TelegramTemplateUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=4096)


class TelegramTemplatePreviewRequest(BaseModel):
    body: str | None = Field(default=None, max_length=4096)
    context: dict[str, str] = Field(default_factory=dict)


class TelegramTemplatePreviewOut(BaseModel):
    template_key: str
    rendered: str


def _designer(db: Session, user_id: str, platform_id: uuid.UUID) -> User:
    try:
        target_id = uuid.UUID(user_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mã người nhận không hợp lệ.") from exc
    target = (
        db.query(User)
        .filter(
            User.id == target_id,
            User.platform_id == platform_id,
            User.role.in_(TELEGRAM_RECIPIENT_ROLES),
        )
        .one_or_none()
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy người nhận trong Acc Mẹ đang chọn.")
    return target


def _designer_snapshot(user: User) -> dict[str, Any]:
    return {
        "private_chat_id": user.telegram_chat_id,
        "private_username": user.telegram_username,
        "group_chat_id": user.telegram_group_chat_id,
        "group_title": user.telegram_group_title,
        "group_type": user.telegram_group_type,
        "group_verified": user.telegram_group_verified,
        "group_verified_at": user.telegram_group_verified_at.isoformat() if user.telegram_group_verified_at else None,
        "group_last_error": user.telegram_group_last_error,
        "delivery_mode": user.telegram_delivery_mode,
        "notifications_enabled": user.telegram_notifications_enabled,
    }


def _designer_out(user: User) -> TelegramDesignerOut:
    mode = user.telegram_delivery_mode or TELEGRAM_DELIVERY_PRIVATE
    selected_chat_id = (
        user.telegram_group_chat_id
        if mode == TELEGRAM_DELIVERY_GROUP and user.telegram_group_verified
        else user.telegram_chat_id if mode == TELEGRAM_DELIVERY_PRIVATE else None
    )
    return TelegramDesignerOut(
        id=str(user.id),
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        active=user.active,
        private_chat_id=user.telegram_chat_id,
        private_username=user.telegram_username,
        private_connected=bool(user.telegram_chat_id),
        group_chat_id=user.telegram_group_chat_id,
        group_title=user.telegram_group_title,
        group_type=user.telegram_group_type,
        group_configured=bool(user.telegram_group_chat_id),
        group_verified=user.telegram_group_verified,
        group_verified_at=user.telegram_group_verified_at,
        group_last_error=user.telegram_group_last_error,
        delivery_mode=mode,
        selected_chat_id=selected_chat_id,
        notifications_enabled=user.telegram_notifications_enabled,
    )


def _audit(
    db: Session,
    *,
    actor_id: uuid.UUID,
    action_type: str,
    target_user_id: uuid.UUID | None = None,
    template_key: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    db.add(
        TelegramConfigurationAudit(
            actor_id=actor_id,
            target_user_id=target_user_id,
            template_key=template_key,
            action_type=action_type,
            before=before,
            after=after,
        )
    )


@router.get("/overview", response_model=TelegramOverviewOut)
def get_telegram_admin_overview(
    current_admin: User = Depends(require_role(ROLE_ADMIN)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    recipients = (
        db.query(User)
        .filter(User.platform_id == platform_id, User.role.in_(TELEGRAM_RECIPIENT_ROLES))
        .order_by(User.active.desc(), User.full_name.asc(), User.username.asc())
        .all()
    )
    rows = [_designer_out(recipient) for recipient in recipients]
    return TelegramOverviewOut(
        is_configured=is_telegram_configured(),
        bot_username=get_bot_username() or None,
        platform_id=str(platform_id),
        recipient_count=len(rows),
        designer_count=sum(row.role in DESIGNER_ROLES for row in rows),
        support_count=sum(row.role == ROLE_SUPPORT for row in rows),
        private_connected_count=sum(row.private_connected for row in rows),
        group_configured_count=sum(row.group_configured for row in rows),
        group_verified_count=sum(row.group_verified for row in rows),
        designers=rows,
    )


@router.put("/designers/{user_id}/group", response_model=TelegramDesignerOut)
def save_designer_group_chat(
    user_id: str,
    payload: GroupChatRequest,
    current_admin: User = Depends(require_role(ROLE_ADMIN)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    group_chat_id = payload.group_chat_id.strip()
    if not CHAT_ID_PATTERN.fullmatch(group_chat_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Group chat ID phải là một số hợp lệ.")
    target = _designer(db, user_id, platform_id)
    if target.role == ROLE_SUPPORT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Support hiện chỉ nhận candidate qua chat riêng Telegram.")
    duplicate = (
        db.query(User)
        .filter(User.telegram_group_chat_id == group_chat_id, User.id != target.id)
        .one_or_none()
    )
    if duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, "Group này đã được gắn cho một designer khác.")

    before = _designer_snapshot(target)
    target.telegram_group_chat_id = group_chat_id
    target.telegram_group_title = None
    target.telegram_group_type = None
    target.telegram_group_verified = False
    target.telegram_group_verified_at = None
    target.telegram_group_last_error = None
    _audit(
        db,
        actor_id=current_admin.id,
        target_user_id=target.id,
        action_type="SET_DESIGNER_GROUP_CHAT",
        before=before,
        after=_designer_snapshot(target),
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Group này vừa được gắn cho designer khác.") from exc
    db.refresh(target)
    return _designer_out(target)


@router.delete("/designers/{user_id}/group", response_model=TelegramDesignerOut)
def clear_designer_group_chat(
    user_id: str,
    current_admin: User = Depends(require_role(ROLE_ADMIN)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    target = _designer(db, user_id, platform_id)
    if target.role == ROLE_SUPPORT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Support hiện chỉ nhận candidate qua chat riêng Telegram.")
    before = _designer_snapshot(target)
    target.telegram_group_chat_id = None
    target.telegram_group_title = None
    target.telegram_group_type = None
    target.telegram_group_verified = False
    target.telegram_group_verified_at = None
    target.telegram_group_last_error = None
    if target.telegram_delivery_mode == TELEGRAM_DELIVERY_GROUP:
        target.telegram_delivery_mode = TELEGRAM_DELIVERY_PRIVATE
    _audit(
        db,
        actor_id=current_admin.id,
        target_user_id=target.id,
        action_type="CLEAR_DESIGNER_GROUP_CHAT",
        before=before,
        after=_designer_snapshot(target),
    )
    db.commit()
    db.refresh(target)
    return _designer_out(target)


@router.post("/designers/{user_id}/group/verify", response_model=TelegramDesignerOut)
def verify_designer_group_chat(
    user_id: str,
    current_admin: User = Depends(require_role(ROLE_ADMIN)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    target = _designer(db, user_id, platform_id)
    if target.role == ROLE_SUPPORT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Support hiện chỉ nhận candidate qua chat riêng Telegram.")
    if not target.telegram_group_chat_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Designer này chưa có group chat ID.")
    before = _designer_snapshot(target)
    inspection = inspect_telegram_group(target.telegram_group_chat_id)
    target.telegram_group_verified = inspection.ok
    target.telegram_group_verified_at = datetime.now(UTC) if inspection.ok else None
    target.telegram_group_title = inspection.title if inspection.ok else target.telegram_group_title
    target.telegram_group_type = inspection.chat_type if inspection.ok else target.telegram_group_type
    target.telegram_group_last_error = inspection.error
    _audit(
        db,
        actor_id=current_admin.id,
        target_user_id=target.id,
        action_type="VERIFY_DESIGNER_GROUP_CHAT" if inspection.ok else "VERIFY_DESIGNER_GROUP_CHAT_FAILED",
        before=before,
        after=_designer_snapshot(target),
    )
    db.commit()
    db.refresh(target)
    if not inspection.ok:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, inspection.error or "Không xác thực được group.")
    return _designer_out(target)


@router.patch("/designers/{user_id}/delivery-mode", response_model=TelegramDesignerOut)
def update_designer_delivery_mode(
    user_id: str,
    payload: DeliveryModeRequest,
    current_admin: User = Depends(require_role(ROLE_ADMIN)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    target = _designer(db, user_id, platform_id)
    if target.role == ROLE_SUPPORT and payload.mode != TELEGRAM_DELIVERY_PRIVATE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Support hiện chỉ nhận candidate qua chat riêng Telegram.")
    if payload.mode == TELEGRAM_DELIVERY_GROUP and not (
        target.telegram_group_chat_id and target.telegram_group_verified
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Hãy lưu và xác thực group trước khi chọn gửi vào group.")
    if payload.mode == TELEGRAM_DELIVERY_PRIVATE and not target.telegram_chat_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Designer này chưa kết nối chat riêng với bot.")
    before = _designer_snapshot(target)
    target.telegram_delivery_mode = payload.mode
    _audit(
        db,
        actor_id=current_admin.id,
        target_user_id=target.id,
        action_type="CHANGE_DESIGNER_DELIVERY_MODE",
        before=before,
        after=_designer_snapshot(target),
    )
    db.commit()
    db.refresh(target)
    return _designer_out(target)


@router.post("/designers/{user_id}/test", response_model=TelegramTestOut)
def send_designer_test_message(
    user_id: str,
    payload: TelegramTestRequest,
    current_admin: User = Depends(require_role(ROLE_ADMIN)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    target_user = _designer(db, user_id, platform_id)
    target = resolve_designer_chat_target(db, target_user)
    if target is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Đích gửi đang chọn chưa được cấu hình hoặc chưa bật thông báo.")
    if not is_telegram_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Bot Telegram chưa được cấu hình token.")
    # The ad-hoc test message is not an editable template. Escape it so an
    # admin cannot accidentally break Telegram's HTML parser with raw input.
    result = send_message(target.chat_id, html.escape(payload.message.strip()), parse_mode="HTML")
    if result is None:
        if target.mode == TELEGRAM_DELIVERY_GROUP:
            target_user.telegram_group_last_error = "Bot không gửi được tin nhắn test vào group."
            db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Bot không gửi được tin nhắn test tới đích đã chọn.")
    return TelegramTestOut(
        ok=True,
        mode=target.mode,
        chat_id=target.chat_id,
        message="Đã gửi tin nhắn test.",
    )


@router.get("/templates", response_model=list[TelegramTemplateOut])
def list_telegram_templates(
    current_admin: User = Depends(require_role(ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    return [TelegramTemplateOut(**template_metadata(db, key)) for key in DEFAULT_TELEGRAM_TEMPLATES]


@router.put("/templates/{template_key}", response_model=TelegramTemplateOut)
def update_telegram_template(
    template_key: str,
    payload: TelegramTemplateUpdate,
    current_admin: User = Depends(require_role(ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    if template_key not in DEFAULT_TELEGRAM_TEMPLATES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy mẫu tin nhắn.")
    body = payload.body.strip()
    try:
        validate_telegram_template_body(template_key, body)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    template = db.query(TelegramMessageTemplate).filter_by(template_key=template_key).one_or_none()
    before = {
        "body": template.body if template else DEFAULT_TELEGRAM_TEMPLATES[template_key]["body"],
        "version": template.version if template else 1,
        "active": template.active if template else True,
    }
    if template is None:
        template = TelegramMessageTemplate(
            template_key=template_key,
            audience=DEFAULT_TELEGRAM_TEMPLATES[template_key]["audience"],
            body=body,
            active=True,
            version=1,
            updated_by_id=current_admin.id,
        )
        db.add(template)
    else:
        template.body = body
        template.version += 1
        template.updated_by_id = current_admin.id
    db.flush()
    after = {"body": template.body, "version": template.version, "active": template.active}
    _audit(
        db,
        actor_id=current_admin.id,
        action_type="UPDATE_TELEGRAM_TEMPLATE",
        template_key=template_key,
        before=before,
        after=after,
    )
    db.commit()
    db.refresh(template)
    return TelegramTemplateOut(**template_metadata(db, template_key))


@router.post("/templates/{template_key}/reset", response_model=TelegramTemplateOut)
def reset_telegram_template(
    template_key: str,
    current_admin: User = Depends(require_role(ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    if template_key not in DEFAULT_TELEGRAM_TEMPLATES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy mẫu tin nhắn.")
    template = db.query(TelegramMessageTemplate).filter_by(template_key=template_key).one_or_none()
    before = {
        "body": template.body if template else DEFAULT_TELEGRAM_TEMPLATES[template_key]["body"],
        "version": template.version if template else 1,
        "active": template.active if template else True,
    }
    if template is not None:
        db.delete(template)
        db.flush()
    default_body = DEFAULT_TELEGRAM_TEMPLATES[template_key]["body"]
    _audit(
        db,
        actor_id=current_admin.id,
        action_type="RESET_TELEGRAM_TEMPLATE",
        template_key=template_key,
        before=before,
        after={"body": default_body, "version": 1, "active": True},
    )
    db.commit()
    return TelegramTemplateOut(**template_metadata(db, template_key))


@router.post("/templates/{template_key}/preview", response_model=TelegramTemplatePreviewOut)
def preview_telegram_template(
    template_key: str,
    payload: TelegramTemplatePreviewRequest,
    current_admin: User = Depends(require_role(ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    if template_key not in DEFAULT_TELEGRAM_TEMPLATES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy mẫu tin nhắn.")
    context = {
        "product_name": "Sản phẩm mẫu",
        "deadline": "22/09/2026 18:00",
        "admin_note": "Ghi chú Admin mẫu",
        "fix_count": "2",
        "order_count": "10",
        "total_amount": "400.000 VNĐ",
        "time": "22/09/2026 12:00",
        "order_code": "DJ0000000",
        "designer_name": "Designer mẫu",
        "qc_note": "Ghi chú QC mẫu",
        "submission_link": "https://drive.google.com/example",
        "title": "Cảnh báo mẫu",
        "platform_name": "Acc Mẹ mẫu",
        "message": "Nội dung cảnh báo mẫu",
        "matched_order_code": "DJ0000001",
        "matched_product_name": "Sản phẩm lịch sử mẫu",
        "similarity": "0.9234",
        "classifier": "TRUNG",
    }
    context.update(payload.context)
    try:
        rendered = render_telegram_template(
            db,
            template_key,
            context,
            body_override=payload.body.strip() if payload.body is not None else None,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return TelegramTemplatePreviewOut(template_key=template_key, rendered=rendered)

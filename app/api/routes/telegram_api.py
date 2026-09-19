from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.db.models import Order, TelegramActionLog, User, WorkflowEvent
from app.api.deps import get_current_user, get_db
from app.application.telegram_service import (
    generate_telegram_link_code,
    get_bot_username,
    is_telegram_configured,
    link_telegram_account,
    send_message,
    unlink_telegram_account,
)
from app.config import get_settings
from app.domain.models import OrderState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])


class TelegramStatusResponse(BaseModel):
    is_configured: bool
    bot_username: str | None
    is_linked: bool
    telegram_chat_id: str | None
    telegram_username: str | None
    notifications_enabled: bool


class TelegramLinkCodeResponse(BaseModel):
    ok: bool
    code: str
    link_url: str | None
    bot_username: str | None
    expires_in_seconds: int
    is_linked: bool


@router.get("/status", response_model=TelegramStatusResponse)
def api_telegram_status(user: User = Depends(get_current_user)):
    """Check if Telegram is configured and if the current user is linked."""
    return TelegramStatusResponse(
        is_configured=is_telegram_configured(),
        bot_username=get_bot_username() or None,
        is_linked=bool(user.telegram_chat_id),
        telegram_chat_id=user.telegram_chat_id,
        telegram_username=user.telegram_username,
        notifications_enabled=user.telegram_notifications_enabled,
    )


@router.post("/link-code", response_model=TelegramLinkCodeResponse)
def api_telegram_link_code(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a time-limited OTP link code to connect Telegram."""
    data = generate_telegram_link_code(db, user)
    return TelegramLinkCodeResponse(**data)


@router.post("/unlink")
def api_telegram_unlink(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Unlink Telegram account from current user."""
    return unlink_telegram_account(db, user)


@router.post("/webhook")
async def api_telegram_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    """Webhook for Telegram Bot updates (/start link codes and inline callbacks)."""
    settings = get_settings()
    if settings.telegram_webhook_secret and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid webhook secret")

    body: dict[str, Any] = await request.json()
    logger.debug("Received Telegram webhook update: %s", body)

    # 1. Handle incoming text message (e.g. /start <code>)
    message = body.get("message")
    if message:
        chat = message.get("chat", {})
        chat_id = str(chat.get("id"))
        text = str(message.get("text") or "").strip()
        from_user = message.get("from", {})
        tg_username = from_user.get("username")

        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            if len(parts) > 1:
                link_code = parts[1].strip()
                ok, msg, linked_user = link_telegram_account(db, link_code, chat_id, tg_username)
                if ok and linked_user:
                    welcome_text = (
                        f"🎉 <b>KẾT NỐI THÀNH CÔNG!</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"Xin chào <b>{linked_user.full_name}</b> (@{linked_user.username})!\n"
                        f"Tài khoản của bạn đã được kết nối với hệ thống.\n\n"
                        f"🔔 Bạn sẽ nhận được các thông báo kịp thời khi có đơn mới, đơn cần sửa gấp hoặc thanh toán tiền công."
                    )
                    send_message(chat_id, welcome_text)
                else:
                    send_message(chat_id, f"❌ {msg}")
            else:
                send_message(
                    chat_id,
                    "👋 Chào bạn! Để liên kết tài khoản, vui lòng đăng nhập vào Web và bấm nút <b>Kết nối Telegram</b> trong trang cá nhân.",
                )
            return {"ok": True}

    # 2. Handle Inline Callback Query (Buttons clicked on Telegram)
    callback_query = body.get("callback_query")
    if callback_query:
        cb_data = str(callback_query.get("data") or "")
        from_user = callback_query.get("from", {})
        user_chat_id = str(from_user.get("id"))

        # Verify admin user
        admin_user = (
            db.query(User)
            .filter(User.telegram_chat_id == user_chat_id, User.role == "admin", User.active.is_(True))
            .first()
        )
        if not admin_user:
            logger.warning("Unauthorized callback from chat_id %s", user_chat_id)
            return {"ok": True}

        # Parse callback: appfix:<token> or rejfix:<token>
        if cb_data.startswith("appfix:") or cb_data.startswith("rejfix:"):
            prefix, token = cb_data.split(":", 1)
            action_log = (
                db.query(TelegramActionLog)
                .filter(TelegramActionLog.callback_token == token)
                .first()
            )
            if not action_log or action_log.status != "pending":
                send_message(user_chat_id, "⚠️ Nút bấm này đã được xử lý trước đó hoặc đã hết hạn.")
                return {"ok": True}

            order = db.get(Order, action_log.order_id)
            if not order:
                send_message(user_chat_id, "❌ Không tìm thấy đơn hàng tương ứng.")
                return {"ok": True}

            if prefix == "appfix":
                # Admin accepts fix
                order.state = OrderState.REVISION.value
                order.fix_approved_by_admin = True
                order.status_changed_at = datetime.now(UTC)
                action_log.status = "executed"
                action_log.executed_at = datetime.now(UTC)
                action_log.actor_id = admin_user.id

                # Workflow event
                db.add(
                    WorkflowEvent(
                        order_id=order.id,
                        from_state=OrderState.REVISION.value,
                        to_state=OrderState.REVISION.value,
                        actor_id=admin_user.id,
                        evidence={
                            "action": "APPROVE_FIX_FOR_DESIGNER",
                            "actor_name": admin_user.full_name or admin_user.username,
                            "actor_role": "admin",
                            "source": "telegram_callback",
                            "description": f"Admin {admin_user.full_name} đã chấp nhận Fix qua Telegram",
                        },
                    )
                )
                db.commit()

                # Notify designer
                from app.adapters.db.models import Assignment
                asgn = db.query(Assignment).filter(Assignment.order_id == order.id, Assignment.status != "cancelled").first()
                if asgn and asgn.designer_id:
                    from app.workers.telegram_tasks import async_notify_designer_urgent_fix
                    async_notify_designer_urgent_fix.delay(str(order.id), str(asgn.designer_id), order.designer_note)

                send_message(
                    user_chat_id,
                    f"✅ Đã chấp nhận Fix cho đơn <code>{order.external_order_id}</code> và chuyển tới mục Cần sửa gấp của Designer!",
                )

            elif prefix == "rejfix":
                # Admin rejects fix -> send back to Review
                old_state = order.state
                order.state = OrderState.QC_PENDING.value
                order.fix_approved_by_admin = False
                order.fix_rejected_by_admin = True
                order.status_changed_at = datetime.now(UTC)
                action_log.status = "executed"
                action_log.executed_at = datetime.now(UTC)
                action_log.actor_id = admin_user.id

                db.add(
                    WorkflowEvent(
                        order_id=order.id,
                        from_state=old_state,
                        to_state=OrderState.QC_PENDING.value,
                        actor_id=admin_user.id,
                        evidence={
                            "action": "REJECT_FIX_TO_REVIEW",
                            "actor_name": admin_user.full_name or admin_user.username,
                            "actor_role": "admin",
                            "source": "telegram_callback",
                            "description": f"Admin {admin_user.full_name} đã từ chối Fix qua Telegram và gửi lại Review",
                        },
                    )
                )
                db.commit()

                # Sync to platform
                try:
                    from app.workers.assignment_sync_tasks import (
                        sync_order_review_to_printerval_task,
                    )
                    sync_order_review_to_printerval_task.delay(str(order.id), order.note_outsource, "Review")
                except Exception:
                    pass

                send_message(
                    user_chat_id,
                    f"✅ Đã từ chối Fix cho đơn <code>{order.external_order_id}</code>, chuyển về Review và gửi lại lên Platform!",
                )

    return {"ok": True}

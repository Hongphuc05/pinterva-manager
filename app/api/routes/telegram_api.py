from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.db.models import (
    Assignment,
    Order,
    TelegramActionLog,
    TelegramFixConversation,
    User,
    WorkflowEvent,
)
from app.api.deps import get_current_user, get_db
from app.application.support_compare import (
    ACTION_CHECK_NO as SUPPORT_COMPARE_ACTION_CHECK_NO,
)
from app.application.support_compare import (
    ACTION_CHECK_YES as SUPPORT_COMPARE_ACTION_CHECK_YES,
)
from app.application.support_compare import (
    ACTION_CONFIRM as SUPPORT_COMPARE_ACTION_CONFIRM,
)
from app.application.support_compare import (
    ACTION_REJECT as SUPPORT_COMPARE_ACTION_REJECT,
)
from app.application.support_compare import (
    CALLBACK_CHECK_NO_PREFIX as SUPPORT_COMPARE_CALLBACK_CHECK_NO,
)
from app.application.support_compare import (
    CALLBACK_CHECK_YES_PREFIX as SUPPORT_COMPARE_CALLBACK_CHECK_YES,
)
from app.application.support_compare import (
    CALLBACK_CONFIRM_PREFIX as SUPPORT_COMPARE_CALLBACK_CONFIRM,
)
from app.application.support_compare import (
    CALLBACK_REJECT_PREFIX as SUPPORT_COMPARE_CALLBACK_REJECT,
)
from app.application.support_compare import (
    count_support_unchecked_orders,
    create_support_compare_job,
    execute_support_duplicate_decision,
    new_support_check_actions,
    supersede_support_check_siblings,
    support_check_keyboard,
)
from app.application.telegram_service import (
    clear_message_keyboard,
    delete_messages,
    generate_telegram_link_code,
    get_bot_username,
    is_telegram_configured,
    link_telegram_account,
    send_message,
    unlink_telegram_account,
)
from app.config import get_settings
from app.domain.access import ROLE_SUPPORT
from app.domain.models import OrderState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])


def _track_fix_transient_message(db: Session, order_id, chat_id: str, message_id: int | None) -> None:
    if message_id is None:
        return
    conversation = (
        db.query(TelegramFixConversation)
        .filter_by(order_id=order_id, chat_id=chat_id, status="active")
        .order_by(TelegramFixConversation.created_at.desc())
        .first()
    )
    if conversation is None:
        return
    ids = list(conversation.transient_message_ids or [])
    if message_id not in ids:
        conversation.transient_message_ids = [*ids, message_id]
        db.commit()


def _clean_completed_fix_conversations(db: Session, order_id, extra_message: tuple[str, int] | None = None) -> None:
    """Keep the original Fix card but remove its buttons and all flow chatter."""
    conversations = db.query(TelegramFixConversation).filter_by(order_id=order_id, status="active").all()
    for conversation in conversations:
        keyboard_cleared = clear_message_keyboard(conversation.chat_id, conversation.root_message_id)
        transient = [int(message_id) for message_id in (conversation.transient_message_ids or [])]
        if extra_message and extra_message[0] == conversation.chat_id:
            transient.append(extra_message[1])
        messages_deleted = delete_messages(conversation.chat_id, transient)
        if keyboard_cleared and messages_deleted:
            conversation.status = "cleaned"
            conversation.cleaned_at = datetime.now(UTC)
        else:
            logger.warning("Telegram Fix chat cleanup remains pending for order %s chat %s", order_id, conversation.chat_id)
    if conversations:
        db.commit()


def _action_is_pending_and_valid(action_log: TelegramActionLog, action_type: str) -> bool:
    return (
        action_log.status == "pending"
        and action_log.action_type == action_type
        and (action_log.expires_at is None or action_log.expires_at >= datetime.now(UTC))
    )


def _supersede_sibling_fix_choices(db: Session, action_log: TelegramActionLog) -> None:
    """Ensure only one of the two note choices can release a Fix."""
    parent_action_id = str((action_log.payload or {}).get("parent_action_id") or "")
    if not parent_action_id:
        return
    candidates = (
        db.query(TelegramActionLog)
        .filter(
            TelegramActionLog.status == "pending",
            TelegramActionLog.action_type.in_(("APPROVE_FIX_WRITE_NOTE", "APPROVE_FIX_USE_OUTSOURCE")),
        )
        .all()
    )
    for candidate in candidates:
        if candidate.id != action_log.id and str((candidate.payload or {}).get("parent_action_id") or "") == parent_action_id:
            candidate.status = "superseded"


def _complete_telegram_fix_approval(
    db: Session,
    *,
    order: Order,
    action_log: TelegramActionLog,
    admin_user: User,
    designer_note: str,
    note_mode: str,
) -> str | None:
    """Release a Fix only after its Designer-facing note is decided by Admin."""
    note = designer_note.strip()
    if not note:
        raise ValueError("Ghi chú gửi Designer không được để trống.")

    old_state = order.state
    order.state = OrderState.REVISION.value
    order.fix_approved_by_admin = True
    order.fix_rejected_by_admin = False
    order.designer_note = note
    # Even when Admin chooses the verbatim QC text, it is copied into this
    # Admin-release field. Designer APIs never expose note_outsource itself.
    order.designer_note_released_for_fix = True
    order.suppress_note_outsource_for_designer = True
    order.fix_deadline_at = datetime.now(UTC) + timedelta(hours=1)
    order.deadline_overdue_notified_at = None
    order.status_changed_at = datetime.now(UTC)

    action_log.status = "executed"
    action_log.executed_at = datetime.now(UTC)
    action_log.actor_id = admin_user.id
    _supersede_sibling_fix_choices(db, action_log)

    db.add(
        WorkflowEvent(
            order_id=order.id,
            from_state=old_state,
            to_state=OrderState.REVISION.value,
            actor_id=admin_user.id,
            evidence={
                "action": "APPROVE_FIX_FOR_DESIGNER",
                "actor_name": admin_user.full_name or admin_user.username,
                "actor_role": "admin",
                "source": "telegram_callback",
                "note_mode": note_mode,
                "description": f"Admin {admin_user.full_name or admin_user.username} đã chấp nhận Fix qua Telegram",
            },
        )
    )

    assignment = (
        db.query(Assignment)
        .filter(Assignment.order_id == order.id, Assignment.status != "cancelled")
        .order_by(Assignment.created_at.desc())
        .first()
    )
    designer_id = str(assignment.designer_id) if assignment and assignment.designer_id else None
    db.commit()
    return designer_id


def _notify_telegram_fix_designer(order: Order, designer_id: str | None) -> None:
    if not designer_id:
        return
    from app.workers.telegram_tasks import async_notify_designer_urgent_fix

    async_notify_designer_urgent_fix.delay(str(order.id), designer_id, order.designer_note)


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

        command = text.split(maxsplit=1)[0].lower() if text else ""
        if command.split("@", 1)[0] == "/check":
            support_user = (
                db.query(User)
                .filter(
                    User.telegram_chat_id == chat_id,
                    User.role == ROLE_SUPPORT,
                    User.active.is_(True),
                )
                .first()
            )
            if not support_user:
                send_message(chat_id, "⚠️ Lệnh này chỉ dành cho tài khoản Support đã liên kết với Telegram.")
                return {"ok": True}
            if support_user.platform_id is None:
                send_message(chat_id, "⚠️ Tài khoản Support chưa được gắn platform.")
                return {"ok": True}
            if not settings.support_compare_enabled:
                send_message(chat_id, "⚠️ Chức năng kiểm tra trùng đang tắt trên hệ thống.")
                return {"ok": True}

            order_count = count_support_unchecked_orders(db, platform_id=support_user.platform_id)
            if order_count == 0:
                send_message(
                    chat_id,
                    "📋 Hiện tại có <b>0</b> đơn trong tab <b>Chưa kiểm tra</b>. Không có gì để kiểm tra.",
                )
                return {"ok": True}

            pending_check_actions = (
                db.query(TelegramActionLog)
                .filter(
                    TelegramActionLog.status == "pending",
                    TelegramActionLog.action_type.in_(
                        (SUPPORT_COMPARE_ACTION_CHECK_YES, SUPPORT_COMPARE_ACTION_CHECK_NO)
                    ),
                )
                .all()
            )
            has_pending_prompt = any(
                str((action.payload or {}).get("chat_id") or "") == chat_id
                and _action_is_pending_and_valid(action, action.action_type)
                for action in pending_check_actions
            )
            if has_pending_prompt:
                send_message(chat_id, "⚠️ Bạn đã có một yêu cầu kiểm tra đang chờ xác nhận.")
                return {"ok": True}

            yes_action, no_action = new_support_check_actions(
                platform_id=support_user.platform_id,
                chat_id=chat_id,
                order_count=order_count,
            )
            db.add_all([yes_action, no_action])
            db.commit()
            try:
                prompt = send_message(
                    chat_id,
                    (
                        f"📋 Hiện tại có <b>{order_count}</b> đơn trong tab "
                        "<b>Chưa kiểm tra</b>.\nBạn có muốn kiểm tra trùng không?"
                    ),
                    reply_markup=support_check_keyboard(
                        yes_action.callback_token,
                        no_action.callback_token,
                    ),
                )
            except Exception:
                logger.exception("failed to send Support /check confirmation to %s", chat_id)
                yes_action.status = no_action.status = "failed"
                db.commit()
                return {"ok": True}

            if prompt is None:
                yes_action.status = no_action.status = "failed"
                db.commit()
                return {"ok": True}

            message_id = prompt.get("message_id") if isinstance(prompt, dict) else None
            for action in (yes_action, no_action):
                action.payload = {
                    **(action.payload or {}),
                    "message_id": message_id,
                }
            db.commit()
            return {"ok": True}

        # A note typed by an Admin after choosing “soạn ghi chú” is the final
        # confirmation step for a Telegram Fix approval. Prefer a reply to the
        # bot prompt; accepting a non-reply is safe only when that Admin has
        # exactly one outstanding note request.
        admin_user = (
            db.query(User)
            .filter(User.telegram_chat_id == chat_id, User.role == "admin", User.active.is_(True))
            .first()
        )
        if admin_user and text and not text.startswith("/"):
            pending_logs = (
                db.query(TelegramActionLog)
                .filter(
                    TelegramActionLog.action_type == "AWAIT_ADMIN_FIX_NOTE",
                    TelegramActionLog.status == "pending",
                )
                .order_by(TelegramActionLog.created_at.desc())
                .all()
            )
            pending_logs = [
                log for log in pending_logs
                if str((log.payload or {}).get("chat_id")) == chat_id
            ]
            reply_message_id = (message.get("reply_to_message") or {}).get("message_id")
            if reply_message_id is not None:
                pending_logs = [
                    log for log in pending_logs
                    if (log.payload or {}).get("prompt_message_id") == reply_message_id
                ]

            if len(pending_logs) == 1:
                note_log = pending_logs[0]
                if not _action_is_pending_and_valid(note_log, "AWAIT_ADMIN_FIX_NOTE"):
                    note_log.status = "expired"
                    db.commit()
                    send_message(chat_id, "⚠️ Yêu cầu nhập ghi chú Fix đã hết hạn. Vui lòng xử lý lại từ thông báo Fix.")
                    return {"ok": True}
                order = db.get(Order, note_log.order_id)
                if order is None:
                    note_log.status = "failed"
                    db.commit()
                    send_message(chat_id, "❌ Không tìm thấy đơn hàng cho yêu cầu ghi chú này.")
                    return {"ok": True}
                try:
                    designer_id = _complete_telegram_fix_approval(
                        db,
                        order=order,
                        action_log=note_log,
                        admin_user=admin_user,
                        designer_note=text,
                        note_mode="admin_written",
                    )
                except ValueError as exc:
                    send_message(chat_id, f"⚠️ {exc}")
                    return {"ok": True}
                _notify_telegram_fix_designer(order, designer_id)
                inbound_message_id = message.get("message_id")
                _clean_completed_fix_conversations(
                    db,
                    order.id,
                    (chat_id, int(inbound_message_id)) if inbound_message_id is not None else None,
                )
                return {"ok": True}
            if len(pending_logs) > 1:
                send_message(chat_id, "⚠️ Bạn có nhiều yêu cầu ghi chú Fix. Hãy trả lời trực tiếp vào đúng tin nhắn bot đã hỏi.")
                return {"ok": True}

    # 2. Handle Inline Callback Query (Buttons clicked on Telegram)
    callback_query = body.get("callback_query")
    if callback_query:
        cb_data = str(callback_query.get("data") or "")
        from_user = callback_query.get("from", {})
        user_chat_id = str(from_user.get("id"))

        # Support duplicate-image review callbacks are intentionally handled
        # before the legacy Admin-only Fix callback branch.  The callback still
        # delegates the actual order mutation to the scoped comparison service.
        # The normal Support web command remains Waiting-only; this callback
        # additionally permits an unclassified Doing order from this source.
        check_prefixes = {
            SUPPORT_COMPARE_CALLBACK_CHECK_YES,
            SUPPORT_COMPARE_CALLBACK_CHECK_NO,
        }
        if ":" in cb_data and cb_data.split(":", 1)[0] in check_prefixes:
            prefix, token = cb_data.split(":", 1)
            support_user = (
                db.query(User)
                .filter(
                    User.telegram_chat_id == user_chat_id,
                    User.role == ROLE_SUPPORT,
                    User.active.is_(True),
                )
                .first()
            )
            if not support_user:
                logger.warning("Unauthorized Support /check callback from chat_id %s", user_chat_id)
                return {"ok": True}

            expected_action_type = (
                SUPPORT_COMPARE_ACTION_CHECK_YES
                if prefix == SUPPORT_COMPARE_CALLBACK_CHECK_YES
                else SUPPORT_COMPARE_ACTION_CHECK_NO
            )
            action_log = (
                db.query(TelegramActionLog)
                .filter(TelegramActionLog.callback_token == token)
                .with_for_update()
                .first()
            )
            if not action_log or not _action_is_pending_and_valid(action_log, expected_action_type):
                send_message(user_chat_id, "⚠️ Nút bấm này đã được xử lý trước đó hoặc đã hết hạn.")
                return {"ok": True}

            payload = action_log.payload or {}
            if str(payload.get("chat_id") or "") != user_chat_id:
                logger.warning("Support /check callback chat mismatch for action %s", action_log.id)
                return {"ok": True}
            if str(payload.get("platform_id") or "") != str(support_user.platform_id):
                send_message(user_chat_id, "⚠️ Platform của tài khoản Support đã thay đổi. Hãy gửi lại /check.")
                return {"ok": True}

            if prefix == SUPPORT_COMPARE_CALLBACK_CHECK_NO:
                action_log.status = "executed"
                action_log.executed_at = datetime.now(UTC)
                action_log.actor_id = support_user.id
                supersede_support_check_siblings(db, action_log)
                db.commit()
                message_id = payload.get("message_id")
                if message_id is not None:
                    clear_message_keyboard(user_chat_id, int(message_id))
                send_message(user_chat_id, "✅ Đã hủy kiểm tra trùng.")
                return {"ok": True}

            try:
                job = create_support_compare_job(
                    db,
                    platform_id=support_user.platform_id,
                    requested_by_id=support_user.id,
                    chat_id=user_chat_id,
                    requested_count=int(payload.get("order_count") or 0),
                )
            except Exception:
                db.rollback()
                logger.exception("failed to queue local Support /check comparison for %s", user_chat_id)
                send_message(user_chat_id, "❌ Không thể bắt đầu kiểm tra trùng lúc này. Vui lòng thử lại.")
                return {"ok": True}

            action_log.status = "executed"
            action_log.executed_at = datetime.now(UTC)
            action_log.actor_id = support_user.id
            action_log.payload = {
                **payload,
                "job_id": str(job.id),
            }
            supersede_support_check_siblings(db, action_log)
            db.commit()
            message_id = payload.get("message_id")
            if message_id is not None:
                clear_message_keyboard(user_chat_id, int(message_id))
            order_count = payload.get("order_count", 0)
            send_message(
                user_chat_id,
                f"✅ Đã xếp <b>{order_count}</b> đơn trong tab <b>Chưa kiểm tra</b> "
                "vào hàng đợi máy local để embedding và kiểm tra trùng.\n"
                "Bot sẽ báo cáo và gửi các cặp nghi trùng khi máy local xử lý xong.",
            )
            return {"ok": True}

        support_prefixes = {
            SUPPORT_COMPARE_CALLBACK_CONFIRM,
            SUPPORT_COMPARE_CALLBACK_REJECT,
        }
        if ":" in cb_data and cb_data.split(":", 1)[0] in support_prefixes:
            prefix, token = cb_data.split(":", 1)
            support_user = (
                db.query(User)
                .filter(
                    User.telegram_chat_id == user_chat_id,
                    User.role == ROLE_SUPPORT,
                    User.active.is_(True),
                )
                .first()
            )
            if not support_user:
                logger.warning("Unauthorized Support comparison callback from chat_id %s", user_chat_id)
                return {"ok": True}

            expected_action_type = (
                SUPPORT_COMPARE_ACTION_CONFIRM
                if prefix == SUPPORT_COMPARE_CALLBACK_CONFIRM
                else SUPPORT_COMPARE_ACTION_REJECT
            )
            action_log = (
                db.query(TelegramActionLog)
                .filter(TelegramActionLog.callback_token == token)
                .with_for_update()
                .first()
            )
            if not action_log or not _action_is_pending_and_valid(action_log, expected_action_type):
                send_message(user_chat_id, "⚠️ Nút bấm này đã được xử lý trước đó hoặc đã hết hạn.")
                return {"ok": True}
            if str((action_log.payload or {}).get("chat_id") or "") != user_chat_id:
                logger.warning("Support comparison callback chat mismatch for action %s", action_log.id)
                return {"ok": True}

            decision = "duplicate" if prefix == SUPPORT_COMPARE_CALLBACK_CONFIRM else "non_duplicate"
            try:
                execute_support_duplicate_decision(
                    db,
                    actor=support_user,
                    action_log=action_log,
                    decision_status=decision,
                )
            except ValueError as exc:
                db.rollback()
                send_message(user_chat_id, f"⚠️ {exc}")
                return {"ok": True}

            action_log.status = "executed"
            action_log.executed_at = datetime.now(UTC)
            action_log.actor_id = support_user.id
            db.commit()
            message_id = (action_log.payload or {}).get("message_id")
            if message_id is not None:
                clear_message_keyboard(user_chat_id, int(message_id))
            result_text = "✅ Đã xác nhận: đơn được đưa vào Trùng lặp." if decision == "duplicate" else "✅ Đã xác nhận: Không trùng, đơn không bị đưa vào Trùng lặp."
            send_message(user_chat_id, result_text)
            return {"ok": True}

        # Verify admin user
        admin_user = (
            db.query(User)
            .filter(User.telegram_chat_id == user_chat_id, User.role == "admin", User.active.is_(True))
            .first()
        )
        if not admin_user:
            logger.warning("Unauthorized callback from chat_id %s", user_chat_id)
            return {"ok": True}

        # Parse callback: first choose approve/reject, then (for approval)
        # choose whether to write an Admin note or release the QC text verbatim.
        valid_prefixes = {"appfix", "rejfix", "appfixnote", "appfixsource"}
        if ":" in cb_data and cb_data.split(":", 1)[0] in valid_prefixes:
            prefix, token = cb_data.split(":", 1)
            action_log = (
                db.query(TelegramActionLog)
                .filter(TelegramActionLog.callback_token == token)
                .first()
            )
            expected_action_types = {
                "appfix": "APPROVE_FIX",
                "rejfix": "REJECT_FIX",
                "appfixnote": "APPROVE_FIX_WRITE_NOTE",
                "appfixsource": "APPROVE_FIX_USE_OUTSOURCE",
            }
            if not action_log or not _action_is_pending_and_valid(action_log, expected_action_types[prefix]):
                send_message(user_chat_id, "⚠️ Nút bấm này đã được xử lý trước đó hoặc đã hết hạn.")
                return {"ok": True}

            order = db.get(Order, action_log.order_id)
            if not order:
                send_message(user_chat_id, "❌ Không tìm thấy đơn hàng tương ứng.")
                return {"ok": True}

            if prefix == "appfix":
                # Do not release the Fix yet. Admin must first decide the only
                # Designer-facing note that will be copied into Tacahu.
                action_log.status = "executed"
                action_log.executed_at = datetime.now(UTC)
                action_log.actor_id = admin_user.id
                expires_at = min(
                    action_log.expires_at or (datetime.now(UTC) + timedelta(minutes=30)),
                    datetime.now(UTC) + timedelta(minutes=30),
                )
                write_note_token = secrets.token_urlsafe(16)
                use_source_token = secrets.token_urlsafe(16)
                common_payload = {
                    "order_id": str(order.id),
                    "external_order_id": order.external_order_id,
                    "parent_action_id": str(action_log.id),
                }
                db.add_all([
                    TelegramActionLog(
                        order_id=order.id,
                        action_type="APPROVE_FIX_WRITE_NOTE",
                        callback_token=write_note_token,
                        payload=common_payload,
                        expires_at=expires_at,
                    ),
                    TelegramActionLog(
                        order_id=order.id,
                        action_type="APPROVE_FIX_USE_OUTSOURCE",
                        callback_token=use_source_token,
                        payload=common_payload,
                        expires_at=expires_at,
                    ),
                ])
                db.commit()
                choice_message = send_message(
                    user_chat_id,
                    "📝 <b>Bạn có muốn gửi đè Note Outsource bằng Ghi chú Admin cho Designer không?</b>\n\n"
                    "Nếu chọn <b>Có</b>, bot sẽ yêu cầu bạn soạn Ghi chú Admin. Nếu chọn <b>Không</b>, "
                    "bot sẽ copy nguyên văn Note Outsource vào Ghi chú Admin để gửi Des.",
                    reply_markup={
                        "inline_keyboard": [
                            [{"text": "✍️ Có, soạn Ghi chú Admin", "callback_data": f"appfixnote:{write_note_token}"}],
                            [{"text": "➡️ Không, dùng nguyên văn Note Outsource", "callback_data": f"appfixsource:{use_source_token}"}],
                        ]
                    },
                )
                _track_fix_transient_message(
                    db, order.id, user_chat_id,
                    int(choice_message["message_id"]) if isinstance(choice_message, dict) and choice_message.get("message_id") is not None else None,
                )

            elif prefix == "appfixsource":
                upstream_note = (order.note_outsource or "").strip()
                if not upstream_note:
                    action_log.status = "failed"
                    action_log.executed_at = datetime.now(UTC)
                    action_log.actor_id = admin_user.id
                    db.commit()
                    send_message(user_chat_id, "⚠️ Đơn này không có Note Outsource để gửi. Hãy chọn soạn Ghi chú Admin.")
                    return {"ok": True}
                designer_id = _complete_telegram_fix_approval(
                    db,
                    order=order,
                    action_log=action_log,
                    admin_user=admin_user,
                    designer_note=upstream_note,
                    note_mode="verbatim_upstream_approved_by_admin",
                )
                _notify_telegram_fix_designer(order, designer_id)
                _clean_completed_fix_conversations(db, order.id)

            elif prefix == "appfixnote":
                action_log.status = "executed"
                action_log.executed_at = datetime.now(UTC)
                action_log.actor_id = admin_user.id
                _supersede_sibling_fix_choices(db, action_log)
                note_log = TelegramActionLog(
                    order_id=order.id,
                    action_type="AWAIT_ADMIN_FIX_NOTE",
                    callback_token=secrets.token_urlsafe(16),
                    payload={"order_id": str(order.id), "chat_id": user_chat_id},
                    expires_at=min(
                        action_log.expires_at or (datetime.now(UTC) + timedelta(minutes=30)),
                        datetime.now(UTC) + timedelta(minutes=30),
                    ),
                )
                db.add(note_log)
                db.commit()
                prompt = send_message(
                    user_chat_id,
                    f"✍️ Hãy <b>trả lời tin nhắn này</b> bằng Ghi chú Admin muốn gửi cho Designer của đơn <code>{order.external_order_id}</code>.",
                    reply_markup={"force_reply": True, "input_field_placeholder": "Nhập Ghi chú Admin cho Designer"},
                )
                if isinstance(prompt, dict) and prompt.get("message_id") is not None:
                    note_log.payload = {**(note_log.payload or {}), "prompt_message_id": prompt["message_id"]}
                    db.commit()
                    _track_fix_transient_message(db, order.id, user_chat_id, int(prompt["message_id"]))

            elif prefix == "rejfix":
                # Admin rejects fix -> send back to Review
                old_state = order.state
                order.state = OrderState.QC_PENDING.value
                order.fix_approved_by_admin = False
                order.fix_rejected_by_admin = True
                order.designer_note = ""
                order.designer_note_released_for_fix = False
                order.suppress_note_outsource_for_designer = True
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

                _clean_completed_fix_conversations(db, order.id)

    return {"ok": True}

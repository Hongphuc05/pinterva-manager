from __future__ import annotations

import html
import logging
import re
import secrets
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from app.adapters.db.models import (
    Assignment,
    Order,
    Platform,
    TelegramActionLog,
    TelegramMessageTemplate,
    User,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
VIETNAM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
TELEGRAM_DELIVERY_PRIVATE = "private"
TELEGRAM_DELIVERY_GROUP = "group"
TELEGRAM_TEMPLATE_MAX_LENGTH = 4096
_TEMPLATE_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


DEFAULT_TELEGRAM_TEMPLATES: dict[str, dict[str, Any]] = {
    "designer_new_order": {
        "audience": "designer",
        "body": (
            "🎨 <b>BẠN CÓ ĐƠN HÀNG MỚI (ĐANG LÀM)!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👕 <b>Sản phẩm:</b> {{product_name}}\n"
            "⏰ <b>Hạn chót:</b> {{deadline}}\n"
            "📝 <b>Note Admin:</b> {{admin_note}}"
        ),
        "placeholders": {"product_name", "deadline", "admin_note"},
    },
    "designer_urgent_fix": {
        "audience": "designer",
        "body": (
            "🚨 <b>CẢNH BÁO: ĐƠN CẦN SỬA GẤP (FIX)!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👕 <b>Sản phẩm:</b> {{product_name}}\n"
            "🔄 <b>Lần fix thứ:</b> #{{fix_count}}\n"
            "⏰ <b>Hạn sửa:</b> {{deadline}}\n"
            "📌 <b>Hướng dẫn từ Admin:</b> {{admin_note}}\n"
            "⚡ <i>Vui lòng vào tab <b>Cần sửa gấp</b> trên web để xử lý ngay!</i>"
        ),
        "placeholders": {"product_name", "fix_count", "deadline", "admin_note"},
    },
    "designer_payment": {
        "audience": "designer",
        "body": (
            "💰 <b>THÔNG BÁO THANH TOÁN TIỀN CÔNG</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🎉 Admin vừa duyệt thanh toán tiền công cho bạn!\n"
            "📦 <b>Số lượng đơn:</b> {{order_count}} đơn\n"
            "💵 <b>Tổng tiền công:</b> <b>{{total_amount}}</b>\n"
            "📅 <b>Thời gian:</b> {{time}}\n\n"
            "<i>Cảm ơn bạn đã nỗ lực! Chúc bạn làm việc hiệu quả và nhiều năng lượng!</i>"
        ),
        "placeholders": {"order_count", "total_amount", "time"},
    },
    "admin_new_fix": {
        "audience": "admin",
        "body": (
            "⚠️ <b>CÓ ĐƠN FIX MỚI TỪ PLATFORM!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📦 <b>Mã đơn:</b> <code>{{order_code}}</code>\n"
            "👕 <b>Sản phẩm:</b> {{product_name}}\n"
            "👤 <b>Designer:</b> {{designer_name}}\n"
            "🔄 <b>Lần fix:</b> #{{fix_count}}\n"
            "📝 <b>Ghi chú từ QC:</b> {{qc_note}}\n\n"
            "👉 <i>Admin chọn thao tác xử lý bên dưới:</i>"
        ),
        "placeholders": {"order_code", "product_name", "designer_name", "fix_count", "qc_note"},
    },
    "admin_review_submitted": {
        "audience": "admin",
        "body": (
            "📤 <b>DESIGNER VỪA NỘP BÀI (REVIEW)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📦 <b>Mã đơn:</b> <code>{{order_code}}</code>\n"
            "👕 <b>Sản phẩm:</b> {{product_name}}\n"
            "👤 <b>Designer:</b> {{designer_name}}\n"
            "🔗 <b>Link nộp:</b> {{submission_link}}\n"
            "⏱ <i>Hệ thống đang tự động đồng bộ Review lên Platform.</i>"
        ),
        "placeholders": {"order_code", "product_name", "designer_name", "submission_link"},
    },
    "admin_missing_template": {
        "audience": "admin",
        "body": (
            "🚩 <b>DESIGNER BÁO THIẾU TEMP!</b>\n"
            "📦 <b>Mã đơn:</b> <code>{{order_code}}</code>\n"
            "👤 <b>Designer:</b> {{designer_name}}\n"
            "🕒 <b>Deadline:</b> {{deadline}}\n"
            "👉 Admin bổ sung temp/ghi chú để Designer tiếp tục làm."
        ),
        "placeholders": {"order_code", "designer_name", "deadline"},
    },
    "admin_excessive_fix": {
        "audience": "admin",
        "body": (
            "🚨 <b>CẢNH BÁO CHẤT LƯỢNG (QC ALERT)!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ Đơn <code>{{order_code}}</code> đã bị trả về Fix <b>lần thứ {{fix_count}}</b>!\n"
            "👤 <b>Designer phụ trách:</b> {{designer_name}}\n"
            "💡 <i>Gợi ý: Admin nên can thiệp kiểm tra lại file thiết kế hoặc đổi Designer để tránh trễ hạn.</i>"
        ),
        "placeholders": {"order_code", "fix_count", "designer_name"},
    },
    "admin_deadline_overdue": {
        "audience": "admin",
        "body": (
            "⏰ <b>DESIGNER QUÁ HẠN!</b>\n"
            "👤 <b>Designer:</b> {{designer_name}}\n"
            "📦 <b>Số đơn quá hạn:</b> {{order_count}}\n"
            "👉 Admin kiểm tra và xử lý các đơn trên Tacahu."
        ),
        "placeholders": {"designer_name", "order_count"},
    },
    "admin_system_alert": {
        "audience": "admin",
        "body": (
            "🔥 <b>CẢNH BÁO HỆ THỐNG: {{title}}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🏢 <b>Platform:</b> {{platform_name}}\n"
            "❌ <b>Chi tiết:</b> {{message}}\n"
            "⏰ <b>Thời gian:</b> {{time}}"
        ),
        "placeholders": {"title", "platform_name", "message", "time"},
    },
}


@dataclass(frozen=True)
class TelegramChatTarget:
    chat_id: str
    mode: str
    label: str


@dataclass(frozen=True)
class TelegramGroupInspection:
    ok: bool
    chat_id: str
    chat_type: str | None = None
    title: str | None = None
    error: str | None = None


def format_vietnam_time(value: datetime | None) -> str:
    if value is None:
        return "Không có"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(VIETNAM_TZ).strftime("%d/%m/%Y %H:%M")


def is_telegram_configured() -> bool:
    """Check if telegram bot token is set in settings."""
    settings = get_settings()
    return bool(settings.telegram_bot_token and settings.telegram_bot_token.strip())


def get_bot_username() -> str:
    settings = get_settings()
    return (settings.telegram_bot_username or "").strip().lstrip("@")


def send_telegram_request(
    endpoint: str,
    payload: dict[str, Any],
    *,
    timeout: float = 10.0,
) -> dict[str, Any] | None:
    """Synchronous HTTP call to Telegram Bot API with graceful error handling."""
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token or not token.strip():
        logger.debug("Telegram token not configured; skipping API call to %s", endpoint)
        return None

    url = f"{TELEGRAM_API_BASE}/bot{token.strip()}/{endpoint}"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            data = resp.json()
            if not resp.is_success or not data.get("ok"):
                logger.warning(
                    "Telegram API %s returned error: %s (status %d)",
                    endpoint,
                    data.get("description", resp.text),
                    resp.status_code,
                )
                return None
            return data.get("result")
    except Exception as exc:
        logger.warning("Telegram API request %s failed: %s", endpoint, exc)
        return None


def send_message(
    chat_id: str,
    text: str,
    *,
    parse_mode: str = "HTML",
    reply_markup: dict[str, Any] | None = None,
    disable_web_page_preview: bool = True,
) -> dict[str, Any] | None:
    """Send text message to a specific chat_id."""
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return send_telegram_request("sendMessage", payload)


def clear_message_keyboard(chat_id: str, message_id: int) -> bool:
    return bool(send_telegram_request("editMessageReplyMarkup", {
        "chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []},
    }))


def delete_messages(chat_id: str, message_ids: list[int]) -> bool:
    ids = list(dict.fromkeys(message_ids))
    return not ids or bool(send_telegram_request("deleteMessages", {"chat_id": chat_id, "message_ids": ids}))


def send_photo(
    chat_id: str,
    photo_url: str,
    *,
    caption: str | None = None,
    parse_mode: str = "HTML",
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Send photo with optional caption and buttons."""
    # If photo_url is not a valid public http/https URL, fallback directly to text message
    clean_url = (photo_url or "").strip()
    if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
        if caption:
            return send_message(chat_id, caption, parse_mode=parse_mode, reply_markup=reply_markup)
        return None

    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "photo": clean_url,
        "parse_mode": parse_mode,
    }
    if caption:
        payload["caption"] = caption
    if reply_markup:
        payload["reply_markup"] = reply_markup
    res = send_telegram_request("sendPhoto", payload)
    # If sending photo fails (e.g. invalid url), fallback to sending as text message
    if not res and caption:
        return send_message(chat_id, caption, parse_mode=parse_mode, reply_markup=reply_markup)
    return res


def validate_telegram_template_body(template_key: str, body: str) -> set[str]:
    """Validate an editable body against the server-owned placeholder allowlist."""
    definition = DEFAULT_TELEGRAM_TEMPLATES.get(template_key)
    if definition is None:
        raise ValueError("Mẫu tin nhắn không tồn tại.")
    clean_body = body.strip()
    if not clean_body:
        raise ValueError("Nội dung mẫu tin nhắn không được để trống.")
    if len(clean_body) > TELEGRAM_TEMPLATE_MAX_LENGTH:
        raise ValueError(f"Nội dung mẫu tin nhắn không được dài quá {TELEGRAM_TEMPLATE_MAX_LENGTH} ký tự.")
    placeholders = {match.group(1) for match in _TEMPLATE_PATTERN.finditer(clean_body)}
    unknown = placeholders - set(definition["placeholders"])
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"Placeholder không được phép trong mẫu này: {names}.")
    return placeholders


def render_telegram_template(
    session: Session,
    template_key: str,
    context: dict[str, Any],
    *,
    body_override: str | None = None,
) -> str:
    """Render a stored template while escaping all dynamic values for Telegram HTML."""
    definition = DEFAULT_TELEGRAM_TEMPLATES.get(template_key)
    if definition is None:
        raise ValueError("Mẫu tin nhắn không tồn tại.")
    template = session.query(TelegramMessageTemplate).filter_by(template_key=template_key).one_or_none()
    body = body_override if body_override is not None else (template.body if template else definition["body"])
    validate_telegram_template_body(template_key, body)

    def replace(match: re.Match[str]) -> str:
        value = context.get(match.group(1), "")
        return html.escape(str(value) if value is not None else "")

    return _TEMPLATE_PATTERN.sub(replace, body.strip())


def template_metadata(session: Session, template_key: str) -> dict[str, Any]:
    definition = DEFAULT_TELEGRAM_TEMPLATES.get(template_key)
    if definition is None:
        raise ValueError("Mẫu tin nhắn không tồn tại.")
    stored = session.query(TelegramMessageTemplate).filter_by(template_key=template_key).one_or_none()
    body = stored.body if stored else definition["body"]
    validate_telegram_template_body(template_key, body)
    return {
        "template_key": template_key,
        "audience": definition["audience"],
        "body": body,
        "active": stored.active if stored else True,
        "version": stored.version if stored else 1,
        "updated_by_id": str(stored.updated_by_id) if stored and stored.updated_by_id else None,
        "updated_at": stored.updated_at if stored else None,
        "placeholders": sorted(definition["placeholders"]),
    }


def inspect_telegram_group(chat_id: str) -> TelegramGroupInspection:
    """Verify a group belongs to this bot and the bot can send messages there."""
    clean_chat_id = chat_id.strip()
    if not re.fullmatch(r"-?\d{1,64}", clean_chat_id):
        return TelegramGroupInspection(False, clean_chat_id, error="Group chat ID phải là một số hợp lệ.")
    if not is_telegram_configured():
        return TelegramGroupInspection(False, clean_chat_id, error="Bot Telegram chưa được cấu hình token.")

    chat = send_telegram_request("getChat", {"chat_id": clean_chat_id})
    if not isinstance(chat, dict):
        return TelegramGroupInspection(False, clean_chat_id, error="Không tìm thấy group hoặc bot không truy cập được group.")
    chat_type = str(chat.get("type") or "")
    if chat_type not in {"group", "supergroup"}:
        return TelegramGroupInspection(False, clean_chat_id, chat_type=chat_type, error="ID này không phải group hoặc supergroup.")

    bot = send_telegram_request("getMe", {})
    bot_id = bot.get("id") if isinstance(bot, dict) else None
    if bot_id is None:
        return TelegramGroupInspection(False, clean_chat_id, chat_type=chat_type, error="Không xác định được bot hiện tại.")

    membership = send_telegram_request(
        "getChatMember",
        {"chat_id": clean_chat_id, "user_id": bot_id},
    )
    if not isinstance(membership, dict):
        return TelegramGroupInspection(False, clean_chat_id, chat_type=chat_type, error="Không kiểm tra được quyền của bot trong group.")
    member_status = str(membership.get("status") or "")
    if member_status in {"left", "kicked", ""}:
        return TelegramGroupInspection(False, clean_chat_id, chat_type=chat_type, error="Bot chưa được thêm vào group hoặc đã bị đuổi.")
    if member_status == "restricted" and membership.get("can_send_messages") is False:
        return TelegramGroupInspection(False, clean_chat_id, chat_type=chat_type, error="Bot đang bị hạn chế quyền gửi tin trong group.")

    return TelegramGroupInspection(
        True,
        clean_chat_id,
        chat_type=chat_type,
        title=str(chat.get("title") or chat.get("username") or clean_chat_id),
    )


def resolve_designer_chat_target(session: Session, designer: User) -> TelegramChatTarget | None:
    """Resolve the explicitly selected designer destination without silent fallback."""
    if not designer.telegram_notifications_enabled:
        return None
    if designer.telegram_delivery_mode == TELEGRAM_DELIVERY_GROUP:
        if designer.telegram_group_chat_id and designer.telegram_group_verified:
            return TelegramChatTarget(
                chat_id=designer.telegram_group_chat_id,
                mode=TELEGRAM_DELIVERY_GROUP,
                label=designer.telegram_group_title or designer.telegram_group_chat_id,
            )
        logger.warning(
            "Telegram group destination is not ready for designer %s: group=%s verified=%s error=%s",
            designer.id,
            designer.telegram_group_chat_id,
            designer.telegram_group_verified,
            designer.telegram_group_last_error,
        )
        return None
    if designer.telegram_chat_id:
        return TelegramChatTarget(
            chat_id=designer.telegram_chat_id,
            mode=TELEGRAM_DELIVERY_PRIVATE,
            label=designer.telegram_username or designer.telegram_chat_id,
        )
    return None


def send_designer_notification(
    session: Session,
    designer: User,
    text: str,
    *,
    photo_url: str | None = None,
) -> bool:
    target = resolve_designer_chat_target(session, designer)
    if target is None:
        return False
    result = send_photo(target.chat_id, photo_url, caption=text) if photo_url else send_message(target.chat_id, text)
    if result is None:
        logger.warning(
            "Telegram notification failed for designer=%s mode=%s chat=%s",
            designer.id,
            target.mode,
            target.chat_id,
        )
        return False
    return True


# =========================================================================
# User Linking & Account Management
# =========================================================================

def generate_telegram_link_code(session: Session, user: User) -> dict[str, Any]:
    """Generate a unique time-limited link code for linking Telegram account."""
    code = secrets.token_urlsafe(16)
    user.telegram_link_code = code
    user.telegram_link_code_expires_at = datetime.now(UTC) + timedelta(minutes=15)
    session.add(user)
    session.commit()

    bot_user = get_bot_username()
    link_url = f"https://t.me/{bot_user}?start={code}" if bot_user else None

    return {
        "ok": True,
        "code": code,
        "link_url": link_url,
        "bot_username": bot_user,
        "expires_in_seconds": 900,
        "telegram_chat_id": user.telegram_chat_id,
        "telegram_username": user.telegram_username,
        "is_linked": bool(user.telegram_chat_id),
    }


def link_telegram_account(
    session: Session,
    link_code: str,
    chat_id: str,
    username: str | None = None,
) -> tuple[bool, str, User | None]:
    """Link a Telegram chat_id to the user matching the link_code."""
    user = (
        session.query(User)
        .filter(User.telegram_link_code == link_code)
        .first()
    )
    if not user:
        return False, "Mã liên kết không hợp lệ hoặc không tìm thấy.", None

    if user.telegram_link_code_expires_at and user.telegram_link_code_expires_at < datetime.now(UTC):
        return False, "Mã liên kết đã hết hạn (chỉ có hiệu lực trong 15 phút). Vui lòng tạo mã mới trên web.", None

    user.telegram_chat_id = str(chat_id)
    user.telegram_username = username
    user.telegram_link_code = None
    user.telegram_link_code_expires_at = None
    user.telegram_notifications_enabled = True
    session.add(user)
    session.commit()

    return True, f"Liên kết thành công với tài khoản {user.full_name} ({user.username})!", user


def unlink_telegram_account(session: Session, user: User) -> dict[str, Any]:
    """Unlink Telegram from current user account."""
    user.telegram_chat_id = None
    user.telegram_username = None
    user.telegram_link_code = None
    user.telegram_link_code_expires_at = None
    session.add(user)
    session.commit()
    return {"ok": True, "message": "Đã hủy liên kết Telegram thành công."}


# =========================================================================
# Designer Notifications
# =========================================================================

def notify_designer_new_order(
    session: Session,
    order_id: uuid.UUID,
    designer_id: uuid.UUID,
) -> bool:
    """Notify designer when a new order is assigned (Doing tab)."""
    designer = session.get(User, designer_id)
    if not designer or not resolve_designer_chat_target(session, designer):
        return False

    order = session.get(Order, order_id)
    if not order:
        return False

    text = render_telegram_template(
        session,
        "designer_new_order",
        {
            "product_name": order.product_name or "Sản phẩm",
            "deadline": format_vietnam_time(order.deadline_tacahu),
            "admin_note": order.designer_note or "",
        },
    )

    thumb = order.thumbnail_url or (order.product_image_urls[0] if order.product_image_urls else None)
    return send_designer_notification(session, designer, text, photo_url=thumb)


def notify_designer_urgent_fix(
    session: Session,
    order_id: uuid.UUID,
    designer_id: uuid.UUID,
    admin_note: str | None = None,
) -> bool:
    """Notify designer when an order requires urgent Fix (Admin approved fix)."""
    designer = session.get(User, designer_id)
    if not designer or not resolve_designer_chat_target(session, designer):
        return False

    order = session.get(Order, order_id)
    if not order:
        return False

    fix_cnt = order.fix_return_count or 1
    text = render_telegram_template(
        session,
        "designer_urgent_fix",
        {
            "product_name": order.product_name or "Sản phẩm",
            "fix_count": fix_cnt,
            "deadline": format_vietnam_time(order.fix_deadline_at),
            "admin_note": admin_note or order.designer_note or "Sửa theo yêu cầu của khách",
        },
    )

    thumb = order.thumbnail_url or (order.product_image_urls[0] if order.product_image_urls else None)
    return send_designer_notification(session, designer, text, photo_url=thumb)


def notify_designer_payment(
    session: Session,
    designer_id: uuid.UUID,
    order_count: int,
    total_amount: int,
) -> bool:
    """Notify designer when admin completes payment for their design workload."""
    designer = session.get(User, designer_id)
    if not designer or not resolve_designer_chat_target(session, designer):
        return False

    formatted_money = f"{total_amount:,.0f} VNĐ"
    now_str = format_vietnam_time(datetime.now(UTC))

    text = render_telegram_template(
        session,
        "designer_payment",
        {
            "order_count": order_count,
            "total_amount": formatted_money,
            "time": now_str,
        },
    )
    return send_designer_notification(session, designer, text)


# =========================================================================
# Admin Notifications & Interactive Callbacks
# =========================================================================

def _get_admin_chat_ids(session: Session, platform_id: uuid.UUID | None = None) -> list[str]:
    """Get telegram_chat_ids of all active admins."""
    query = (
        session.query(User.telegram_chat_id)
        .filter(
            User.role == "admin",
            User.active.is_(True),
            User.telegram_chat_id.isnot(None),
            User.telegram_notifications_enabled.is_(True),
        )
    )
    if platform_id:
        query = query.filter((User.platform_id == platform_id) | (User.platform_id.is_(None)))
    return [cid for (cid,) in query.all() if cid]


def _normalize_text(text: str | None) -> str:
    if not text:
        return ""
    nfd = unicodedata.normalize("NFD", text.strip().lower())
    nfd = nfd.replace("đ", "d").replace("Đ", "d")
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def resolve_tacahu_designer_name(session: Session, order: Order | None) -> str:
    """Resolve the assigned designer's name on Tacahu platform for an order.

    1. Query active Assignment in Tacahu for order.id -> User (full_name or username).
    2. If no Assignment, match order.printerval_designer with Tacahu active users.
    3. Fallback to cleaned order.printerval_designer or 'Designer'.
    """
    if not order:
        return "Designer"

    # 1. Check active Assignment on Tacahu
    assignment = (
        session.query(Assignment)
        .filter(Assignment.order_id == order.id, Assignment.status != "cancelled")
        .order_by(Assignment.created_at.desc())
        .first()
    )
    if assignment and assignment.designer_id:
        designer = session.get(User, assignment.designer_id)
        if designer:
            return designer.full_name or designer.username or "Designer"

    # 2. Try matching order.printerval_designer string against Tacahu Users
    raw_p_des = (order.printerval_designer or "").strip()
    if raw_p_des:
        clean_p_des = raw_p_des.split("-")[0].strip() if "-" in raw_p_des else raw_p_des
        norm_clean = _normalize_text(clean_p_des)
        norm_raw = _normalize_text(raw_p_des)

        all_designers = session.query(User).filter(User.active.is_(True)).all()

        for u in all_designers:
            u_full = (u.full_name or "").strip()
            u_user = (u.username or "").strip()
            u_opt = (u.printerval_designer_option or "").strip()

            for val in (u_full, u_user, u_opt):
                if val and (clean_p_des.lower() == val.lower() or raw_p_des.lower() == val.lower()):
                    return u.full_name or u.username

            for val in (u_full, u_user, u_opt):
                if val and (norm_clean == _normalize_text(val) or norm_raw == _normalize_text(val)):
                    return u.full_name or u.username

        if norm_clean:
            tokens = [t for t in norm_clean.split() if len(t) > 1]
            if tokens:
                for u in all_designers:
                    u_norm = _normalize_text(u.full_name or u.username or "")
                    if u_norm and all(t in u_norm for t in tokens):
                        return u.full_name or u.username

        if clean_p_des:
            return clean_p_des

    return "Designer"


def notify_admin_new_fix(session: Session, order_id: uuid.UUID) -> bool:
    """Notify admins when platform returns FIX, with inline buttons to Approve/Reject."""
    order = session.get(Order, order_id)
    if not order:
        return False

    chat_ids = _get_admin_chat_ids(session, order.platform_id)
    if not chat_ids:
        return False

    fix_cnt = order.fix_return_count or 1
    order_id_code = order.external_order_id
    p_name = order.product_name or "Sản phẩm"
    qc_note = order.note_outsource or "Không có ghi chú"
    des_name = resolve_tacahu_designer_name(session, order)

    # Generate callback tokens for Approve / Reject buttons
    approve_token = secrets.token_urlsafe(16)
    reject_token = secrets.token_urlsafe(16)
    expires_at = datetime.now(UTC) + timedelta(hours=48)

    session.add(
        TelegramActionLog(
            order_id=order.id,
            action_type="APPROVE_FIX",
            callback_token=approve_token,
            payload={"order_id": str(order.id), "external_order_id": order.external_order_id},
            expires_at=expires_at,
        )
    )
    session.add(
        TelegramActionLog(
            order_id=order.id,
            action_type="REJECT_FIX",
            callback_token=reject_token,
            payload={"order_id": str(order.id), "external_order_id": order.external_order_id},
            expires_at=expires_at,
        )
    )
    session.commit()

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Chấp nhận Fix & Giao Des", "callback_data": f"appfix:{approve_token}"},
            ],
            [
                {"text": "❌ Từ chối Fix (Về Review)", "callback_data": f"rejfix:{reject_token}"},
            ],
        ]
    }

    text = render_telegram_template(
        session,
        "admin_new_fix",
        {
            "order_code": order_id_code,
            "product_name": p_name,
            "designer_name": des_name,
            "fix_count": fix_cnt,
            "qc_note": qc_note,
        },
    )

    thumb = order.thumbnail_url or (order.product_image_urls[0] if order.product_image_urls else None)
    deliveries = []
    for cid in chat_ids:
        if thumb:
            result = send_photo(cid, thumb, caption=text, reply_markup=reply_markup)
        else:
            result = send_message(cid, text, reply_markup=reply_markup)
        if isinstance(result, dict) and result.get("message_id") is not None:
            deliveries.append((cid, int(result["message_id"])))
    if deliveries:
        from app.adapters.db.models import TelegramFixConversation
        session.add_all(TelegramFixConversation(order_id=order.id, chat_id=chat_id, root_message_id=message_id) for chat_id, message_id in deliveries)
        session.commit()
    return True


def notify_admin_review_submitted(
    session: Session,
    order_id: uuid.UUID,
    designer_name: str,
) -> bool:
    """Notify admins when designer submits a task to Review."""
    order = session.get(Order, order_id)
    if not order:
        return False

    chat_ids = _get_admin_chat_ids(session, order.platform_id)
    if not chat_ids:
        return False

    text = render_telegram_template(
        session,
        "admin_review_submitted",
        {
            "order_code": order.external_order_id,
            "product_name": order.product_name or "Sản phẩm",
            "designer_name": designer_name,
            "submission_link": order.note_outsource or "Chưa có link",
        },
    )
    for cid in chat_ids:
        send_message(cid, text)
    return True


def notify_admin_deadline_overdue_by_designer(session: Session, orders: list[Order]) -> None:
    """Send one overdue summary per Designer instead of one message per order.

    Orders must already have been selected by the periodic deadline scanner.  A
    platform is part of the grouping key so an Admin only receives summaries for
    the platform they are allowed to manage.
    """
    if not orders:
        return

    order_ids = [order.id for order in orders]
    assignments = (
        session.query(Assignment)
        .filter(Assignment.order_id.in_(order_ids), Assignment.status == "approved")
        .all()
    )
    assignment_by_order = {assignment.order_id: assignment for assignment in assignments}
    designer_ids = {assignment.designer_id for assignment in assignments}
    designers_by_id = {
        designer.id: designer
        for designer in session.query(User).filter(User.id.in_(designer_ids)).all()
    } if designer_ids else {}

    grouped_orders: dict[tuple[uuid.UUID | None, str], list[Order]] = {}
    for order in orders:
        assignment = assignment_by_order.get(order.id)
        designer = designers_by_id.get(assignment.designer_id) if assignment else None
        designer_name = (
            (designer.full_name or designer.username)
            if designer
            else (order.printerval_designer or "Chưa rõ")
        )
        grouped_orders.setdefault((order.platform_id, designer_name), []).append(order)

    for (platform_id, designer_name), designer_orders in grouped_orders.items():
        chat_ids = _get_admin_chat_ids(session, platform_id)
        if not chat_ids:
            continue
        text = render_telegram_template(
            session,
            "admin_deadline_overdue",
            {
                "designer_name": designer_name,
                "order_count": len(designer_orders),
            },
        )
        for cid in chat_ids:
            send_message(cid, text)


def notify_admin_deadline_overdue(session: Session, order_id: uuid.UUID) -> bool:
    """Backward-compatible single-order entry point for non-periodic callers."""
    order = session.get(Order, order_id)
    if order is None:
        return False
    notify_admin_deadline_overdue_by_designer(session, [order])
    return True


def notify_admin_missing_template(session: Session, order_id: uuid.UUID, designer_id: uuid.UUID) -> bool:
    order = session.get(Order, order_id)
    designer = session.get(User, designer_id)
    if order is None or designer is None:
        return False
    chat_ids = _get_admin_chat_ids(session, order.platform_id)
    if not chat_ids:
        return False
    text = render_telegram_template(
        session,
        "admin_missing_template",
        {
            "order_code": order.external_order_id,
            "designer_name": designer.full_name or designer.username,
            "deadline": format_vietnam_time(order.deadline_tacahu),
        },
    )
    for cid in chat_ids:
        send_message(cid, text)
    return True


def notify_admin_excessive_fix(
    session: Session,
    order_id: uuid.UUID,
    designer_name: str | None = None,
    fix_count: int = 3,
) -> bool:
    """Alert admins when an order is returned for Fix 3+ times."""
    order = session.get(Order, order_id)
    if not order:
        return False

    chat_ids = _get_admin_chat_ids(session, order.platform_id)
    if not chat_ids:
        return False

    resolved_designer = resolve_tacahu_designer_name(session, order)
    if designer_name and designer_name not in (order.printerval_designer, "Designer", ""):
        display_designer = designer_name
    else:
        display_designer = resolved_designer

    text = render_telegram_template(
        session,
        "admin_excessive_fix",
        {
            "order_code": order.external_order_id,
            "fix_count": fix_count,
            "designer_name": display_designer,
        },
    )
    for cid in chat_ids:
        send_message(cid, text)
    return True


def notify_admin_system_alert(
    session: Session,
    platform_id: uuid.UUID | None,
    title: str,
    message: str,
) -> bool:
    """Alert admins about system errors (cookie expired, crawl failed, etc.)."""
    chat_ids = _get_admin_chat_ids(session, platform_id)
    if not chat_ids:
        return False

    plat_name = "Toàn hệ thống"
    if platform_id:
        plat = session.get(Platform, platform_id)
        if plat:
            plat_name = plat.name

    text = render_telegram_template(
        session,
        "admin_system_alert",
        {
            "title": title,
            "platform_name": plat_name,
            "message": message,
            "time": datetime.now(UTC).strftime("%d/%m/%Y %H:%M:%S UTC"),
        },
    )
    for cid in chat_ids:
        send_message(cid, text)
    return True

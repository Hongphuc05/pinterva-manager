from __future__ import annotations

import html
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.adapters.db.models import Order, Platform, TelegramActionLog, User
from app.config import get_settings

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


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


def send_photo(
    chat_id: str,
    photo_url: str,
    *,
    caption: str | None = None,
    parse_mode: str = "HTML",
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Send photo with optional caption and buttons."""
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "photo": photo_url,
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
    if not designer or not designer.telegram_chat_id or not designer.telegram_notifications_enabled:
        return False

    order = session.get(Order, order_id)
    if not order:
        return False

    p_name = html.escape(order.product_name or "Sản phẩm")
    order_id_code = html.escape(order.external_order_id)
    deadline_str = order.deadline_at_ext.strftime("%d/%m/%Y %H:%M") if order.deadline_at_ext else "Không có"

    text = (
        f"🎨 <b>BẠN CÓ ĐƠN HÀNG MỚI (DOING)!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Mã đơn:</b> <code>{order_id_code}</code>\n"
        f"👕 <b>Sản phẩm:</b> {p_name}\n"
        f"⏰ <b>Hạn chót:</b> {deadline_str}\n"
    )
    if order.designer_note:
        text += f"📝 <b>Note Admin:</b> {html.escape(order.designer_note)}\n"

    thumb = order.thumbnail_url or (order.product_image_urls[0] if order.product_image_urls else None)
    if thumb:
        send_photo(designer.telegram_chat_id, thumb, caption=text)
    else:
        send_message(designer.telegram_chat_id, text)
    return True


def notify_designer_urgent_fix(
    session: Session,
    order_id: uuid.UUID,
    designer_id: uuid.UUID,
    admin_note: str | None = None,
) -> bool:
    """Notify designer when an order requires urgent Fix (Admin approved fix)."""
    designer = session.get(User, designer_id)
    if not designer or not designer.telegram_chat_id or not designer.telegram_notifications_enabled:
        return False

    order = session.get(Order, order_id)
    if not order:
        return False

    order_id_code = html.escape(order.external_order_id)
    p_name = html.escape(order.product_name or "Sản phẩm")
    fix_cnt = order.fix_return_count or 1
    qc_note = html.escape(order.note_outsource or "Không có note chi tiết")
    adm_note = html.escape(admin_note or order.designer_note or "Sửa theo yêu cầu của khách")

    text = (
        f"🚨 <b>CẢNH BÁO: ĐƠN CẦN SỬA GẤP (FIX)!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Mã đơn:</b> <code>{order_id_code}</code>\n"
        f"👕 <b>Sản phẩm:</b> {p_name}\n"
        f"🔄 <b>Lần fix thứ:</b> #{fix_cnt}\n"
        f"💬 <b>Yêu cầu của khách/QC:</b> {qc_note}\n"
        f"📌 <b>Hướng dẫn từ Admin:</b> {adm_note}\n"
        f"⚡ <i>Vui lòng vào tab <b>Cần sửa gấp</b> trên web để xử lý ngay!</i>"
    )

    thumb = order.thumbnail_url or (order.product_image_urls[0] if order.product_image_urls else None)
    if thumb:
        send_photo(designer.telegram_chat_id, thumb, caption=text)
    else:
        send_message(designer.telegram_chat_id, text)
    return True


def notify_designer_payment(
    session: Session,
    designer_id: uuid.UUID,
    order_count: int,
    total_amount: int,
) -> bool:
    """Notify designer when admin completes payment for their design workload."""
    designer = session.get(User, designer_id)
    if not designer or not designer.telegram_chat_id or not designer.telegram_notifications_enabled:
        return False

    formatted_money = f"{total_amount:,.0f} VNĐ"
    now_str = datetime.now(UTC).strftime("%d/%m/%Y %H:%M")

    text = (
        f"💰 <b>THÔNG BÁO THANH TOÁN TIỀN CÔNG</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎉 Admin vừa duyệt thanh toán tiền công cho bạn!\n"
        f"📦 <b>Số lượng đơn:</b> {order_count} đơn\n"
        f"💵 <b>Tổng tiền công:</b> <b>{formatted_money}</b>\n"
        f"📅 <b>Thời gian:</b> {now_str}\n\n"
        f"<i>Cảm ơn bạn đã nỗ lực! Chúc bạn làm việc hiệu quả và nhiều năng lượng!</i>"
    )
    send_message(designer.telegram_chat_id, text)
    return True


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


def notify_admin_new_fix(session: Session, order_id: uuid.UUID) -> bool:
    """Notify admins when platform returns FIX, with inline buttons to Approve/Reject."""
    order = session.get(Order, order_id)
    if not order:
        return False

    chat_ids = _get_admin_chat_ids(session, order.platform_id)
    if not chat_ids:
        return False

    order_id_code = html.escape(order.external_order_id)
    p_name = html.escape(order.product_name or "Sản phẩm")
    fix_cnt = order.fix_return_count or 1
    qc_note = html.escape(order.note_outsource or "Không có ghi chú")
    des_name = html.escape(order.printerval_designer or "Chưa rõ")

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

    text = (
        f"⚠️ <b>CÓ ĐƠN FIX MỚI TỪ PLATFORM!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Mã đơn:</b> <code>{order_id_code}</code>\n"
        f"👕 <b>Sản phẩm:</b> {p_name}\n"
        f"👤 <b>Designer:</b> {des_name}\n"
        f"🔄 <b>Lần fix:</b> #{fix_cnt}\n"
        f"📝 <b>Ghi chú từ QC:</b> {qc_note}\n\n"
        f"👉 <i>Admin chọn thao tác xử lý bên dưới:</i>"
    )

    thumb = order.thumbnail_url or (order.product_image_urls[0] if order.product_image_urls else None)
    for cid in chat_ids:
        if thumb:
            send_photo(cid, thumb, caption=text, reply_markup=reply_markup)
        else:
            send_message(cid, text, reply_markup=reply_markup)
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

    order_id_code = html.escape(order.external_order_id)
    p_name = html.escape(order.product_name or "Sản phẩm")
    link = html.escape(order.note_outsource or "Chưa có link")

    text = (
        f"📤 <b>DESIGNER VỪA NỘP BÀI (REVIEW)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Mã đơn:</b> <code>{order_id_code}</code>\n"
        f"👕 <b>Sản phẩm:</b> {p_name}\n"
        f"👤 <b>Designer:</b> {html.escape(designer_name)}\n"
        f"🔗 <b>Link nộp:</b> {link}\n"
        f"⏱ <i>Hệ thống đang tự động đồng bộ Review lên Platform.</i>"
    )
    for cid in chat_ids:
        send_message(cid, text)
    return True


def notify_admin_excessive_fix(
    session: Session,
    order_id: uuid.UUID,
    designer_name: str,
    fix_count: int,
) -> bool:
    """Alert admins when an order is returned for Fix 3+ times."""
    order = session.get(Order, order_id)
    if not order:
        return False

    chat_ids = _get_admin_chat_ids(session, order.platform_id)
    if not chat_ids:
        return False

    order_id_code = html.escape(order.external_order_id)

    text = (
        f"🚨 <b>CẢNH BÁO CHẤT LƯỢNG (QC ALERT)!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ Đơn <code>{order_id_code}</code> đã bị trả về Fix <b>lần thứ {fix_count}</b>!\n"
        f"👤 <b>Designer phụ trách:</b> {html.escape(designer_name)}\n"
        f"💡 <i>Gợi ý: Admin nên can thiệp kiểm tra lại file thiết kế hoặc đổi Designer để tránh trễ hạn.</i>"
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

    text = (
        f"🔥 <b>CẢNH BÁO HỆ THỐNG: {html.escape(title)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏢 <b>Platform:</b> {html.escape(plat_name)}\n"
        f"❌ <b>Chi tiết:</b> {html.escape(message)}\n"
        f"⏰ <b>Thời gian:</b> {datetime.now(UTC).strftime('%d/%m/%Y %H:%M:%S UTC')}"
    )
    for cid in chat_ids:
        send_message(cid, text)
    return True

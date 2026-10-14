"""Read-only view of the Printerval per-order chat (mirrored by ``order_chat``)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.adapters.db.models import Order, User
from app.api.deps import get_current_platform_id, get_current_user, get_db
from app.application import order_chat as chat
from app.application.order_queries import get_order_detail_for_user
from app.config import get_settings

router = APIRouter(tags=["order-chat"])


def _chat_order(db: Session, user: User, order_id: str, platform_id: uuid.UUID) -> Order:
    order = get_order_detail_for_user(db, user, order_id)
    if order is None or (order.platform_id is not None and order.platform_id != platform_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")
    if not chat.can_read_chat(db, user, order):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bạn không có quyền xem chat của đơn này")
    return order


@router.get("/orders/{order_id}/chat")
def get_order_chat(
    order_id: str,
    user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    order = _chat_order(db, user, order_id, platform_id)
    fresh = True
    if get_settings().order_chat_enabled:
        fresh = chat.refresh_order_if_stale(db, order)
    messages = chat.list_messages(db, order)
    return {
        "order_id": str(order.id),
        "stale": not fresh,
        "last_read_external_id": chat.last_read(db, order, user),
        "messages": [
            {
                "id": m.external_id,
                "type": m.message_type,
                "sender_type": m.sender_type,
                "sender_name": m.sender_name,
                "mine": m.mine,
                "content": m.content,
                "image_urls": m.image_urls,
                "fix_round": m.fix_round,
                "fix_reason_label": m.fix_reason_label,
                "sent_at": m.sent_at,
            }
            for m in messages
        ],
    }


@router.post("/orders/{order_id}/chat/read")
def mark_order_chat_read(
    order_id: str,
    user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    order = _chat_order(db, user, order_id, platform_id)
    return {"last_read_external_id": chat.mark_read(db, order, user)}


@router.get("/chat/unread")
def chat_unread(
    user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Orders with Printerval-side messages the caller has not seen (toasts and list badges)."""
    return {"items": chat.unread_for_user(db, user, platform_id)}

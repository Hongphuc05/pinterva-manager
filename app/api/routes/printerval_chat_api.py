"""Printerval's per-order chat for Admin (see ``printerval_chat``): read live, never stored."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.adapters.db.models import Order, Platform, User
from app.api.deps import get_current_platform_id, get_db, require_role
from app.application.printerval_chat import (
    fetch_messages,
    numeric_job_id,
    read_fix_chat_text,
    unread_orders,
)
from app.config import get_settings
from app.domain.access import ROLE_ADMIN

logger = logging.getLogger(__name__)
router = APIRouter(tags=["printerval-chat"])


def _platform(db: Session, platform_id: uuid.UUID) -> Platform:
    platform = db.get(Platform, platform_id)
    if platform is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy platform")
    return platform


@router.get("/orders/{order_id}/printerval-chat")
def order_printerval_chat(
    order_id: uuid.UUID,
    _user: User = Depends(require_role(ROLE_ADMIN)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The whole conversation of one order, fetched now. Printerval marks it read for its team."""
    order = db.get(Order, order_id)
    if order is None or order.platform_id != platform_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")
    job_id = numeric_job_id(order)
    if job_id is None:
        return {"messages": []}
    try:
        return {"messages": fetch_messages(_platform(db, platform_id), job_id)}
    except Exception as exc:
        logger.warning("Printerval chat of %s could not be read: %s", order.external_order_id, exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Không tải được chat từ Printerval, thử lại sau") from exc


@router.get("/orders/{order_id}/fix-chat")
def order_fix_chat(
    order_id: uuid.UUID,
    _user: User = Depends(require_role(ROLE_ADMIN)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """QC's messages of the order's latest Fix round, for the Accept Fix dialogs (null when none)."""
    order = db.get(Order, order_id)
    if order is None or order.platform_id != platform_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")
    return {"text": read_fix_chat_text(db, order)}


@router.get("/printerval-chat/unread")
def printerval_chat_unread(
    _user: User = Depends(require_role(ROLE_ADMIN)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Orders with messages still unread on Printerval; empty (stale) when Printerval cannot be reached."""
    if not get_settings().order_chat_enabled:
        return {"items": [], "stale": False}
    try:
        return {"items": unread_orders(db, _platform(db, platform_id)), "stale": False}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Printerval unread chat list unavailable: %s", exc)
        return {"items": [], "stale": True}

"""Read an order's Printerval chat once when its Printerval status moves to Fix/Confirm/Done."""

from __future__ import annotations

import logging
import threading
import uuid

from app.adapters.db.models import Order
from app.adapters.db.session import SessionLocal
from app.application.printerval_chat import capture_chat
from app.application.telegram_service import is_telegram_configured, notify_admin_new_fix
from app.config import get_settings
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

CAPTURE_RETRY_DELAYS = (120, 300)


@celery_app.task(bind=True, name="app.workers.printerval_chat_tasks.capture_order_chat")
def capture_order_chat(self, order_id: str, status: str, notify: bool = True) -> None:
    """Store the order's new chat messages; for Fix, then send the Admin's Telegram card.

    The card goes out after the first attempt whether or not the chat could be read (it then points
    to the chat on Tacahu), so a slow Printerval never delays it; a failed read is retried alone.
    """
    session = SessionLocal()
    failed = False
    try:
        order = session.get(Order, uuid.UUID(order_id))
        if order is None:
            return
        try:
            if capture_chat(session, order, status):
                session.commit()
        except Exception:
            session.rollback()
            failed = True
            logger.warning("Could not read the Printerval chat of %s (%s)", order.external_order_id, status, exc_info=True)
        if notify and status == "fix" and is_telegram_configured():
            try:
                notify_admin_new_fix(session, order.id)
            except Exception:
                logger.exception("Failed to notify the Fix of order %s", order_id)
    finally:
        session.close()
    if failed and self.request.retries < len(CAPTURE_RETRY_DELAYS):
        raise self.retry(countdown=CAPTURE_RETRY_DELAYS[self.request.retries], kwargs={"notify": False})


def dispatch_chat_capture(order_id: uuid.UUID, status: str, notify: bool = False) -> None:
    """Queue the chat read for an order whose Printerval status just changed (never raises)."""
    if not get_settings().order_chat_enabled:
        return
    try:
        capture_order_chat.delay(str(order_id), status, notify)
    except Exception as exc:
        logger.warning("Celery dispatch failed for the chat read of %s: %s", order_id, exc)
        try:
            threading.Thread(target=capture_order_chat.run, args=(str(order_id), status, notify), daemon=True).start()
        except Exception:
            logger.exception("Background thread fallback failed for the chat read of %s", order_id)

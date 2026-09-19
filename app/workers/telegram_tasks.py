from __future__ import annotations

import logging
import uuid

from app.adapters.db.session import SessionLocal
from app.application.telegram_service import (
    is_telegram_configured,
    notify_admin_excessive_fix,
    notify_admin_new_fix,
    notify_admin_review_submitted,
    notify_admin_system_alert,
    notify_designer_new_order,
    notify_designer_payment,
    notify_designer_urgent_fix,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.telegram_tasks.async_notify_designer_new_order")
def async_notify_designer_new_order(order_id_str: str, designer_id_str: str) -> None:
    if not is_telegram_configured():
        return
    session = SessionLocal()
    try:
        notify_designer_new_order(session, uuid.UUID(order_id_str), uuid.UUID(designer_id_str))
    except Exception:
        logger.exception("Failed to async_notify_designer_new_order for order %s", order_id_str)
    finally:
        session.close()


@celery_app.task(name="app.workers.telegram_tasks.async_notify_designer_urgent_fix")
def async_notify_designer_urgent_fix(
    order_id_str: str, designer_id_str: str, admin_note: str | None = None
) -> None:
    if not is_telegram_configured():
        return
    session = SessionLocal()
    try:
        notify_designer_urgent_fix(session, uuid.UUID(order_id_str), uuid.UUID(designer_id_str), admin_note)
    except Exception:
        logger.exception("Failed to async_notify_designer_urgent_fix for order %s", order_id_str)
    finally:
        session.close()


@celery_app.task(name="app.workers.telegram_tasks.async_notify_designer_payment")
def async_notify_designer_payment(designer_id_str: str, order_count: int, total_amount: int) -> None:
    if not is_telegram_configured():
        return
    session = SessionLocal()
    try:
        notify_designer_payment(session, uuid.UUID(designer_id_str), order_count, total_amount)
    except Exception:
        logger.exception("Failed to async_notify_designer_payment for designer %s", designer_id_str)
    finally:
        session.close()


@celery_app.task(name="app.workers.telegram_tasks.async_notify_admin_new_fix")
def async_notify_admin_new_fix(order_id_str: str) -> None:
    if not is_telegram_configured():
        return
    session = SessionLocal()
    try:
        notify_admin_new_fix(session, uuid.UUID(order_id_str))
    except Exception:
        logger.exception("Failed to async_notify_admin_new_fix for order %s", order_id_str)
    finally:
        session.close()


@celery_app.task(name="app.workers.telegram_tasks.async_notify_admin_review_submitted")
def async_notify_admin_review_submitted(order_id_str: str, designer_name: str) -> None:
    if not is_telegram_configured():
        return
    session = SessionLocal()
    try:
        notify_admin_review_submitted(session, uuid.UUID(order_id_str), designer_name)
    except Exception:
        logger.exception("Failed to async_notify_admin_review_submitted for order %s", order_id_str)
    finally:
        session.close()


@celery_app.task(name="app.workers.telegram_tasks.async_notify_admin_excessive_fix")
def async_notify_admin_excessive_fix(order_id_str: str, designer_name: str, fix_count: int) -> None:
    if not is_telegram_configured():
        return
    session = SessionLocal()
    try:
        notify_admin_excessive_fix(session, uuid.UUID(order_id_str), designer_name, fix_count)
    except Exception:
        logger.exception("Failed to async_notify_admin_excessive_fix for order %s", order_id_str)
    finally:
        session.close()


@celery_app.task(name="app.workers.telegram_tasks.async_notify_admin_system_alert")
def async_notify_admin_system_alert(platform_id_str: str | None, title: str, message: str) -> None:
    if not is_telegram_configured():
        return
    session = SessionLocal()
    try:
        plat_uuid = uuid.UUID(platform_id_str) if platform_id_str else None
        notify_admin_system_alert(session, plat_uuid, title, message)
    except Exception:
        logger.exception("Failed to async_notify_admin_system_alert: %s", title)
    finally:
        session.close()

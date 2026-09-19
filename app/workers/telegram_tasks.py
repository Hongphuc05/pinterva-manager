import logging
import threading
import uuid
from datetime import UTC, datetime

from app.adapters.db.models import Order
from app.adapters.db.session import SessionLocal
from app.application.telegram_service import (
    is_telegram_configured,
    notify_admin_excessive_fix,
    notify_admin_deadline_overdue,
    notify_admin_missing_template,
    notify_admin_new_fix,
    notify_admin_review_submitted,
    notify_admin_system_alert,
    notify_designer_new_order,
    notify_designer_payment,
    notify_designer_urgent_fix,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def safe_dispatch_telegram_task(task, *args, **kwargs) -> None:
    """Safely dispatch celery task or fallback to background thread immediately."""
    if not is_telegram_configured():
        return
    try:
        task.delay(*args, **kwargs)
    except Exception as exc:
        logger.warning("Celery dispatch failed for %s, falling back to background thread: %s", getattr(task, "name", str(task)), exc)
        try:
            t = threading.Thread(target=task, args=args, kwargs=kwargs, daemon=True)
            t.start()
        except Exception:
            logger.exception("Failed background thread fallback for %s", getattr(task, "name", str(task)))


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


@celery_app.task(name="app.workers.telegram_tasks.check_designer_deadlines")
def check_designer_deadlines() -> None:
    """Alert each active order deadline once; timestamps make periodic scans idempotent."""
    if not is_telegram_configured():
        return
    session = SessionLocal()
    try:
        now = datetime.now(UTC)
        orders = session.query(Order).filter(
            Order.deadline_overdue_notified_at.is_(None),
            Order.state.in_(("IN_PROGRESS", "REVISION")),
        ).all()
        order_ids = []
        for order in orders:
            # Starting a Fix changes state to IN_PROGRESS, but its one-hour
            # deadline remains authoritative until the designer resubmits.
            deadline = order.fix_deadline_at or order.deadline_tacahu
            if deadline and deadline <= now:
                order.deadline_overdue_notified_at = now
                order_ids.append(order.id)
        session.commit()
        for order_id in order_ids:
            notify_admin_deadline_overdue(session, order_id)
    except Exception:
        session.rollback()
        logger.exception("Failed overdue deadline scan")
    finally:
        session.close()


@celery_app.task(name="app.workers.telegram_tasks.async_notify_admin_missing_template")
def async_notify_admin_missing_template(order_id_str: str, designer_id_str: str) -> None:
    if not is_telegram_configured():
        return
    session = SessionLocal()
    try:
        notify_admin_missing_template(session, uuid.UUID(order_id_str), uuid.UUID(designer_id_str))
    except Exception:
        logger.exception("Failed missing-template Telegram notification for order %s", order_id_str)
    finally:
        session.close()

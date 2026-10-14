from __future__ import annotations

import logging

from sqlalchemy import text

from app.adapters.db.models import Platform
from app.adapters.db.session import SessionLocal, engine
from app.application.order_chat import purge_closed_chats, sync_platform_chats
from app.config import get_settings
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.order_chat_tasks.sync_order_chats")
def sync_order_chats() -> dict:
    """Mirror the Printerval chat of Doing/Review/Fix orders, one platform at a time.

    A dedicated connection holds a Postgres advisory lock per platform so two sweeps never
    overlap (a sweep can outlast the 2-minute beat interval).
    """
    settings = get_settings()
    if not settings.order_chat_enabled:
        return {}
    results: dict[str, dict] = {}
    session = SessionLocal()
    try:
        platforms = (
            session.query(Platform)
            .filter(
                Platform.is_active.is_(True),
                Platform.team_outsource.isnot(None),
                (Platform.account_password.isnot(None)) | (Platform.session_cookie.isnot(None)),
            )
            .all()
        )
        for platform in platforms:
            with engine.connect() as lock_conn:
                key = f"order-chat-sync:{platform.id}"
                got = lock_conn.execute(
                    text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": key}
                ).scalar()
                if not got:
                    continue
                try:
                    results[platform.name] = sync_platform_chats(
                        session, platform, rotation=settings.order_chat_rotation_batch
                    )
                except Exception:
                    session.rollback()
                    logger.exception("order chat sweep failed for platform %s", platform.name)
                finally:
                    lock_conn.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": key})
                    lock_conn.commit()
        logger.info("order chat sweep: %s", results)
    finally:
        session.close()
    return results


@celery_app.task(name="app.workers.order_chat_tasks.purge_order_chats")
def purge_order_chats() -> int:
    settings = get_settings()
    if not settings.order_chat_enabled:
        return 0
    session = SessionLocal()
    try:
        purged = purge_closed_chats(session, retention_days=settings.order_chat_retention_days)
        logger.info("purged chat of %s closed orders", purged)
        return purged
    except Exception:
        session.rollback()
        logger.exception("order chat purge failed")
        return 0
    finally:
        session.close()

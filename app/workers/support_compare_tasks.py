from __future__ import annotations

import logging
import sys
from pathlib import Path
from uuid import UUID

from app.adapters.db.session import SessionLocal
from app.application.support_compare import notify_pending_duplicate_candidates
from app.application.telegram_service import send_message
from app.config import get_settings
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _comparison_runner():
    """Import the optional ML runner only when a comparison task is executed."""
    runner_root = Path(__file__).resolve().parents[2] / "support_compare_image" / "dup-compare"
    runner_path = str(runner_root)
    if runner_path not in sys.path:
        sys.path.insert(0, runner_path)
    from backend.postgres_compare import run_comparison

    return run_comparison


@celery_app.task(bind=True, name="app.workers.support_compare_tasks.run_support_compare_batch")
def run_support_compare_batch(
    self,
    source_kind: str = "support_unchecked",
    limit: int | None = None,
    platform_id: str | None = None,
    notify_chat_id: str | None = None,
) -> dict:
    settings = get_settings()
    if not settings.support_compare_enabled:
        logger.info("support comparison is disabled; skipping batch")
        summary = {"skipped": True, "reason": "SUPPORT_COMPARE_ENABLED=false"}
        if notify_chat_id:
            send_message(notify_chat_id, "⚠️ Chức năng kiểm tra trùng đang tắt trên hệ thống.")
        return summary

    try:
        run_comparison = _comparison_runner()
        database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
        summary = run_comparison(
            database_url,
            source_kind=source_kind,
            model_name=settings.support_compare_model_name,
            model_version=settings.support_compare_model_version,
            platform_id=UUID(platform_id) if platform_id else None,
            limit=limit if limit is not None else settings.support_compare_scan_limit,
            embedding_batch_size=settings.support_compare_embedding_batch_size,
            promote_new_images=source_kind in {"waiting", "support_unchecked"},
        )
    except Exception as exc:
        if notify_chat_id:
            send_message(
                notify_chat_id,
                f"❌ Không thể hoàn tất kiểm tra trùng: <code>{type(exc).__name__}</code>.",
            )
        raise

    logger.info("support comparison task %s completed: %s", self.request.id, summary)
    if notify_chat_id:
        send_message(
            notify_chat_id,
            (
                f"✅ Đã quét xong <b>{summary.get('requested_count', 0)}</b> đơn trong tab "
                "<b>Chưa kiểm tra</b>.\n"
                f"• Đã embedding/so sánh: <b>{summary.get('processed_count', 0)}</b>\n"
                f"• Phát hiện candidate duplicate: <b>{summary.get('duplicate_count', 0)}</b>\n"
                f"• Lỗi: <b>{summary.get('error_count', 0)}</b>\n\n"
                "Các cặp duplicate (nếu có) sẽ được gửi tiếp qua các tin nhắn Telegram riêng."
            ),
        )
    return summary


@celery_app.task(name="app.workers.support_compare_tasks.notify_support_duplicate_candidates")
def notify_support_duplicate_candidates() -> int:
    settings = get_settings()
    if not settings.support_compare_enabled:
        return 0
    session = SessionLocal()
    try:
        count = notify_pending_duplicate_candidates(
            session,
            limit=settings.support_compare_batch_limit,
        )
        logger.info("notified %s support duplicate candidates", count)
        return count
    except Exception:
        session.rollback()
        logger.exception("support duplicate candidate notification failed")
        return 0
    finally:
        session.close()

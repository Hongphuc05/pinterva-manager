"""Support duplicate-image comparison orchestration and Telegram review actions."""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from html import escape

from sqlalchemy import exists, or_
from sqlalchemy.orm import Session

from app.adapters.db.models import (
    Order,
    SupportCompareCandidate,
    SupportCompareItem,
    SupportCompareJob,
    SupportCompareRun,
    SupportHistoricalJob,
    TelegramActionLog,
    User,
)
from app.application.duplicate_board import set_orders_duplicate_status
from app.application.telegram_service import (
    render_telegram_template,
    send_media_group,
    send_message,
    send_photo,
)
from app.domain.access import (
    DUPLICATE_CHECK_DUPLICATE,
    DUPLICATE_CHECK_NON_DUPLICATE,
    DUPLICATE_CHECK_UNCHECK,
    ROLE_SUPPORT,
    SUPPORT_CLASSIFICATION_STATES,
    SUPPORT_READ_ONLY_DOING_STATES,
    WORK_DOMAIN_DUPLICATE,
)

logger = logging.getLogger(__name__)

ACTION_CONFIRM = "SUPPORT_COMPARE_CONFIRM_DUPLICATE"
ACTION_REJECT = "SUPPORT_COMPARE_REJECT_DUPLICATE"
CALLBACK_CONFIRM_PREFIX = "scdup_yes"
CALLBACK_REJECT_PREFIX = "scdup_no"
ACTION_CHECK_YES = "SUPPORT_COMPARE_CHECK_YES"
ACTION_CHECK_NO = "SUPPORT_COMPARE_CHECK_NO"
CALLBACK_CHECK_YES_PREFIX = "sccheck_yes"
CALLBACK_CHECK_NO_PREFIX = "sccheck_no"
ACTION_HANDLE_YES = "SUPPORT_COMPARE_HANDLE_YES"
ACTION_HANDLE_NO = "SUPPORT_COMPARE_HANDLE_NO"
CALLBACK_HANDLE_YES_PREFIX = "schandle_yes"
CALLBACK_HANDLE_NO_PREFIX = "schandle_no"
ACTION_EXPIRY = timedelta(hours=24)


def _unchecked_scope(platform_id: uuid.UUID) -> list:
    """Orders shown in Support's "Chưa kiểm tra" tab (state based, see Order visibility)."""
    return [
        Order.platform_id == platform_id,
        or_(
            Order.state.in_(SUPPORT_CLASSIFICATION_STATES),
            Order.state.in_(SUPPORT_READ_ONLY_DOING_STATES),
        ),
        or_(
            Order.duplicate_check_status.is_(None),
            Order.duplicate_check_status == DUPLICATE_CHECK_UNCHECK,
        ),
        or_(
            Order.work_domain.is_(None),
            Order.work_domain != WORK_DOMAIN_DUPLICATE,
        ),
    ]


def _has_item(*review_statuses: str):
    """EXISTS: the order has a completed comparison item in one of the statuses."""
    return exists().where(
        SupportCompareItem.order_id == Order.id,
        SupportCompareItem.processing_status == "completed",
        SupportCompareItem.review_status.in_(review_statuses),
    )


def count_support_unchecked_orders(session: Session, *, platform_id: uuid.UUID) -> int:
    """Count the orders a /check would send to the local worker.

    The Chưa kiểm tra tab scope, minus orders that already have a completed
    comparison (those wait for the localhost review, Telegram or /handle).
    State only: Support's web view has no ``printerval_status`` (it is stripped),
    so a stale "doing" mirror on a QC_PENDING/DONE order must not be counted.
    """
    never_compared = ~exists().where(
        SupportCompareItem.order_id == Order.id,
        SupportCompareItem.processing_status == "completed",
    )
    return session.query(Order).filter(*_unchecked_scope(platform_id), never_compared).count()


def _handleable_filters(platform_id: uuid.UUID) -> list:
    return [
        *_unchecked_scope(platform_id),
        _has_item("no_match", "ai_wrong"),
        ~_has_item("pending_review", "selected_duplicate"),
    ]


def count_handleable_orders(session: Session, *, platform_id: uuid.UUID) -> int:
    """Compared orders with no duplicate found (or model judged wrong) still in the tab."""
    return session.query(Order).filter(*_handleable_filters(platform_id)).count()


def handle_unchecked_orders(session: Session, *, actor: User, platform_id: uuid.UUID) -> int:
    """/handle: move compared-and-not-duplicate orders to Không trùng lặp."""
    order_ids = [
        row[0]
        for row in session.query(Order.id).filter(*_handleable_filters(platform_id)).all()
    ]
    if not order_ids:
        return 0
    return set_orders_duplicate_status(
        session,
        actor=actor,
        platform_id=platform_id,
        order_ids=order_ids,
        duplicate_status=DUPLICATE_CHECK_NON_DUPLICATE,
        allow_support_unclassified_doing=True,
    )


def create_support_compare_job(
    session: Session,
    *,
    platform_id: uuid.UUID,
    requested_by_id: uuid.UUID,
    chat_id: str,
    requested_count: int,
) -> SupportCompareJob:
    """Queue a comparison request for the separately-run local ML worker."""
    active_job = (
        session.query(SupportCompareJob)
        .filter(
            SupportCompareJob.platform_id == platform_id,
            SupportCompareJob.status.in_(("queued", "running")),
        )
        .with_for_update()
        .first()
    )
    if active_job is not None:
        return active_job
    job = SupportCompareJob(
        platform_id=platform_id,
        requested_by_id=requested_by_id,
        chat_id=chat_id,
        requested_count=requested_count,
    )
    session.add(job)
    session.flush()
    return job


def notify_completed_support_compare_jobs(session: Session, *, limit: int = 20) -> int:
    """Send local-worker completion/failure reports through the server-side bot."""
    jobs = (
        session.query(SupportCompareJob)
        .filter(
            SupportCompareJob.status.in_(("completed", "failed")),
            SupportCompareJob.notification_sent_at.is_(None),
        )
        .order_by(SupportCompareJob.finished_at.asc(), SupportCompareJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(max(1, limit))
        .all()
    )
    notified = 0
    for job in jobs:
        if job.status == "completed":
            summary = job.summary or {}
            processed = int(summary.get("processed_count", job.processed_count) or 0)
            duplicates = int(summary.get("duplicate_count", job.duplicate_count) or 0)
            errors = int(summary.get("error_count", job.error_count) or 0)
            text = (
                f"✅ Đã so sánh xong <b>{processed}</b> đơn bằng máy local.\n"
                f"• Nghi trùng (cần duyệt trên localhost): <b>{duplicates}</b>\n"
                f"• Không thấy trùng: <b>{max(processed - duplicates, 0)}</b>\n"
                f"• Lỗi: <b>{errors}</b>\n\n"
                "Mở giao diện localhost để duyệt các đơn nghi trùng. "
                "Cặp ảnh bạn chọn sẽ được gửi lại ở đây để xác nhận."
            )
        else:
            error = escape((job.last_error or "Không rõ lỗi")[:1000])
            text = (
                "❌ Máy local không hoàn tất được luồng kiểm tra trùng.\n"
                f"• Số đơn yêu cầu: <b>{job.requested_count}</b>\n"
                f"• Lỗi: <code>{error}</code>"
            )
        if send_message(job.chat_id, text) is not None:
            job.notification_sent_at = datetime.now(UTC)
            notified += 1
    session.commit()
    return notified


def _new_confirm_actions(
    yes_type: str,
    no_type: str,
    *,
    platform_id: uuid.UUID,
    chat_id: str,
    order_count: int,
) -> tuple[TelegramActionLog, TelegramActionLog]:
    """Create the two opaque callback records for a yes/no confirmation prompt."""
    request_id = str(uuid.uuid4())
    payload = {
        "chat_id": chat_id,
        "platform_id": str(platform_id),
        "order_count": order_count,
        "request_id": request_id,
    }
    expires_at = datetime.now(UTC) + ACTION_EXPIRY
    return tuple(  # type: ignore[return-value]
        TelegramActionLog(
            order_id=None,
            action_type=action_type,
            callback_token=secrets.token_urlsafe(16),
            payload=payload.copy(),
            expires_at=expires_at,
        )
        for action_type in (yes_type, no_type)
    )


def new_support_check_actions(
    *,
    platform_id: uuid.UUID,
    chat_id: str,
    order_count: int,
) -> tuple[TelegramActionLog, TelegramActionLog]:
    """Callback records for a /check confirmation prompt."""
    return _new_confirm_actions(
        ACTION_CHECK_YES, ACTION_CHECK_NO,
        platform_id=platform_id, chat_id=chat_id, order_count=order_count,
    )


def new_support_handle_actions(
    *,
    platform_id: uuid.UUID,
    chat_id: str,
    order_count: int,
) -> tuple[TelegramActionLog, TelegramActionLog]:
    """Callback records for a /handle confirmation prompt."""
    return _new_confirm_actions(
        ACTION_HANDLE_YES, ACTION_HANDLE_NO,
        platform_id=platform_id, chat_id=chat_id, order_count=order_count,
    )


def support_handle_keyboard(yes_token: str, no_token: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Có, chuyển hết", "callback_data": f"{CALLBACK_HANDLE_YES_PREFIX}:{yes_token}"},
                {"text": "❌ Không", "callback_data": f"{CALLBACK_HANDLE_NO_PREFIX}:{no_token}"},
            ]
        ]
    }


def support_check_keyboard(yes_token: str, no_token: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Có, bắt đầu", "callback_data": f"{CALLBACK_CHECK_YES_PREFIX}:{yes_token}"},
                {"text": "❌ Không", "callback_data": f"{CALLBACK_CHECK_NO_PREFIX}:{no_token}"},
            ]
        ]
    }


def supersede_support_check_siblings(session: Session, action_log: TelegramActionLog) -> None:
    """Close the other button from the same /check or /handle prompt."""
    request_id = str((action_log.payload or {}).get("request_id") or "")
    if not request_id:
        return
    siblings = (
        session.query(TelegramActionLog)
        .filter(
            TelegramActionLog.status == "pending",
            TelegramActionLog.action_type.in_(
                (ACTION_CHECK_YES, ACTION_CHECK_NO, ACTION_HANDLE_YES, ACTION_HANDLE_NO)
            ),
        )
        .all()
    )
    for sibling in siblings:
        if sibling.id != action_log.id and str((sibling.payload or {}).get("request_id") or "") == request_id:
            sibling.status = "superseded"


def _support_recipients(session: Session, platform_id: uuid.UUID) -> list[User]:
    """Return active Support Telegram accounts scoped to the source platform."""
    return (
        session.query(User)
        .filter(
            User.role == ROLE_SUPPORT,
            User.active.is_(True),
            User.telegram_chat_id.isnot(None),
            User.telegram_notifications_enabled.is_(True),
            (User.platform_id == platform_id) | (User.platform_id.is_(None)),
        )
        .order_by(User.id)
        .all()
    )


def _caption_for_new(session: Session, item: SupportCompareItem) -> str:
    return render_telegram_template(
        session,
        "support_duplicate_new_candidate",
        {
            "order_code": item.external_order_id,
            "product_name": item.product_name or "Không có tên",
        },
    )


def _caption_for_old(session: Session, candidate: SupportCompareCandidate) -> str:
    return render_telegram_template(
        session,
        "support_duplicate_match_candidate",
        {
            "matched_order_code": candidate.matched_external_order_id or "Không rõ",
            "matched_product_name": candidate.matched_product_name or "Không có tên",
            "similarity": f"{candidate.visual_similarity:.4f}",
            "classifier": candidate.classification,
        },
    )


_CONFIG_VALUE_LIMIT = 300
_CONFIG_BLOCK_LIMIT = 1700


def format_custom_config(config: dict | None, limit: int = _CONFIG_BLOCK_LIMIT) -> str:
    """Telegram-HTML lines for an order's custom configuration (Vietnamese if present).

    ``limit`` caps the text (markup included, so it is conservative); longer configurations end with "…".
    """
    if not isinstance(config, dict):
        return "<i>Không có cấu hình</i>"
    entries = config.get("translated_vn") or config.get("original") or []
    lines: list[str] = []
    total = 0
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("key"):
            continue
        if str(entry["key"]).lower().startswith(("extra_discount", "url_")):  # internal flags, not design options
            continue
        value = str(entry.get("value") or "").strip()
        if len(value) > _CONFIG_VALUE_LIMIT:
            value = value[:_CONFIG_VALUE_LIMIT] + "…"
        line = f"• <b>{escape(str(entry['key']))}</b>: {escape(value)}"
        if total + len(line) > limit:
            lines.append("…")
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines) or "<i>Không có cấu hình</i>"


def _config_for_new(session: Session, item: SupportCompareItem) -> dict | None:
    order = session.get(Order, item.order_id)
    return order.custom_config if order is not None else None


def _config_for_old(session: Session, candidate: SupportCompareCandidate, platform_id: uuid.UUID) -> dict | None:
    """Prefer the tracked order (fresher), then the pool entry's stored configuration."""
    if candidate.matched_external_order_id:
        order = (
            session.query(Order)
            .filter(
                Order.platform_id == platform_id,
                Order.external_order_id == candidate.matched_external_order_id,
            )
            .first()
        )
        if order is not None and order.custom_config:
            return order.custom_config
    if candidate.historical_job_id is not None:
        job = session.get(SupportHistoricalJob, candidate.historical_job_id)
        if job is not None:
            return job.custom_config
    return None


CAPTION_LIMIT = 1000  # Telegram allows 1024 characters in a media caption


def _combined_caption(session: Session, item: SupportCompareItem, candidate: SupportCompareCandidate) -> str:
    """One caption for the album: new order, matched order and both custom configurations.

    Telegram shows only one caption per album and cuts it at 1024 characters, so the
    configurations share whatever room the two order captions leave (full data is on the web).
    """
    head = f"{_caption_for_new(session, item)}\n\n{_caption_for_old(session, candidate)}"
    titles = (
        f"🧩 <b>Cấu hình đơn mới {escape(item.external_order_id)}</b>",
        f"🧩 <b>Cấu hình đơn cũ {escape(candidate.matched_external_order_id or 'không rõ')}</b>",
    )
    configs = (_config_for_new(session, item), _config_for_old(session, candidate, item.platform_id))
    room = CAPTION_LIMIT - len(head) - sum(len(t) for t in titles) - 6
    per_block = room // 2
    if per_block < 60:  # order captions alone are nearly full: skip the details
        return head
    blocks = [f"{title}\n{format_custom_config(config, per_block)}" for title, config in zip(titles, configs)]
    return f"{head}\n\n" + "\n\n".join(blocks)


def _keyboard(confirm_token: str, reject_token: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Xác nhận trùng", "callback_data": f"{CALLBACK_CONFIRM_PREFIX}:{confirm_token}"},
                {"text": "❌ Từ chối", "callback_data": f"{CALLBACK_REJECT_PREFIX}:{reject_token}"},
            ]
        ]
    }


def _new_action(
    *,
    order_id: uuid.UUID,
    action_type: str,
    candidate_id: uuid.UUID,
    chat_id: str,
    expected_version: int | None,
) -> TelegramActionLog:
    return TelegramActionLog(
        order_id=order_id,
        action_type=action_type,
        callback_token=secrets.token_urlsafe(16),
        payload={
            "candidate_id": str(candidate_id),
            "chat_id": chat_id,
            "expected_order_version": expected_version,
        },
        expires_at=datetime.now(UTC) + ACTION_EXPIRY,
    )


def notify_duplicate_candidate(session: Session, candidate_id: uuid.UUID) -> bool:
    """Send the candidate Support picked on the localhost review to Telegram.

    The candidate itself remains pending until a Support callback invokes the
    existing duplicate application service.
    """
    candidate = session.get(SupportCompareCandidate, candidate_id)
    if candidate is None:
        return False
    if candidate.decision_status != "pending" or candidate.telegram_notified_at is not None:
        return False

    item = session.get(SupportCompareItem, candidate.comparison_item_id)
    if (
        item is None
        or item.processing_status != "completed"
        or item.review_status != "selected_duplicate"
        or item.selected_candidate_id != candidate.id
    ):
        return False
    order = session.get(Order, item.order_id)
    if order is None or order.platform_id != item.platform_id:
        logger.warning("comparison candidate %s has no matching production order", candidate_id)
        return False

    recipients = _support_recipients(session, item.platform_id)
    if not recipients:
        logger.info("no linked Support Telegram account for platform %s", item.platform_id)
        return False

    action_rows: list[tuple[TelegramActionLog, TelegramActionLog, str]] = []
    for recipient in recipients:
        chat_id = str(recipient.telegram_chat_id)
        confirm = _new_action(
            order_id=order.id,
            action_type=ACTION_CONFIRM,
            candidate_id=candidate.id,
            chat_id=chat_id,
            expected_version=order.version,
        )
        reject = _new_action(
            order_id=order.id,
            action_type=ACTION_REJECT,
            candidate_id=candidate.id,
            chat_id=chat_id,
            expected_version=order.version,
        )
        session.add_all([confirm, reject])
        action_rows.append((confirm, reject, chat_id))
    session.commit()

    delivered = False
    try:
        for confirm, reject, chat_id in action_rows:
            caption = _combined_caption(session, item, candidate)
            album = None
            if (
                item.image_url.startswith(("http://", "https://"))
                and candidate.matched_image_url.startswith(("http://", "https://"))
            ):
                # One album = one message: both previews plus the combined caption (Telegram
                # shows only the first caption of an album).
                album = send_media_group(
                    chat_id,
                    [
                        {"media": item.image_url, "caption": caption},
                        {"media": candidate.matched_image_url},
                    ],
                )

            if album is None:
                # Keep a graceful fallback for private/invalid URLs.  Buttons
                # are attached to the separate prompt below in both paths.
                new_message = send_photo(chat_id, item.image_url, caption=caption)
                old_message = send_photo(
                    chat_id, candidate.matched_image_url, caption=_caption_for_old(session, candidate)
                )
                if new_message is None or old_message is None:
                    logger.warning("failed to deliver duplicate candidate %s to %s", candidate.id, chat_id)
                    continue

            prompt = send_message(
                chat_id,
                (
                    f"👉 Đơn <b>{escape(item.external_order_id)}</b> trùng với đơn "
                    f"<b>{escape(candidate.matched_external_order_id or 'không rõ')}</b>? "
                    "Xác nhận để gắn tag Trùng lặp, Từ chối để đưa vào Không trùng lặp."
                ),
                reply_markup=_keyboard(confirm.callback_token, reject.callback_token),
            )
            if prompt is None:
                logger.warning("failed to deliver duplicate candidate %s to %s", candidate.id, chat_id)
                continue
            message_id = prompt.get("message_id") if isinstance(prompt, dict) else None
            for action in (confirm, reject):
                action.payload = {
                    **(action.payload or {}),
                    "message_id": message_id,
                }
            delivered = True
        if delivered:
            candidate.telegram_notified_at = datetime.now(UTC)
            session.commit()
        return delivered
    except Exception:
        session.rollback()
        logger.exception("failed to deliver duplicate candidate %s", candidate.id)
        return False


def notify_pending_duplicate_candidates(session: Session, *, limit: int = 20) -> int:
    """Send every candidate Support selected on the localhost review."""
    candidates = (
        session.query(SupportCompareCandidate)
        .join(
            SupportCompareItem,
            SupportCompareItem.selected_candidate_id == SupportCompareCandidate.id,
        )
        .filter(
            SupportCompareItem.review_status == "selected_duplicate",
            SupportCompareItem.processing_status == "completed",
            SupportCompareCandidate.decision_status == "pending",
            SupportCompareCandidate.telegram_notified_at.is_(None),
        )
        .order_by(SupportCompareItem.reviewed_at.asc())
        .limit(max(1, limit))
        .all()
    )
    notified = 0
    for candidate in candidates:
        if notify_duplicate_candidate(session, candidate.id):
            notified += 1
    return notified


def execute_support_duplicate_decision(
    session: Session,
    *,
    actor: User,
    action_log: TelegramActionLog,
    decision_status: str,
) -> tuple[SupportCompareCandidate, Order]:
    """Apply a Telegram decision through the existing Support order command."""
    if actor.role != ROLE_SUPPORT:
        raise ValueError("Chỉ tài khoản Support được xử lý candidate này")
    if decision_status not in {DUPLICATE_CHECK_DUPLICATE, DUPLICATE_CHECK_NON_DUPLICATE}:
        raise ValueError("Quyết định duplicate không hợp lệ")

    candidate_id = uuid.UUID(str((action_log.payload or {}).get("candidate_id")))
    candidate = (
        session.query(SupportCompareCandidate)
        .filter(SupportCompareCandidate.id == candidate_id)
        .with_for_update()
        .one_or_none()
    )
    if candidate is None or candidate.decision_status != "pending":
        raise ValueError("Candidate đã được xử lý hoặc không còn tồn tại")
    item = session.get(SupportCompareItem, candidate.comparison_item_id)
    order = session.get(Order, item.order_id if item else None)
    if item is None or order is None:
        raise ValueError("Không tìm thấy order mới tương ứng với candidate")
    run = session.get(SupportCompareRun, item.run_id)
    if run is None or run.source_kind not in {"waiting", "support_unchecked"}:
        raise ValueError("Candidate từ source test Review chỉ được xem, chưa được phép thao tác")
    if item.review_status != "selected_duplicate" or item.selected_candidate_id != candidate.id:
        raise ValueError("Candidate này chưa được Support chọn trên giao diện localhost")
    if order.platform_id != item.platform_id:
        raise ValueError("Candidate không cùng platform với order")

    # The normal web command remains Waiting-only.  This scoped callback is the
    # only path allowed to classify an unverified Doing order after the model
    # has produced a positive candidate and Support has clicked a button.
    expected_version = (action_log.payload or {}).get("expected_order_version")
    expected_versions = {order.id: int(expected_version)} if expected_version is not None else None
    set_orders_duplicate_status(
        session,
        actor=actor,
        platform_id=item.platform_id,
        order_ids=[order.id],
        duplicate_status=decision_status,
        expected_versions=expected_versions,
        allow_support_unclassified_doing=True,
    )

    candidate.decision_status = decision_status
    candidate.decided_by_id = actor.id
    candidate.decided_at = datetime.now(UTC)
    session.query(SupportCompareCandidate).filter(
        SupportCompareCandidate.comparison_item_id == candidate.comparison_item_id,
        SupportCompareCandidate.id != candidate.id,
        SupportCompareCandidate.decision_status == "pending",
    ).update({"decision_status": "superseded"}, synchronize_session=False)
    session.commit()
    return candidate, order

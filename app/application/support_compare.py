"""Support duplicate-image comparison orchestration and Telegram review actions."""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.adapters.db.models import (
    Order,
    SupportCompareCandidate,
    SupportCompareItem,
    SupportCompareRun,
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
ACTION_EXPIRY = timedelta(hours=24)


def count_support_unchecked_orders(session: Session, *, platform_id: uuid.UUID) -> int:
    """Count the orders shown in Support's current "Chưa kiểm tra" scope."""
    return (
        session.query(Order)
        .filter(
            Order.platform_id == platform_id,
            or_(
                Order.state.in_(SUPPORT_CLASSIFICATION_STATES),
                Order.state.in_(SUPPORT_READ_ONLY_DOING_STATES),
                Order.printerval_status.ilike("waiting"),
                Order.printerval_status.ilike("doing"),
            ),
            or_(
                Order.duplicate_check_status.is_(None),
                Order.duplicate_check_status == DUPLICATE_CHECK_UNCHECK,
            ),
            or_(
                Order.work_domain.is_(None),
                Order.work_domain != WORK_DOMAIN_DUPLICATE,
            ),
        )
        .count()
    )


def new_support_check_actions(
    *,
    platform_id: uuid.UUID,
    chat_id: str,
    order_count: int,
) -> tuple[TelegramActionLog, TelegramActionLog]:
    """Create the two opaque callback records for a /check confirmation prompt."""
    request_id = str(uuid.uuid4())
    payload = {
        "chat_id": chat_id,
        "platform_id": str(platform_id),
        "order_count": order_count,
        "request_id": request_id,
    }
    expires_at = datetime.now(UTC) + ACTION_EXPIRY
    yes_action = TelegramActionLog(
        order_id=None,
        action_type=ACTION_CHECK_YES,
        callback_token=secrets.token_urlsafe(16),
        payload=payload.copy(),
        expires_at=expires_at,
    )
    no_action = TelegramActionLog(
        order_id=None,
        action_type=ACTION_CHECK_NO,
        callback_token=secrets.token_urlsafe(16),
        payload=payload.copy(),
        expires_at=expires_at,
    )
    return yes_action, no_action


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
    """Close the other button from the same /check prompt."""
    request_id = str((action_log.payload or {}).get("request_id") or "")
    if not request_id:
        return
    siblings = (
        session.query(TelegramActionLog)
        .filter(
            TelegramActionLog.status == "pending",
            TelegramActionLog.action_type.in_((ACTION_CHECK_YES, ACTION_CHECK_NO)),
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


def _keyboard(confirm_token: str, reject_token: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Trùng", "callback_data": f"{CALLBACK_CONFIRM_PREFIX}:{confirm_token}"},
                {"text": "❌ Không trùng", "callback_data": f"{CALLBACK_REJECT_PREFIX}:{reject_token}"},
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
    """Send one best positive candidate to the linked Support Telegram account(s).

    Only the highest-scoring candidate of an item marked duplicate is sent.
    The candidate itself remains pending until a Support callback invokes the
    existing duplicate application service.
    """
    candidate = session.get(SupportCompareCandidate, candidate_id)
    if candidate is None or candidate.rank != 1:
        return False
    if candidate.decision_status != "pending" or candidate.telegram_notified_at is not None:
        return False

    item = session.get(SupportCompareItem, candidate.comparison_item_id)
    if item is None or item.processing_status != "completed" or item.is_duplicate is not True:
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
            new_caption = _caption_for_new(session, item)
            old_caption = _caption_for_old(session, candidate)
            album = None
            if (
                item.image_url.startswith(("http://", "https://"))
                and candidate.matched_image_url.startswith(("http://", "https://"))
            ):
                # Telegram albums render the two previews as one visual card.
                album = send_media_group(
                    chat_id,
                    [
                        {"media": item.image_url, "caption": new_caption},
                        {"media": candidate.matched_image_url, "caption": old_caption},
                    ],
                )

            if album is None:
                # Keep a graceful fallback for private/invalid URLs.  Buttons
                # are attached to the separate prompt below in both paths.
                new_message = send_photo(chat_id, item.image_url, caption=new_caption)
                old_message = send_photo(chat_id, candidate.matched_image_url, caption=old_caption)
                if new_message is None or old_message is None:
                    logger.warning("failed to deliver duplicate candidate %s to %s", candidate.id, chat_id)
                    continue

            prompt = send_message(
                chat_id,
                "👉 Support chọn kết quả cho cặp ảnh ở trên:",
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
    """Notify at most one top-ranked positive candidate per source order item."""
    candidates = (
        session.query(SupportCompareCandidate)
        .join(
            SupportCompareItem,
            SupportCompareItem.id == SupportCompareCandidate.comparison_item_id,
        )
        .filter(
            SupportCompareCandidate.rank == 1,
            SupportCompareCandidate.decision_status == "pending",
            SupportCompareCandidate.telegram_notified_at.is_(None),
            SupportCompareItem.processing_status == "completed",
            SupportCompareItem.is_duplicate.is_(True),
        )
        .order_by(SupportCompareItem.created_at.asc(), SupportCompareCandidate.rank.asc())
        .limit(max(1, limit * 5))
        .all()
    )
    notified = 0
    seen_items: set[uuid.UUID] = set()
    for candidate in candidates:
        if candidate.comparison_item_id in seen_items:
            continue
        seen_items.add(candidate.comparison_item_id)
        if notify_duplicate_candidate(session, candidate.id):
            notified += 1
            if notified >= limit:
                break
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
    if item.is_duplicate is not True or candidate.rank != 1:
        raise ValueError("Candidate không phải kết quả duplicate top-1 cần Support xác nhận")
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

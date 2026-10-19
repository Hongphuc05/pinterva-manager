"""Printerval's per-order chat, read on demand and never mirrored wholesale.

QC writes Fix requests and remarks in a chat box per design job (not in ``note_outsource``, which only
holds the link Tacahu pushed). Tacahu reads it in three narrow ways, all Admin-only and read-only:

* the Admin opens an order -> that order's chat is fetched live (nothing stored);
* a poll asks Printerval which jobs have unread messages -> toasts for the Admin;
* an order's Printerval status moves to Fix/Confirm/Done -> a snapshot of the new messages is stored as
  an ``ExternalObservation`` (the Fix reason for the Telegram card, and a net for messages someone
  already read on Printerval, which the unread list no longer shows).

Fetching messages makes Printerval mark them read for its whole team; the unread list does not.
Chat never changes an order's state.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.adapters.db.models import ExternalObservation, Order, Platform
from app.adapters.printerval.api_client import PrintervalApiClient

logger = logging.getLogger(__name__)

SOURCE = "printerval.chat"
# Statuses whose arrival on Printerval makes Tacahu read the order's chat once.
WATCHED_STATUSES = ("fix", "confirm", "done")
ACTIVE_STATES = ("IN_PROGRESS", "QC_PENDING", "REVISION")
PRINTERVAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
SNAPSHOT_MESSAGES = 8
CONTENT_LIMIT = 1500
UNREAD_CACHE_SECONDS = 60
UNREAD_RETRY_SECONDS = 30
CHAT_TIMEOUT_SECONDS = 30.0

ClientFactory = Callable[[Platform], PrintervalApiClient]


def printerval_client_for(platform: Platform) -> PrintervalApiClient:
    return PrintervalApiClient(
        base_url="https://printerval.com",
        username=platform.account_username,
        password=platform.account_password,
        team_outsource=platform.team_outsource,
        session_cookie=platform.session_cookie,
        timeout=CHAT_TIMEOUT_SECONDS,
    )


def numeric_job_id(order: Order) -> int | None:
    code = (order.external_order_id or "").strip()
    digits = code[2:] if code.upper().startswith("DJ") else code
    return int(digits) if digits.isdigit() else None


def _sent_at(raw: object) -> str | None:
    try:
        parsed = datetime.strptime(str(raw), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=PRINTERVAL_TZ).astimezone(UTC).isoformat()


def _http_urls(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [u for u in value if isinstance(u, str) and u.lower().startswith(("http://", "https://"))]


def parse_message(raw: dict) -> dict | None:
    """One Printerval message as plain data, or None when it has no usable id."""
    try:
        message_id = int(raw.get("id"))
    except (TypeError, ValueError):
        return None
    if message_id <= 0:
        return None
    return {
        "id": message_id,
        "fix_round": int(raw.get("fix_round") or 0),
        "type": str(raw.get("type") or "")[:32],
        "sender_type": str(raw.get("sender_type") or "")[:32],
        "sender_name": str(raw.get("sender_name") or "")[:255],
        "mine": bool(raw.get("mine")),
        "content": str(raw.get("content") or "")[:CONTENT_LIMIT],
        "image_urls": _http_urls(raw.get("image_urls")),
        "fix_reason_label": str(raw.get("fix_reason_label") or "")[:255],
        "sent_at": _sent_at(raw.get("created_at")),
    }


def fetch_messages(
    platform: Platform, job_id: int, *, after_id: int = 0, client_factory: ClientFactory = printerval_client_for
) -> list[dict]:
    """Messages of one job after ``after_id``, oldest first. Printerval marks them read for the team."""
    with client_factory(platform) as client:
        client.login()
        payload = client.fetch_chat_messages(job_id, after_id)
    parsed = [m for m in (parse_message(raw) for raw in payload["messages"]) if m]
    return sorted(parsed, key=lambda m: m["id"])


# ----------------------------------------------------------------------------- snapshots


def last_captured_message_id(session: Session, order: Order) -> int:
    row = (
        session.query(ExternalObservation)
        .filter(ExternalObservation.order_id == order.id, ExternalObservation.source == SOURCE)
        .order_by(ExternalObservation.observed_at.desc())
        .first()
    )
    return int((row.evidence or {}).get("last_message_id") or 0) if row else 0


def capture_chat(
    session: Session, order: Order, status: str, *, client_factory: ClientFactory = printerval_client_for
) -> ExternalObservation | None:
    """Store the chat messages that are new since the last snapshot, or None when there are none.

    The caller commits. Raises on a Printerval failure so the Celery task can retry.
    """
    job_id = numeric_job_id(order)
    platform = session.get(Platform, order.platform_id) if order.platform_id else None
    if job_id is None or platform is None:
        return None
    messages = fetch_messages(
        platform, job_id, after_id=last_captured_message_id(session, order), client_factory=client_factory
    )
    if not messages:
        return None
    observation = ExternalObservation(
        order_id=order.id,
        source=SOURCE,
        external_id=str(job_id),
        observed_state=status[:32],
        evidence={
            "trigger_status": status,
            "last_message_id": messages[-1]["id"],
            "messages": messages[-SNAPSHOT_MESSAGES:],
        },
    )
    session.add(observation)
    return observation


def _reason_from(evidence: dict | None) -> str | None:
    for message in reversed((evidence or {}).get("messages") or []):
        if message.get("mine"):
            continue
        text = " — ".join(part for part in (message.get("fix_reason_label"), message.get("content")) if part)
        if text:
            return text
    return None


def latest_fix_reason(session: Session, order: Order) -> str | None:
    """The newest Printerval-side message captured for the order, as one line of text."""
    rows = (
        session.query(ExternalObservation)
        .filter(ExternalObservation.order_id == order.id, ExternalObservation.source == SOURCE)
        .order_by(ExternalObservation.observed_at.desc())
        .limit(5)
        .all()
    )
    return next((reason for reason in (_reason_from(row.evidence) for row in rows) if reason), None)


def fix_reasons(session: Session, order_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """``latest_fix_reason`` for many orders at once (the newest snapshot of each), for list rows."""
    if not order_ids:
        return {}
    rows = (
        session.query(ExternalObservation)
        .filter(ExternalObservation.order_id.in_(order_ids), ExternalObservation.source == SOURCE)
        .distinct(ExternalObservation.order_id)
        .order_by(ExternalObservation.order_id, ExternalObservation.observed_at.desc())
        .all()
    )
    reasons = {row.order_id: _reason_from(row.evidence) for row in rows}
    return {order_id: reason for order_id, reason in reasons.items() if reason}


# ----------------------------------------------------------------------------- unread poll

_unread_cache: dict[uuid.UUID, tuple[float, list[dict]]] = {}


def unread_orders(
    session: Session,
    platform: Platform,
    *,
    client_factory: ClientFactory = printerval_client_for,
    now: Callable[[], float] = time.monotonic,
) -> list[dict]:
    """Orders of this platform with unread messages on Printerval: ``[{order_id, order_code, count}]``.

    One cheap pair of calls to Printerval per platform per minute, however many Admins poll, and none
    when nobody is looking. Reading the unread list does not mark anything read.
    """
    cached = _unread_cache.get(platform.id)
    if cached and now() - cached[0] < UNREAD_CACHE_SECONDS:
        return cached[1]

    try:
        with client_factory(platform) as client:
            client.login()
            job_ids = client.fetch_chat_unread([])["job_ids"]
            codes = {f"DJ{job_id}": job_id for job_id in job_ids}
            orders = (
                session.query(Order)
                .filter(
                    Order.platform_id == platform.id,
                    Order.external_order_id.in_(list(codes)),
                    Order.state.in_(ACTIVE_STATES),
                )
                .all()
                if codes
                else []
            )
            counts: dict = {}
            if orders:
                try:
                    counts = client.fetch_chat_unread([codes[o.external_order_id] for o in orders])["unread"]
                except Exception:
                    logger.warning("unread counts failed, falling back to 1 per order", exc_info=True)
    except Exception:
        # Printerval is slow or down: serve what we had for 30 seconds instead of making every poll wait.
        previous = cached[1] if cached else []
        _unread_cache[platform.id] = (now() - UNREAD_CACHE_SECONDS + UNREAD_RETRY_SECONDS, previous)
        raise
    items = [
        {
            "order_id": str(order.id),
            "order_code": order.external_order_id,
            "count": int(counts.get(str(codes[order.external_order_id])) or 1),
        }
        for order in orders
    ]
    items.sort(key=lambda item: item["order_code"])
    _unread_cache[platform.id] = (now(), items)
    return items

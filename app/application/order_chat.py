"""Read-only mirror of Printerval's per-order chat (see docs/superpowers/specs/2026-10-14-...).

Printerval marks messages read for the whole team when they are fetched, so Tacahu keeps its own
per-user unread state (``OrderChatRead``). Chat never changes an order's state.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.adapters.db.models import (
    Assignment,
    Order,
    OrderChatMessage,
    OrderChatRead,
    Platform,
    User,
)
from app.adapters.printerval.api_client import PrintervalApiClient
from app.domain.access import ROLE_ADMIN, ROLE_DESIGNER, ROLE_DESIGNER_TRELLO
from app.domain.models import OrderState

logger = logging.getLogger(__name__)

PRINTERVAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
ACTIVE_STATES = (
    OrderState.IN_PROGRESS.value,
    OrderState.QC_PENDING.value,
    OrderState.REVISION.value,
)
CLOSED_STATES = (OrderState.DONE.value, OrderState.CANCELLED.value)
MAX_PAGES = 5
# A first fetch of an order brings its whole history: what is older than this is "already known"
# and never raises a toast; only the recent tail does.
BASELINE_AGE = timedelta(minutes=15)
# Old messages never raise a toast or a badge, so a newly assigned designer is not flooded.
UNREAD_WINDOW = timedelta(days=7)
ON_DEMAND_MAX_AGE = timedelta(seconds=30)
SNIPPET_LENGTH = 140

ClientFactory = Callable[[Platform], PrintervalApiClient]


def printerval_client_for(platform: Platform) -> PrintervalApiClient:
    return PrintervalApiClient(
        base_url="https://printerval.com",
        username=platform.account_username,
        password=platform.account_password,
        team_outsource=platform.team_outsource,
        session_cookie=platform.session_cookie,
    )


def numeric_job_id(order: Order) -> int | None:
    code = (order.external_order_id or "").strip()
    digits = code[2:] if code.upper().startswith("DJ") else code
    return int(digits) if digits.isdigit() else None


def _sent_at(raw: object) -> datetime:
    try:
        parsed = datetime.strptime(str(raw), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.now(UTC)
    return parsed.replace(tzinfo=PRINTERVAL_TZ).astimezone(UTC)


def _http_urls(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [u for u in value if isinstance(u, str) and u.lower().startswith(("http://", "https://"))]


def parse_message(raw: dict) -> dict | None:
    """Normalise one Printerval message, or None when it has no usable id."""
    try:
        external_id = int(raw.get("id"))
    except (TypeError, ValueError):
        return None
    if external_id <= 0:
        return None
    return {
        "external_id": external_id,
        "fix_round": int(raw.get("fix_round") or 0),
        "message_type": str(raw.get("type") or "")[:32],
        "sender_type": str(raw.get("sender_type") or "")[:32],
        "sender_name": str(raw.get("sender_name") or "")[:255],
        "mine": bool(raw.get("mine")),
        "content": str(raw.get("content") or ""),
        "image_urls": _http_urls(raw.get("image_urls")),
        "fix_reason_label": str(raw.get("fix_reason_label") or "")[:255],
        "sent_at": _sent_at(raw.get("created_at")),
    }


# ----------------------------------------------------------------------------- readers


def eligible_readers(session: Session, order: Order) -> list[User]:
    """Accounts that may read this order's chat: platform Admins and its assigned designers."""
    admins = (
        session.query(User)
        .filter(
            User.role == ROLE_ADMIN,
            User.active.is_(True),
            (User.platform_id == order.platform_id) | (User.platform_id.is_(None)),
        )
        .all()
    )
    designers = (
        session.query(User)
        .join(Assignment, Assignment.designer_id == User.id)
        .filter(
            Assignment.order_id == order.id,
            Assignment.status != "cancelled",
            User.role.in_((ROLE_DESIGNER, ROLE_DESIGNER_TRELLO)),
            User.active.is_(True),
        )
        .all()
    )
    seen: dict[uuid.UUID, User] = {}
    for user in [*admins, *designers]:
        seen[user.id] = user
    return list(seen.values())


def can_read_chat(session: Session, user: User, order: Order) -> bool:
    if not user.active:
        return False
    if user.role == ROLE_ADMIN:
        return order.platform_id is None or user.platform_id in (None, order.platform_id)
    if user.role in (ROLE_DESIGNER, ROLE_DESIGNER_TRELLO):
        return (
            session.query(Assignment.id)
            .filter(
                Assignment.order_id == order.id,
                Assignment.designer_id == user.id,
                Assignment.status != "cancelled",
            )
            .first()
            is not None
        )
    return False


def _set_read_marker(session: Session, order_id: uuid.UUID, user_id: uuid.UUID, external_id: int) -> None:
    stmt = pg_insert(OrderChatRead).values(
        id=uuid.uuid4(), order_id=order_id, user_id=user_id, last_read_external_id=external_id
    )
    session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_order_chat_read_user",
            set_={"last_read_external_id": func.greatest(OrderChatRead.last_read_external_id, external_id)},
        )
    )


# ----------------------------------------------------------------------------- sync


def sync_order_chat(session: Session, client: PrintervalApiClient, order: Order) -> int:
    """Fetch and store the messages newer than the order's cursor. Returns how many are new."""
    job_id = numeric_job_id(order)
    if job_id is None:
        return 0
    first_fetch = order.chat_last_message_id is None
    cursor = order.chat_last_message_id or 0
    inserted = 0
    newest = cursor
    batch_ids: list[tuple[int, datetime]] = []
    for _ in range(MAX_PAGES):
        data = client.fetch_chat_messages(job_id, after_id=cursor)
        parsed = [m for m in (parse_message(raw) for raw in data["messages"]) if m]
        if not parsed:
            break
        for message in sorted(parsed, key=lambda m: m["external_id"]):
            result = session.execute(
                pg_insert(OrderChatMessage)
                .values(id=uuid.uuid4(), order_id=order.id, platform_id=order.platform_id, **message)
                .on_conflict_do_nothing(constraint="uq_order_chat_message_external")
                .returning(OrderChatMessage.id)
            )
            inserted += 1 if result.first() is not None else 0
            batch_ids.append((message["external_id"], message["sent_at"]))
        page_newest = max(m["external_id"] for m in parsed)
        if page_newest <= cursor:
            break
        cursor = newest = page_newest
        try:
            last_known = int((data.get("chat") or {}).get("last_message_id") or 0)
        except (TypeError, ValueError):
            last_known = 0
        if last_known and page_newest >= last_known:
            break  # Printerval says this was the newest message: no extra page to probe
    if first_fetch and batch_ids:
        cutoff = datetime.now(UTC) - BASELINE_AGE
        known = [external_id for external_id, sent in batch_ids if sent < cutoff]
        if known:
            for reader in eligible_readers(session, order):
                _set_read_marker(session, order.id, reader.id, max(known))
    if newest > (order.chat_last_message_id or 0):
        order.chat_last_message_id = newest
    elif first_fetch:
        order.chat_last_message_id = 0
    order.chat_synced_at = datetime.now(UTC)
    session.commit()
    return inserted


def _candidate_query(session: Session, platform: Platform):
    return session.query(Order).filter(Order.platform_id == platform.id, Order.state.in_(ACTIVE_STATES))


def sync_platform_chats(
    session: Session,
    platform: Platform,
    *,
    rotation: int = 40,
    client_factory: ClientFactory = printerval_client_for,
) -> dict[str, int]:
    """One sweep: the team's unread jobs plus a rotating slice, so a message someone already
    read on Printerval is still picked up."""
    stats = {"orders": 0, "new_messages": 0, "errors": 0}
    slice_orders = (
        _candidate_query(session, platform)
        .order_by(Order.chat_synced_at.asc().nullsfirst(), Order.created_at.asc())
        .limit(max(rotation, 0))
        .all()
    )
    with client_factory(platform) as client:
        client.login()
        slice_ids = [j for j in (numeric_job_id(o) for o in slice_orders) if j is not None]
        unread_ids = set(client.fetch_chat_unread(slice_ids)["job_ids"])
        unread_orders: list[Order] = []
        if unread_ids:
            unread_orders = [
                o
                for o in _candidate_query(session, platform).all()
                if numeric_job_id(o) in unread_ids
            ]
        targets = {o.id: o for o in [*unread_orders, *slice_orders]}
        for order in targets.values():
            try:
                stats["new_messages"] += sync_order_chat(session, client, order)
                stats["orders"] += 1
            except Exception:
                session.rollback()
                stats["errors"] += 1
                logger.warning("order chat sync failed for %s", order.external_order_id, exc_info=True)
    return stats


def refresh_order_if_stale(
    session: Session,
    order: Order,
    *,
    client_factory: ClientFactory = printerval_client_for,
) -> bool:
    """Opening an order fetches its chat first unless it was fetched moments ago.
    Returns False when the fetch failed (the stored messages are then shown as stale)."""
    last = order.chat_synced_at
    if last is not None and datetime.now(UTC) - last < ON_DEMAND_MAX_AGE:
        return True
    platform = session.get(Platform, order.platform_id) if order.platform_id else None
    if platform is None or not (platform.account_password or platform.session_cookie):
        return False
    try:
        with client_factory(platform) as client:
            client.login()
            sync_order_chat(session, client, order)
        return True
    except Exception:
        session.rollback()
        logger.warning("on-demand chat fetch failed for %s", order.external_order_id, exc_info=True)
        return False


# ----------------------------------------------------------------------------- reading


def list_messages(session: Session, order: Order) -> list[OrderChatMessage]:
    return (
        session.query(OrderChatMessage)
        .filter(OrderChatMessage.order_id == order.id)
        .order_by(OrderChatMessage.external_id.asc())
        .all()
    )


def last_read(session: Session, order: Order, user: User) -> int:
    row = (
        session.query(OrderChatRead.last_read_external_id)
        .filter(OrderChatRead.order_id == order.id, OrderChatRead.user_id == user.id)
        .first()
    )
    return int(row[0]) if row else 0


def mark_read(session: Session, order: Order, user: User) -> int:
    newest = (
        session.query(func.max(OrderChatMessage.external_id))
        .filter(OrderChatMessage.order_id == order.id)
        .scalar()
    ) or 0
    if newest:
        _set_read_marker(session, order.id, user.id, int(newest))
        session.commit()
    return int(newest)


def unread_for_user(session: Session, user: User, platform_id: uuid.UUID) -> list[dict]:
    """Orders with Printerval-side messages this user has not seen, newest first."""
    if user.role == ROLE_ADMIN:
        scope = [Order.platform_id == platform_id]
    elif user.role in (ROLE_DESIGNER, ROLE_DESIGNER_TRELLO):
        mine = select(Assignment.order_id).where(
            Assignment.designer_id == user.id, Assignment.status != "cancelled"
        )
        scope = [Order.platform_id == platform_id, Order.id.in_(mine)]
    else:
        return []
    window = datetime.now(UTC) - UNREAD_WINDOW
    rows = (
        session.query(
            OrderChatMessage.order_id,
            Order.external_order_id,
            func.count(OrderChatMessage.id),
            func.max(OrderChatMessage.external_id),
        )
        .join(Order, Order.id == OrderChatMessage.order_id)
        .outerjoin(
            OrderChatRead,
            and_(OrderChatRead.order_id == OrderChatMessage.order_id, OrderChatRead.user_id == user.id),
        )
        .filter(
            *scope,
            OrderChatMessage.mine.is_(False),
            OrderChatMessage.sent_at >= window,
            OrderChatMessage.external_id > func.coalesce(OrderChatRead.last_read_external_id, 0),
        )
        .group_by(OrderChatMessage.order_id, Order.external_order_id)
        .all()
    )
    items = []
    for order_id, code, count, newest_id in rows:
        latest = (
            session.query(OrderChatMessage)
            .filter(OrderChatMessage.order_id == order_id, OrderChatMessage.external_id == newest_id)
            .one()
        )
        items.append(
            {
                "order_id": str(order_id),
                "order_code": code,
                "count": int(count),
                "latest_id": int(newest_id),
                "sender_name": latest.sender_name,
                "snippet": (latest.content or ("[ảnh]" if latest.image_urls else ""))[:SNIPPET_LENGTH],
                "sent_at": latest.sent_at,
            }
        )
    items.sort(key=lambda i: i["sent_at"], reverse=True)
    return items


# ----------------------------------------------------------------------------- retention


def purge_closed_chats(session: Session, *, retention_days: int = 30) -> int:
    """Delete the chat of orders closed (Done/Cancelled) longer ago than the retention window.
    A reopened order starts from cursor 0 and is fetched again in full."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    order_ids = [
        row[0]
        for row in session.query(Order.id)
        .filter(
            Order.state.in_(CLOSED_STATES),
            Order.status_changed_at < cutoff,
            (Order.chat_last_message_id.isnot(None))
            | Order.id.in_(select(OrderChatMessage.order_id)),
        )
        .all()
    ]
    if not order_ids:
        return 0
    session.execute(text("DELETE FROM order_chat_messages WHERE order_id = ANY(:ids)"), {"ids": order_ids})
    session.execute(text("DELETE FROM order_chat_reads WHERE order_id = ANY(:ids)"), {"ids": order_ids})
    session.query(Order).filter(Order.id.in_(order_ids)).update(
        {Order.chat_last_message_id: None, Order.chat_synced_at: None}, synchronize_session=False
    )
    session.commit()
    return len(order_ids)

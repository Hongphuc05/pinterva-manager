"""Paying Designers: the one payment path shared by Admin and Accountant, and its history.

Who is credited for an order, and whether it is payable at all, is decided by the finance
stats (``get_finance_stats``) that the Admin finance page shows; this module reuses it rather
than re-deriving it, so the page, the Accountant list and a payment always agree.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session
from starlette.requests import Request

from app.adapters.db.models import Order, PaymentBatch, Platform, User, WorkflowEvent
from app.application.concurrency import require_expected_order_version
from app.domain.access import ROLE_ADMIN, WORK_DOMAIN_DUPLICATE
from app.domain.models import OrderState

logger = logging.getLogger(__name__)

UNASSIGNED_NAME = "Chưa phân công"
_CLOSED_STATES = ("DONE", "CLAIMED_IMPORTED", "COMPLETED")


class PaymentConflictError(Exception):
    """What the payer saw is no longer what the server has; nothing was paid."""


@dataclass
class PaymentResult:
    updated_count: int
    batches: list[PaymentBatch] = field(default_factory=list)


def order_amount(order: Order, platform: Platform | None) -> int:
    """The pay for one order, by the same rule the finance stats use."""
    if order.custom_rate is not None:
        return order.custom_rate
    if platform is None:
        return 40000
    if (order.work_domain or "standard") == WORK_DOMAIN_DUPLICATE:
        return platform.duplicate_order_rate
    return platform.standard_order_rate


def credited_tasks(db: Session, platform_id: uuid.UUID) -> list[Any]:
    """Every order of ``platform_id`` as the Admin finance page sees it (credited designer, rate, paid)."""
    from app.api.routes.finance_api import get_finance_stats  # the credit rules live there

    request = Request({"type": "http", "headers": [(b"x-platform-id", str(platform_id).encode())]})
    stats = get_finance_stats(
        request=request,
        designer_id=None,
        search=None,
        state=None,
        is_paid=None,
        start_date=None,
        end_date=None,
        page=1,
        page_size=1_000_000,
        user=SimpleNamespace(role=ROLE_ADMIN, id=None, platform_id=None),
        db=db,
    )
    # The default platform id means "all platforms" to the stats: keep this platform only.
    own = {row[0] for row in db.query(Order.id).filter(Order.platform_id == platform_id).all()}
    return [task for task in stats.tasks if uuid.UUID(task.order_id) in own]


def pending_tasks(db: Session, platform_id: uuid.UUID) -> list[Any]:
    """Orders waiting for payment: credited (a submitted link) and not paid yet, with a known designer."""
    return [t for t in credited_tasks(db, platform_id) if t.placeholder_filled and not t.is_paid and t.designer_id]


def _actor_name(user: User) -> str:
    return user.full_name or user.username


def pay_orders(
    db: Session,
    *,
    actor: User,
    platform_id: uuid.UUID,
    order_ids: list[uuid.UUID],
    expected_versions: dict[uuid.UUID, int] | None = None,
    expected_total: int | None = None,
) -> PaymentResult:
    """Mark orders paid, close them in Tacahu (DONE), record one history row per designer, notify.

    With ``expected_total`` (the Accountant flow) the payment is all-or-nothing: every order must
    still be unpaid and the amounts must add up to exactly what the payer transferred, otherwise
    :class:`PaymentConflictError` and nothing changes. Without it (Admin) already-paid orders are
    skipped, so paying twice never records a second payment.
    """
    ids = list(dict.fromkeys(order_ids))
    if not ids:
        return PaymentResult(0)
    platform = db.get(Platform, platform_id)
    orders = (
        db.query(Order)
        .filter(Order.id.in_(ids), Order.platform_id == platform_id)
        .order_by(Order.id)
        .with_for_update()
        .all()
    )
    if expected_total is not None:
        if len(orders) != len(ids) or any(o.is_paid for o in orders):
            db.rollback()
            raise PaymentConflictError("Có đơn đã được thanh toán hoặc không còn tồn tại.")
        if sum(order_amount(o, platform) for o in orders) != expected_total:
            db.rollback()
            raise PaymentConflictError("Số tiền đã thay đổi so với lúc mở.")
    orders = [o for o in orders if not o.is_paid]
    if not orders:
        db.rollback()
        return PaymentResult(0)
    for order in orders:
        require_expected_order_version(order, (expected_versions or {}).get(order.id))

    credit = {uuid.UUID(t.order_id): t for t in credited_tasks(db, platform_id)}
    now = datetime.now(UTC)
    grouped: dict[str | None, list[Order]] = defaultdict(list)
    for order in orders:
        task = credit.get(order.id)
        grouped[task.designer_id if task else None].append(order)
        order.is_paid = True
        order.paid_at = now
        order.paid_by_id = actor.id
        if (order.state or "").upper() not in _CLOSED_STATES:
            previous_state = order.state
            order.state = OrderState.DONE.value
            order.status_changed_at = now
            db.add(
                WorkflowEvent(
                    order_id=order.id,
                    from_state=previous_state,
                    to_state=OrderState.DONE.value,
                    actor_id=actor.id,
                    evidence={"source": "finance", "action": "mark_paid", "actor_role": actor.role},
                )
            )

    batches = []
    for designer_id, designer_orders in grouped.items():
        task = credit.get(designer_orders[0].id)
        batch = _batch(
            platform_id=platform_id,
            paid_by=actor,
            designer_id=designer_id,
            designer_name=task.designer_name if task and designer_id else UNASSIGNED_NAME,
            orders=designer_orders,
            platform=platform,
            paid_at=now,
            source="payment",
        )
        db.add(batch)
        batches.append(batch)
    db.commit()

    _notify_designers(batches)
    return PaymentResult(len(orders), batches)


def _batch(
    *,
    platform_id: uuid.UUID | None,
    paid_by: User | None,
    designer_id: str | None,
    designer_name: str,
    orders: list[Order],
    platform: Platform | None,
    paid_at: datetime,
    source: str,
) -> PaymentBatch:
    items = [
        {
            "order_id": str(o.id),
            "external_order_id": o.external_order_id,
            "product_name": o.product_name,
            "amount": order_amount(o, platform),
        }
        for o in orders
    ]
    return PaymentBatch(
        platform_id=platform_id,
        paid_by_id=paid_by.id if paid_by else None,
        paid_by_name=_actor_name(paid_by) if paid_by else "Không rõ",
        paid_by_role=paid_by.role if paid_by else None,
        designer_id=uuid.UUID(designer_id) if designer_id else None,
        designer_name=designer_name,
        order_count=len(items),
        total_amount=sum(item["amount"] for item in items),
        items=items,
        source=source,
        paid_at=paid_at,
    )


def _notify_designers(batches: list[PaymentBatch]) -> None:
    try:
        from app.workers.telegram_tasks import (
            async_notify_designer_payment,
            safe_dispatch_telegram_task,
        )

        for batch in batches:
            if batch.designer_id:
                safe_dispatch_telegram_task(
                    async_notify_designer_payment, str(batch.designer_id), batch.order_count, batch.total_amount
                )
    except Exception:
        logger.exception("Failed to notify designers about payment batches %s", [str(b.id) for b in batches])


def backfill_payment_batches(db: Session) -> int:
    """Rebuild history rows for orders paid before ``payment_batches`` existed. Idempotent.

    One click of "pay" stamped every order with the same ``paid_at``, so (platform, payer,
    paid_at, credited designer) recovers each original payment. Orders already in a batch are
    skipped, which is what makes a re-run a no-op. Amounts use today's rates: the rate at the
    time was never stored.
    """
    recorded = {
        uuid.UUID(item["order_id"])
        for (items,) in db.query(PaymentBatch.items).all()
        for item in items
    }
    paid = [o for o in db.query(Order).filter(Order.is_paid.is_(True)).all() if o.id not in recorded]
    users = {u.id: u for u in db.query(User).all()}
    platforms = {p.id: p for p in db.query(Platform).all()}
    credit_by_platform: dict[uuid.UUID, dict[uuid.UUID, Any]] = {}

    groups: dict[tuple, list[Order]] = defaultdict(list)
    for order in paid:
        if order.platform_id not in credit_by_platform and order.platform_id is not None:
            credit_by_platform[order.platform_id] = {
                uuid.UUID(t.order_id): t for t in credited_tasks(db, order.platform_id)
            }
        task = credit_by_platform.get(order.platform_id, {}).get(order.id)
        paid_at = order.paid_at or order.updated_at or order.created_at
        key = (
            order.platform_id,
            order.paid_by_id,
            paid_at,
            task.designer_id if task else None,
            task.designer_name if task and task.designer_id else UNASSIGNED_NAME,
        )
        groups[key].append(order)

    for (platform_id, paid_by_id, paid_at, designer_id, designer_name), orders in groups.items():
        db.add(
            _batch(
                platform_id=platform_id,
                paid_by=users.get(paid_by_id) if paid_by_id else None,
                designer_id=designer_id,
                designer_name=designer_name,
                orders=orders,
                platform=platforms.get(platform_id) if platform_id else None,
                paid_at=paid_at,
                source="backfill",
            )
        )
    db.commit()
    return len(groups)

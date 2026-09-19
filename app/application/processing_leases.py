"""Short-lived, auditable processing leases for manual Designer work."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.adapters.db.models import Order, WorkflowEvent

PROCESSING_LEASE_TTL = timedelta(minutes=15)


class ProcessingLeaseConflictError(Exception):
    def __init__(self, order: Order) -> None:
        self.order_id = order.id
        self.expires_at = order.processing_lock_expires_at
        super().__init__("Đơn đang được người khác xử lý.")


class ProcessingLeasePermissionError(Exception):
    pass


def _is_active(order: Order, now: datetime) -> bool:
    return bool(
        order.processing_lock_owner_id
        and order.processing_lock_expires_at
        and order.processing_lock_expires_at > now
    )


def _event(session: Session, order: Order, actor_id: uuid.UUID, action: str, **evidence) -> None:
    session.add(WorkflowEvent(
        order_id=order.id,
        from_state=order.state,
        to_state=order.state,
        actor_id=actor_id,
        evidence={"source": "processing_lease", "action": action, **evidence},
    ))


def acquire_processing_lease(
    session: Session,
    order: Order,
    *,
    actor_id: uuid.UUID,
    takeover_reason: str | None = None,
) -> datetime:
    """Acquire or renew a lease on an already locked order.

    A live lease held by another user can only be replaced through the dedicated
    takeover endpoint, which supplies an audit reason.
    """
    now = datetime.now(UTC)
    active = _is_active(order, now)
    previous_owner = order.processing_lock_owner_id
    if active and previous_owner != actor_id:
        if not takeover_reason:
            raise ProcessingLeaseConflictError(order)
        _event(
            session, order, actor_id, "TAKEOVER",
            previous_owner_id=str(previous_owner), reason=takeover_reason,
        )
    elif previous_owner == actor_id and active:
        _event(session, order, actor_id, "HEARTBEAT")
    else:
        _event(session, order, actor_id, "ACQUIRE", expired_owner_id=str(previous_owner) if previous_owner else None)

    order.processing_lock_owner_id = actor_id
    order.processing_lock_acquired_at = now
    order.processing_lock_heartbeat_at = now
    order.processing_lock_expires_at = now + PROCESSING_LEASE_TTL
    session.add(order)
    session.flush()
    return order.processing_lock_expires_at


def heartbeat_processing_lease(session: Session, order: Order, *, actor_id: uuid.UUID) -> datetime:
    now = datetime.now(UTC)
    if not _is_active(order, now) or order.processing_lock_owner_id != actor_id:
        raise ProcessingLeaseConflictError(order)
    order.processing_lock_heartbeat_at = now
    order.processing_lock_expires_at = now + PROCESSING_LEASE_TTL
    _event(session, order, actor_id, "HEARTBEAT")
    session.add(order)
    session.flush()
    return order.processing_lock_expires_at


def require_processing_lease(order: Order, *, actor_id: uuid.UUID) -> None:
    if not _is_active(order, datetime.now(UTC)) or order.processing_lock_owner_id != actor_id:
        raise ProcessingLeaseConflictError(order)


def release_processing_lease(session: Session, order: Order, *, actor_id: uuid.UUID, reason: str) -> None:
    if order.processing_lock_owner_id is None:
        return
    _event(session, order, actor_id, "RELEASE", previous_owner_id=str(order.processing_lock_owner_id), reason=reason)
    order.processing_lock_owner_id = None
    order.processing_lock_acquired_at = None
    order.processing_lock_heartbeat_at = None
    order.processing_lock_expires_at = None
    session.add(order)
    session.flush()

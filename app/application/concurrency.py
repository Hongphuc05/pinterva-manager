"""Shared optimistic-concurrency primitives for order commands.

Phase 1 only establishes the contract. Individual mutation endpoints adopt these
helpers in later phases so legacy clients remain compatible during rollout.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.adapters.db.models import Order


class OrderVersionConflictError(Exception):
    """The caller attempted a command using an obsolete order revision."""

    def __init__(
        self,
        *,
        order_id: uuid.UUID,
        expected_version: int | None,
        current_version: int | None,
        changed_fields: list[str] | None = None,
    ) -> None:
        self.order_id = order_id
        self.expected_version = expected_version
        self.current_version = current_version
        self.changed_fields = changed_fields or []
        super().__init__("Order version conflict")

    def detail(self) -> dict:
        return {
            "code": "ORDER_VERSION_CONFLICT",
            "message": "Đơn đã được cập nhật bởi người khác. Hãy tải lại dữ liệu trước khi thử lại.",
            "order_id": str(self.order_id),
            "expected_version": self.expected_version,
            "current_version": self.current_version,
            "changed_fields": self.changed_fields,
        }


def require_expected_order_version(order: Order, expected_version: int | None) -> None:
    """Validate a client's optional rollout-era revision against the locked row."""
    if expected_version is None:
        return
    if order.version != expected_version:
        raise OrderVersionConflictError(
            order_id=order.id,
            expected_version=expected_version,
            current_version=order.version,
        )


def lock_order_for_command(
    session: Session,
    *,
    order_id: uuid.UUID,
    expected_version: int | None = None,
    platform_id: uuid.UUID | None = None,
) -> Order | None:
    """Read the current order under a short transaction lock, then validate it.

    The expected version is intentionally checked *after* `FOR UPDATE`: an order
    could change between an earlier client read and lock acquisition.
    """
    query = session.query(Order).filter(Order.id == order_id)
    if platform_id is not None:
        query = query.filter(Order.platform_id == platform_id)
    order = query.with_for_update().one_or_none()
    if order is not None:
        require_expected_order_version(order, expected_version)
    return order

"""HTTP contracts shared by order mutation endpoints."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class OrderCommandPayload(BaseModel):
    """Compatibility-safe base payload for the concurrency rollout.

    `expected_version` stays optional until every deployed frontend sends it.
    Command endpoints become strict in their respective migration phase.
    """

    expected_version: int | None = Field(default=None, ge=1)
    idempotency_key: UUID | None = None


class OrderCommandResult(BaseModel):
    order_id: UUID
    version: int


def stale_order_detail() -> dict:
    """Safe fallback when SQLAlchemy detects a stale row without command context."""
    return {
        "code": "ORDER_VERSION_CONFLICT",
        "message": "Đơn đã được cập nhật bởi người khác. Hãy tải lại dữ liệu trước khi thử lại.",
        "order_id": None,
        "expected_version": None,
        "current_version": None,
        "changed_fields": [],
    }

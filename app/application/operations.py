from __future__ import annotations

from collections.abc import Callable

from app.adapters.db.models import Operation


class OperationInProgressError(Exception):
    """Raised when the same idempotency key is already being processed."""


def run_idempotent(
    session,
    idempotency_key: str,
    command_name: str,
    fn: Callable[[], dict],
) -> dict:
    existing = (
        session.query(Operation).filter_by(idempotency_key=idempotency_key).one_or_none()
    )
    if existing is not None:
        if existing.status == "completed":
            return existing.result
        if existing.status == "pending":
            raise OperationInProgressError(idempotency_key)
        existing.retry_count += 1
    else:
        existing = Operation(
            idempotency_key=idempotency_key,
            command_name=command_name,
            status="pending",
        )
        session.add(existing)
        session.commit()

    try:
        result = fn()
    except Exception:
        existing.status = "failed"
        session.commit()
        raise

    existing.status = "completed"
    existing.result = result
    session.commit()
    return result

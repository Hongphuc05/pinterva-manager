from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.adapters.db.models import Operation

# ponytail: lease-based reclaim, not true cross-primitive atomicity with
# apply_transition — a crash between this ledger's commits and apply_transition's
# own commit leaves a "pending" row that only the lease below rescues. Upgrade to a
# single shared transaction if/when a Phase 2 Celery-worker command actually needs
# apply_transition + run_idempotent to commit/rollback as one unit.
PENDING_LEASE = timedelta(minutes=5)


class OperationInProgressError(Exception):
    """Raised when the same idempotency key is already being processed."""


class IdempotencyKeyReusedError(Exception):
    """Raised when a completed idempotency key is replayed with a different payload."""


def _lease_expired(operation: Operation) -> bool:
    """True when a `pending` row is stale enough to reclaim (its owner likely crashed)."""
    updated_at = operation.updated_at
    if updated_at is None:
        return False
    if updated_at.tzinfo is None:  # tolerate naive values from an older schema
        updated_at = updated_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - updated_at > PENDING_LEASE


def run_idempotent(
    session,
    idempotency_key: str,
    command_name: str,
    fn: Callable[[], dict],
    request_fingerprint: str | None = None,
) -> dict:
    existing = session.query(Operation).filter_by(idempotency_key=idempotency_key).one_or_none()
    claimed = False

    if existing is None:
        existing = Operation(
            idempotency_key=idempotency_key,
            command_name=command_name,
            request_fingerprint=request_fingerprint,
            status="pending",
        )
        session.add(existing)
        try:
            session.commit()
            claimed = True
        except IntegrityError:
            # A concurrent caller won the race on the unique idempotency_key; treat it
            # exactly as if the first query had returned that caller's row.
            session.rollback()
            existing = session.query(Operation).filter_by(idempotency_key=idempotency_key).one()

    if not claimed:
        if existing.status == "completed":
            stored = existing.request_fingerprint
            if (
                stored is not None
                and request_fingerprint is not None
                and stored != request_fingerprint
            ):
                raise IdempotencyKeyReusedError(idempotency_key)
            return existing.result
        if existing.status == "pending" and not _lease_expired(existing):
            raise OperationInProgressError(idempotency_key)
        existing.retry_count += 1
        # Commit before running fn() so `updated_at` (onupdate=now()) is renewed:
        # otherwise the row keeps its stale timestamp and a second worker would
        # reclaim the same lease while we are still working.
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

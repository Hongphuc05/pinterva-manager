import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, text

from app.application.operations import (
    PENDING_LEASE,
    IdempotencyKeyReusedError,
    OperationInProgressError,
    run_idempotent,
)

_INSERT_OPERATION = text(
    "INSERT INTO operations "
    "(id, idempotency_key, command_name, status, result, retry_count, created_at, updated_at) "
    "VALUES (:id, :key, 'test_command', :status, :result, 0, :ts, :ts)"
)


def _counter():
    calls = {"count": 0}

    def side_effect():
        calls["count"] += 1
        return {"value": calls["count"]}

    return calls, side_effect


def _insert_pending(db_session, key: str, age: timedelta) -> None:
    """Write a `pending` row with a backdated updated_at (no public API can do this)."""
    db_session.execute(
        _INSERT_OPERATION,
        {
            "id": uuid.uuid4(),
            "key": key,
            "status": "pending",
            "result": None,
            "ts": datetime.now(UTC) - age,
        },
    )
    db_session.commit()


def test_run_idempotent_executes_once_for_same_key(db_session):
    calls, side_effect = _counter()

    result1 = run_idempotent(db_session, "key-1", "test_command", side_effect)
    result2 = run_idempotent(db_session, "key-1", "test_command", side_effect)

    assert calls["count"] == 1
    assert result1 == {"value": 1}
    assert result2 == {"value": 1}


def test_run_idempotent_executes_again_for_different_key(db_session):
    calls, side_effect = _counter()

    run_idempotent(db_session, "key-a", "test_command", side_effect)
    run_idempotent(db_session, "key-b", "test_command", side_effect)

    assert calls["count"] == 2


# --- Finding 3: pending lease ------------------------------------------------


def test_fresh_pending_operation_still_blocks(db_session):
    calls, side_effect = _counter()
    _insert_pending(db_session, "key-fresh", age=PENDING_LEASE / 2)

    with pytest.raises(OperationInProgressError):
        run_idempotent(db_session, "key-fresh", "test_command", side_effect)

    assert calls["count"] == 0


def test_stale_pending_operation_is_reclaimed(db_session):
    calls, side_effect = _counter()
    _insert_pending(db_session, "key-stale", age=PENDING_LEASE + timedelta(minutes=1))

    result = run_idempotent(db_session, "key-stale", "test_command", side_effect)

    assert calls["count"] == 1
    assert result == {"value": 1}


def test_reclaiming_a_stale_operation_renews_the_lease(db_session, engine):
    """While the reclaimer works, the row must no longer look reclaimable to others."""
    _insert_pending(db_session, "key-renew", age=PENDING_LEASE + timedelta(minutes=1))

    def inner():
        with engine.connect() as conn:
            observed = conn.execute(
                text("SELECT updated_at FROM operations WHERE idempotency_key = 'key-renew'")
            ).scalar_one()
        assert datetime.now(UTC) - observed < PENDING_LEASE, "lease was not renewed"
        return {"ok": True}

    assert run_idempotent(db_session, "key-renew", "test_command", inner) == {"ok": True}


# --- Finding 4: concurrent insert race ---------------------------------------


def test_concurrent_insert_of_same_key_falls_through_to_existing_row(db_session, engine):
    """A competitor inserts the same key between our SELECT and our INSERT.

    `before_flush` fires exactly in that window, so the race is deterministic: the
    guard must swallow the IntegrityError and reuse the competitor's row instead of
    letting the unique-constraint violation escape.
    """
    calls, side_effect = _counter()

    fired = []

    @event.listens_for(db_session, "before_flush")
    def _competitor(sess, flush_context, instances):
        if fired:  # one-shot; can't event.remove() from inside the dispatch
            return
        fired.append(True)
        with engine.begin() as conn:  # independent connection, commits immediately
            conn.execute(
                _INSERT_OPERATION,
                {
                    "id": uuid.uuid4(),
                    "key": "key-race",
                    "status": "completed",
                    "result": '{"value": "from-competitor"}',
                    "ts": datetime.now(UTC),
                },
            )

    result = run_idempotent(db_session, "key-race", "test_command", side_effect)

    assert result == {"value": "from-competitor"}
    assert calls["count"] == 0  # the competitor already did the work


# --- Finding 9B: request fingerprint -----------------------------------------


def test_same_key_same_fingerprint_returns_cached_result(db_session):
    calls, side_effect = _counter()

    run_idempotent(db_session, "key-fp", "test_command", side_effect, request_fingerprint="abc")
    result = run_idempotent(
        db_session, "key-fp", "test_command", side_effect, request_fingerprint="abc"
    )

    assert calls["count"] == 1
    assert result == {"value": 1}


def test_same_key_different_fingerprint_is_rejected(db_session):
    calls, side_effect = _counter()

    run_idempotent(db_session, "key-fp2", "test_command", side_effect, request_fingerprint="abc")

    with pytest.raises(IdempotencyKeyReusedError):
        run_idempotent(
            db_session, "key-fp2", "test_command", side_effect, request_fingerprint="different"
        )

    assert calls["count"] == 1


def test_missing_fingerprint_skips_the_comparison(db_session):
    calls, side_effect = _counter()

    run_idempotent(db_session, "key-fp3", "test_command", side_effect, request_fingerprint="abc")
    # a caller that passes no fingerprint must still get the cached result
    result = run_idempotent(db_session, "key-fp3", "test_command", side_effect)

    assert calls["count"] == 1
    assert result == {"value": 1}

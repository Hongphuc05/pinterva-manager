from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.db.models import Order, User, WorkflowEvent
from app.application.processing_leases import (
    ProcessingLeaseConflictError,
    acquire_processing_lease,
    heartbeat_processing_lease,
    release_processing_lease,
)


def _user(db_session, username: str) -> User:
    user = User(username=username, full_name=username, role="designer", password_hash="hash")
    db_session.add(user)
    db_session.commit()
    return user


def test_processing_lease_blocks_another_owner_and_records_takeover(db_session):
    first = _user(db_session, "lease-first")
    second = _user(db_session, "lease-second")
    order = Order(external_order_id="LEASE-1")
    db_session.add(order)
    db_session.commit()

    acquire_processing_lease(db_session, order, actor_id=first.id)
    with pytest.raises(ProcessingLeaseConflictError):
        acquire_processing_lease(db_session, order, actor_id=second.id)

    expires_at = acquire_processing_lease(
        db_session, order, actor_id=second.id, takeover_reason="Designer trước đã bàn giao ca"
    )
    db_session.commit()

    assert order.processing_lock_owner_id == second.id
    assert expires_at > datetime.now(UTC)
    actions = [
        event.evidence["action"]
        for event in db_session.query(WorkflowEvent).filter_by(order_id=order.id).all()
    ]
    assert "TAKEOVER" in actions


def test_heartbeat_renews_and_release_clears_processing_lease(db_session):
    owner = _user(db_session, "lease-owner")
    order = Order(external_order_id="LEASE-2")
    db_session.add(order)
    db_session.commit()

    acquire_processing_lease(db_session, order, actor_id=owner.id)
    order.processing_lock_expires_at = datetime.now(UTC) + timedelta(minutes=1)
    renewed = heartbeat_processing_lease(db_session, order, actor_id=owner.id)
    release_processing_lease(db_session, order, actor_id=owner.id, reason="result_submitted")
    db_session.commit()

    assert renewed > datetime.now(UTC)
    assert order.processing_lock_owner_id is None
    assert order.processing_lock_expires_at is None


def test_heartbeat_does_not_increment_the_business_order_version(db_session):
    owner = _user(db_session, "lease-version-owner")
    order = Order(external_order_id="LEASE-VERSION")
    db_session.add(order)
    db_session.commit()

    acquire_processing_lease(db_session, order, actor_id=owner.id)
    db_session.commit()
    version_before_heartbeat = order.version

    heartbeat_processing_lease(db_session, order, actor_id=owner.id)
    db_session.commit()
    db_session.refresh(order)

    assert order.version == version_before_heartbeat

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.adapters.db.models import Order
from app.application.concurrency import OrderVersionConflictError, lock_order_for_command
from app.domain.models import OrderState


def test_order_mapper_rejects_a_stale_second_session_write(engine):
    """Phase-0 baseline: Order.version already prevents ORM last-write-wins.

    The API has not exposed expected_version yet. This test protects the existing
    database-level foundation while later phases turn it into a user-facing 409
    contract.
    """
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed_session = session_factory()
    try:
        order = Order(external_order_id="DJ-CONCURRENCY-001", state=OrderState.OPEN.value)
        seed_session.add(order)
        seed_session.commit()
        order_id = order.id
        initial_version = order.version
    finally:
        seed_session.close()

    first_session = session_factory()
    second_session = session_factory()
    try:
        first_order = first_session.get(Order, order_id)
        second_order = second_session.get(Order, order_id)

        first_order.designer_note = "First writer"
        first_session.commit()

        second_order.designer_note = "Stale second writer"
        try:
            second_session.commit()
        except StaleDataError:
            second_session.rollback()
        else:
            raise AssertionError("A stale order write must raise StaleDataError")

        verifier = session_factory()
        try:
            persisted = verifier.get(Order, order_id)
            assert persisted.designer_note == "First writer"
            assert persisted.version == initial_version + 1
        finally:
            verifier.close()
    finally:
        first_session.close()
        second_session.close()


def test_lock_order_for_command_validates_revision_after_lock(db_session):
    order = Order(external_order_id="DJ-CONCURRENCY-002", state=OrderState.OPEN.value)
    db_session.add(order)
    db_session.commit()

    locked = lock_order_for_command(
        db_session,
        order_id=order.id,
        expected_version=order.version,
    )
    assert locked is order

    with pytest.raises(OrderVersionConflictError) as raised:
        lock_order_for_command(
            db_session,
            order_id=order.id,
            expected_version=order.version + 1,
        )

    assert raised.value.detail()["current_version"] == order.version

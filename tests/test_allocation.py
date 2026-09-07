import uuid

from app.adapters.allocation.reference import ReferenceAllocationTool
from app.adapters.db.models import Assignment, Batch, Order, User
from app.application.allocation import (
    create_assignment_draft,
    open_allocation,
    request_quantity,
)
from app.application.auth import hash_password
from app.domain.exceptions import CapacityExceededError
from app.domain.models import OrderState


def _seed_batch_with_orders(db_session, n=3):
    batch = Batch(source="printerval_crawl", owner="ntth", count=n)
    db_session.add(batch)
    db_session.flush()
    orders = []
    for i in range(n):
        order = Order(
            external_order_id=f"DJ{i:07d}",
            batch_id=batch.id,
            state=OrderState.CLAIMED_IMPORTED.value,
        )
        db_session.add(order)
        orders.append(order)
    db_session.commit()
    return batch, orders


def _seed_designer(db_session, capacity=None, username="designer1"):
    user = User(
        username=username, full_name=username, role="designer",
        password_hash=hash_password("s3cret!"), capacity=capacity,
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_open_allocation_transitions_all_claimed_orders(db_session):
    batch, orders = _seed_batch_with_orders(db_session)

    result = open_allocation(db_session, batch.id, "open:1")

    assert set(result["order_ids"]) == {o.external_order_id for o in orders}
    for order in orders:
        db_session.refresh(order)
        assert order.state == OrderState.OPEN_FOR_ALLOCATION.value


def test_request_quantity_grants_contiguous_block_in_order(db_session):
    batch, orders = _seed_batch_with_orders(db_session, n=5)
    open_allocation(db_session, batch.id, "open:2")
    designer = _seed_designer(db_session)
    tool = ReferenceAllocationTool()

    result = request_quantity(db_session, tool, designer.id, batch.id, 2, "req:1")

    assert result["granted_order_ids"] == ["DJ0000000", "DJ0000001"]
    assignments = db_session.query(Assignment).filter_by(designer_id=designer.id).all()
    assert len(assignments) == 2
    assert all(a.status == "draft" for a in assignments)


def test_request_quantity_second_caller_gets_the_remaining_block(db_session):
    batch, orders = _seed_batch_with_orders(db_session, n=3)
    open_allocation(db_session, batch.id, "open:3")
    d1 = _seed_designer(db_session, username="d1")
    d2 = _seed_designer(db_session, username="d2")
    tool = ReferenceAllocationTool()

    r1 = request_quantity(db_session, tool, d1.id, batch.id, 2, "req:a")
    r2 = request_quantity(db_session, tool, d2.id, batch.id, 2, "req:b")

    assert r1["granted_order_ids"] == ["DJ0000000", "DJ0000001"]
    assert r2["granted_order_ids"] == ["DJ0000002"]  # only 1 left, not an error


def test_request_quantity_rejects_over_capacity(db_session):
    batch, orders = _seed_batch_with_orders(db_session, n=5)
    open_allocation(db_session, batch.id, "open:4")
    designer = _seed_designer(db_session, capacity=1)
    tool = ReferenceAllocationTool()

    try:
        request_quantity(db_session, tool, designer.id, batch.id, 2, "req:c")
        assert False, "expected CapacityExceededError"
    except CapacityExceededError:
        pass

    assert db_session.query(Assignment).count() == 0


def test_create_assignment_draft_grants_a_single_named_order(db_session):
    batch, orders = _seed_batch_with_orders(db_session, n=2)
    open_allocation(db_session, batch.id, "open:5")
    designer = _seed_designer(db_session)
    admin = User(
        username="admin1", full_name="Admin", role="admin", password_hash=hash_password("s3cret!")
    )
    db_session.add(admin)
    db_session.commit()

    result = create_assignment_draft(
        db_session, orders[1].external_order_id, designer.id, admin.id, "draft:1"
    )

    assignment = db_session.get(Assignment, uuid.UUID(result["assignment_id"]))
    assert assignment.order_id == orders[1].id
    db_session.refresh(orders[1])
    assert orders[1].state == OrderState.ASSIGNMENT_PENDING_APPROVAL.value

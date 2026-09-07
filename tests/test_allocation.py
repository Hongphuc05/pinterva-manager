import uuid

from app.adapters.allocation.reference import ReferenceAllocationTool
from app.adapters.db.models import ApprovalRequest, Assignment, Batch, Order, User
from app.application.allocation import (
    create_assignment_draft,
    decide_assignment,
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


def _draft_one_assignment(db_session):
    batch, orders = _seed_batch_with_orders(db_session, n=3)
    open_allocation(db_session, batch.id, f"open:{uuid.uuid4()}")
    designer = _seed_designer(db_session, username=f"d-{uuid.uuid4()}")
    admin = User(
        username=f"admin-{uuid.uuid4()}", full_name="Admin", role="admin",
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(admin)
    db_session.commit()
    tool = ReferenceAllocationTool()
    request_quantity(db_session, tool, designer.id, batch.id, 1, f"req:{uuid.uuid4()}")
    order = db_session.query(Order).filter_by(external_order_id="DJ0000000").one()
    assignment = db_session.query(Assignment).filter_by(order_id=order.id).one()
    approval = db_session.query(ApprovalRequest).filter_by(target_id=assignment.id).one()
    return batch, orders, designer, admin, approval, assignment, tool


def test_decide_assignment_approve_moves_order_to_assigned(db_session):
    _, _, _, admin, approval, assignment, tool = _draft_one_assignment(db_session)

    result = decide_assignment(
        db_session, tool, approval.id, "approve", admin.id, f"decide:{uuid.uuid4()}"
    )

    assert result["decision"] == "approve"
    db_session.refresh(assignment)
    assert assignment.status == "approved"
    order = db_session.query(Order).filter_by(id=assignment.order_id).one()
    assert order.state == OrderState.ASSIGNED.value


def test_decide_assignment_cancel_releases_order_and_grants_a_replacement(db_session):
    batch, orders, designer, admin, approval, assignment, tool = _draft_one_assignment(db_session)

    result = decide_assignment(
        db_session, tool, approval.id, "cancel", admin.id, f"decide:{uuid.uuid4()}",
        reason="đã làm rồi",
    )

    assert result["decision"] == "cancel"
    db_session.refresh(assignment)
    assert assignment.status == "cancelled"
    assert assignment.cancel_reason == "đã làm rồi"
    cancelled_order = db_session.query(Order).filter_by(id=assignment.order_id).one()
    assert cancelled_order.state == OrderState.OPEN_FOR_ALLOCATION.value

    assert len(result["replacement_assignment_ids"]) == 1
    replacement = db_session.get(Assignment, uuid.UUID(result["replacement_assignment_ids"][0]))
    assert replacement.designer_id == designer.id
    assert replacement.replacement_of_id == assignment.id


def test_decide_assignment_cancel_with_no_reason_raises(db_session):
    _, _, _, admin, approval, _, tool = _draft_one_assignment(db_session)

    try:
        decide_assignment(
            db_session, tool, approval.id, "cancel", admin.id, f"decide:{uuid.uuid4()}"
        )
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_decide_assignment_second_call_on_same_approval_returns_first_result_unchanged(db_session):
    """Multi-admin race, claude.md §10: the second admin's attempt must not
    re-execute the decision — it gets the first admin's result back, letting the
    API tell them it was already handled."""
    _, _, _, admin, approval, assignment, tool = _draft_one_assignment(db_session)
    other_admin = User(
        username=f"admin2-{uuid.uuid4()}", full_name="Other Admin", role="admin",
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(other_admin)
    db_session.commit()

    key = f"decide:{approval.id}"  # same key both times, keyed by approval only
    first = decide_assignment(db_session, tool, approval.id, "approve", admin.id, key)
    second = decide_assignment(
        db_session, tool, approval.id, "cancel", other_admin.id, key, reason="x"
    )

    assert second == first
    assert second["actor_id"] == str(admin.id)  # the FIRST actor, not other_admin
    db_session.refresh(assignment)
    assert assignment.status == "approved"  # cancel from the second call never ran

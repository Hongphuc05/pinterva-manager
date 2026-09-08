import threading
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.adapters.allocation.reference import ReferenceAllocationTool
from app.adapters.db.models import ApprovalRequest, Assignment, Batch, Order, User
from app.application.allocation import (
    create_assignment_draft,
    decide_assignment,
    open_allocation,
    request_quantity,
)
from app.application.auth import hash_password
from app.domain.exceptions import ApprovalAlreadyDecidedError, CapacityExceededError
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
    assert orders[1].state == OrderState.IN_PROGRESS.value


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


def test_decide_assignment_cancel_sends_cancelled_order_to_exception_and_grants_replacement(
    db_session,
):
    # Assign the SECOND order (not the earliest) so that after cancel, the
    # cancelled order goes to EXCEPTION (never back to the pool — see the sibling
    # test below) while a genuinely different order (the earliest still-available
    # one, orders[0]) is what FIFO picks as the replacement — orders[0] was never
    # touched, so it sorts first.
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

    draft = create_assignment_draft(
        db_session, orders[1].external_order_id, designer.id, admin.id, f"draft:{uuid.uuid4()}"
    )
    assignment = db_session.get(Assignment, uuid.UUID(draft["assignment_id"]))
    approval = db_session.query(ApprovalRequest).filter_by(target_id=assignment.id).one()

    result = decide_assignment(
        db_session, tool, approval.id, "cancel", admin.id, f"decide:{uuid.uuid4()}",
        reason="đã làm rồi",
    )

    assert result["decision"] == "cancel"
    db_session.refresh(assignment)
    assert assignment.status == "cancelled"
    assert assignment.cancel_reason == "đã làm rồi"
    cancelled_order = db_session.query(Order).filter_by(id=assignment.order_id).one()
    assert cancelled_order.state == OrderState.EXCEPTION.value

    assert len(result["replacement_assignment_ids"]) == 1
    replacement = db_session.get(Assignment, uuid.UUID(result["replacement_assignment_ids"][0]))
    assert replacement.designer_id == designer.id
    assert replacement.replacement_of_id == assignment.id
    assert replacement.order_id == orders[0].id  # earliest available, not the cancelled order


def test_decide_assignment_cancel_sends_order_to_exception_not_back_to_pool(db_session):
    """Cancel must not let the released order re-enter the pool at all — moving
    it to EXCEPTION (not OPEN_FOR_ALLOCATION) is what stops FIFO from re-granting
    the very order just cancelled back to the same designer."""
    from app.application.allocation import _remaining_order_ids

    batch, orders = _seed_batch_with_orders(db_session, n=1)
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

    result = decide_assignment(
        db_session, tool, approval.id, "cancel", admin.id, f"decide:{uuid.uuid4()}", reason="test"
    )

    db_session.refresh(order)
    assert order.state == OrderState.EXCEPTION.value
    assert result["replacement_assignment_ids"] == []  # batch had only this one order
    assert order.id not in {o.id for o in _remaining_order_ids(db_session, batch.id)}


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


def test_decide_assignment_raises_when_approval_already_decided_under_a_different_key(db_session):
    """`run_idempotent`'s cache only protects a *replayed* idempotency_key. A
    second decide_assignment call on the SAME approval with a DIFFERENT key must
    still be rejected — the state machine allows ASSIGNED -> EXCEPTION, so
    without this check a second call would silently cancel an already-approved
    assignment."""
    _, _, _, admin, approval, assignment, tool = _draft_one_assignment(db_session)
    other_admin = User(
        username=f"admin3-{uuid.uuid4()}", full_name="Other Admin", role="admin",
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(other_admin)
    db_session.commit()

    decide_assignment(db_session, tool, approval.id, "approve", admin.id, f"decide:{uuid.uuid4()}")

    with pytest.raises(ApprovalAlreadyDecidedError) as exc_info:
        decide_assignment(
            db_session, tool, approval.id, "cancel", other_admin.id, f"decide:{uuid.uuid4()}",
            reason="different key entirely",
        )

    assert exc_info.value.status == "approved"
    assert exc_info.value.actor_id == admin.id
    db_session.refresh(assignment)
    assert assignment.status == "approved"  # never cancelled by the second call
    order = db_session.query(Order).filter_by(id=assignment.order_id).one()
    assert order.state == OrderState.ASSIGNED.value  # never moved to EXCEPTION


def test_request_quantity_concurrent_offers_on_same_batch_do_not_double_grant(engine):
    """Real concurrency test for I1: two designers race to offer on a 2-order
    batch. Each runs in its own thread with its own DB session/transaction. If
    the FOR UPDATE lock in `_remaining_order_ids` were released mid-grant (the
    bug: `apply_transition` used to commit per-order), the second thread could
    read a stale snapshot and grant an order the first thread already holds.
    With the fix (the whole grant runs in one transaction, committed once by
    run_idempotent), the second thread instead blocks until the first commits,
    then sees the updated state."""
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    setup = session_factory()
    batch = Batch(source="printerval_crawl", owner="ntth", count=2)
    setup.add(batch)
    setup.flush()
    for i in range(2):
        setup.add(
            Order(
                external_order_id=f"CC{i:07d}", batch_id=batch.id,
                state=OrderState.OPEN_FOR_ALLOCATION.value,
            )
        )
    d1 = User(
        username="cd1", full_name="cd1", role="designer", password_hash=hash_password("s3cret!")
    )
    d2 = User(
        username="cd2", full_name="cd2", role="designer", password_hash=hash_password("s3cret!")
    )
    setup.add(d1)
    setup.add(d2)
    setup.commit()
    batch_id, d1_id, d2_id = batch.id, d1.id, d2.id
    setup.close()

    results: dict[str, dict] = {}
    errors: dict[str, Exception] = {}

    def worker(name: str, designer_id: uuid.UUID) -> None:
        session = session_factory()
        try:
            results[name] = request_quantity(
                session, ReferenceAllocationTool(), designer_id, batch_id, 2, f"concurrent:{name}"
            )
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors[name] = exc
        finally:
            session.close()

    t1 = threading.Thread(target=worker, args=("A", d1_id))
    t2 = threading.Thread(target=worker, args=("B", d2_id))
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert not errors, errors
    all_granted = results["A"]["granted_order_ids"] + results["B"]["granted_order_ids"]
    assert len(all_granted) == 2  # only 2 orders exist in the batch
    assert len(set(all_granted)) == 2  # no order granted to both designers


def test_request_quantity_concurrent_offers_for_one_designer_do_not_exceed_capacity(
    engine,
):
    """Capacity is global to a designer, including concurrent offers to
    different batches.  Both requests start together; the designer-row lock
    makes one complete before the other rechecks its held count."""
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    setup = session_factory()
    batches = [
        Batch(source="printerval_crawl", owner="ntth", count=2),
        Batch(source="printerval_crawl", owner="ntth", count=2),
    ]
    setup.add_all(batches)
    setup.flush()
    for prefix, batch in (("CA", batches[0]), ("CB", batches[1])):
        for i in range(2):
            setup.add(
                Order(
                    external_order_id=f"{prefix}{i:07d}",
                    batch_id=batch.id,
                    state=OrderState.OPEN_FOR_ALLOCATION.value,
                )
            )
    designer = User(
        username="capacity-race", full_name="capacity-race", role="designer",
        password_hash=hash_password("s3cret!"), capacity=2,
    )
    setup.add(designer)
    setup.commit()
    batch_ids, designer_id = [batch.id for batch in batches], designer.id
    setup.close()

    start_barrier = threading.Barrier(2)
    errors: dict[str, Exception] = {}

    def worker(name: str, batch_id: uuid.UUID) -> None:
        session = session_factory()
        try:
            start_barrier.wait(timeout=10)
            request_quantity(
                session, ReferenceAllocationTool(), designer_id, batch_id, 2, f"capacity:{name}"
            )
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors[name] = exc
        finally:
            session.close()

    threads = [
        threading.Thread(target=worker, args=("A", batch_ids[0])),
        threading.Thread(target=worker, args=("B", batch_ids[1])),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert len(errors) == 1
    assert isinstance(next(iter(errors.values())), CapacityExceededError)
    verifier = session_factory()
    try:
        held = (
            verifier.query(Assignment)
            .filter(
                Assignment.designer_id == designer_id,
                Assignment.status.in_(["draft", "approved"]),
            )
            .count()
        )
    finally:
        verifier.close()
    assert held <= 2

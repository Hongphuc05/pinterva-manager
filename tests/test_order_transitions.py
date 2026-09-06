import pytest

from app.adapters.db.models import Order, WorkflowEvent
from app.domain.exceptions import InvalidTransitionError
from app.domain.models import OrderState


def _make_order(db_session, external_id="DJ0000001"):
    order = Order(external_order_id=external_id, state=OrderState.DISCOVERED.value)
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)
    return order


def test_apply_transition_updates_state_and_writes_event(db_session):
    from app.application.order_transitions import apply_transition

    order = _make_order(db_session)
    initial_version = order.version

    event = apply_transition(
        db_session, order, OrderState.CLAIMED_IMPORTED, actor_id=None, evidence={"note": "claimed"}
    )

    assert order.state == OrderState.CLAIMED_IMPORTED.value
    assert order.version > initial_version
    assert event.from_state == OrderState.DISCOVERED.value
    assert event.to_state == OrderState.CLAIMED_IMPORTED.value
    assert event.evidence == {"note": "claimed"}


def test_apply_transition_rejects_invalid_transition(db_session):
    from app.application.order_transitions import apply_transition

    order = _make_order(db_session, external_id="DJ0000002")

    with pytest.raises(InvalidTransitionError):
        apply_transition(db_session, order, OrderState.DONE, actor_id=None, evidence={})

    db_session.refresh(order)
    assert order.state == OrderState.DISCOVERED.value


def test_workflow_events_are_append_only(db_session):
    from app.application.order_transitions import apply_transition

    order = _make_order(db_session, external_id="DJ0000003")
    apply_transition(db_session, order, OrderState.CLAIMED_IMPORTED, actor_id=None, evidence={})
    apply_transition(db_session, order, OrderState.OPEN_FOR_ALLOCATION, actor_id=None, evidence={})

    events = (
        db_session.query(WorkflowEvent)
        .filter_by(order_id=order.id)
        .order_by(WorkflowEvent.created_at)
        .all()
    )
    assert [e.to_state for e in events] == [
        OrderState.CLAIMED_IMPORTED.value,
        OrderState.OPEN_FOR_ALLOCATION.value,
    ]

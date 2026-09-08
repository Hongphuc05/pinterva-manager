import pytest

from app.adapters.db.models import Order, WorkflowEvent
from app.domain.exceptions import InvalidTransitionError
from app.domain.models import OrderState


def _make_order(db_session, external_id="DJ0000001"):
    order = Order(external_order_id=external_id, state=OrderState.OPEN.value)
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)
    return order


def test_apply_transition_updates_state_and_writes_event(db_session):
    from app.application.order_transitions import apply_transition

    order = _make_order(db_session)

    event = apply_transition(
        db_session, order, OrderState.IN_PROGRESS, actor_id=None, evidence={"note": "in_progress"}
    )

    assert order.state == OrderState.IN_PROGRESS.value
    assert event.from_state == OrderState.OPEN.value
    assert event.to_state == OrderState.IN_PROGRESS.value
    assert event.evidence == {"note": "in_progress"}


def test_apply_transition_rejects_invalid_transition(db_session):
    from app.application.order_transitions import apply_transition

    order = _make_order(db_session, external_id="DJ0000002")

    with pytest.raises(InvalidTransitionError):
        apply_transition(db_session, order, OrderState.DONE, actor_id=None, evidence={})

    db_session.refresh(order)
    assert order.state == OrderState.OPEN.value


def test_workflow_events_are_append_only(db_session):
    from app.application.order_transitions import apply_transition

    order = _make_order(db_session, external_id="DJ0000003")
    apply_transition(db_session, order, OrderState.IN_PROGRESS, actor_id=None, evidence={})
    apply_transition(db_session, order, OrderState.QC_PENDING, actor_id=None, evidence={})

    events = (
        db_session.query(WorkflowEvent)
        .filter_by(order_id=order.id)
        .order_by(WorkflowEvent.created_at)
        .all()
    )
    assert [e.to_state for e in events] == [
        OrderState.IN_PROGRESS.value,
        OrderState.QC_PENDING.value,
    ]

import pytest

from app.domain.exceptions import InvalidTransitionError
from app.domain.models import OrderState
from app.domain.state_machine import ALLOWED_TRANSITIONS, validate_transition


def test_valid_transition_does_not_raise():
    validate_transition(OrderState.OPEN, OrderState.IN_PROGRESS)


def test_invalid_transition_raises():
    with pytest.raises(InvalidTransitionError):
        validate_transition(OrderState.OPEN, OrderState.DONE)


def test_done_can_return_to_each_operational_tab_but_cancelled_only_escalates_to_exception():
    for state in (OrderState.CANCELLED,):
        with pytest.raises(InvalidTransitionError):
            validate_transition(state, OrderState.IN_PROGRESS)
        validate_transition(state, OrderState.EXCEPTION)

    for target in (OrderState.WAITING, OrderState.IN_PROGRESS, OrderState.QC_PENDING, OrderState.REVISION):
        validate_transition(OrderState.DONE, target)
    assert ALLOWED_TRANSITIONS[OrderState.DONE] == {
        OrderState.WAITING,
        OrderState.IN_PROGRESS,
        OrderState.QC_PENDING,
        OrderState.REVISION,
        OrderState.EXCEPTION,
    }
    assert ALLOWED_TRANSITIONS[OrderState.CANCELLED] == {OrderState.EXCEPTION}


def test_every_state_can_enter_exception():
    for state in OrderState:
        if state is OrderState.EXCEPTION:
            continue
        validate_transition(state, OrderState.EXCEPTION)


def test_qc_pending_allows_outcomes():
    for target in (
        OrderState.DONE,
        OrderState.REVISION,
        OrderState.CANCELLED,
    ):
        validate_transition(OrderState.QC_PENDING, target)

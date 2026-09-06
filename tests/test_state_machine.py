import pytest

from app.domain.exceptions import InvalidTransitionError
from app.domain.models import OrderState
from app.domain.state_machine import validate_transition


def test_valid_transition_does_not_raise():
    validate_transition(OrderState.DISCOVERED, OrderState.CLAIMED_IMPORTED)


def test_invalid_transition_raises():
    with pytest.raises(InvalidTransitionError):
        validate_transition(OrderState.DISCOVERED, OrderState.DONE)


def test_terminal_states_have_no_outgoing_transitions():
    for state in (OrderState.DONE, OrderState.CANCELLED, OrderState.SKIPPED):
        with pytest.raises(InvalidTransitionError):
            validate_transition(state, OrderState.IN_PROGRESS)


def test_qc_pending_allows_all_four_outcomes():
    for target in (
        OrderState.SUBMITTING_TO_SITE,
        OrderState.REVISION_REQUESTED,
        OrderState.SKIPPED,
        OrderState.CANCELLED,
    ):
        validate_transition(OrderState.QC_PENDING, target)


def test_assignment_pending_approval_cancel_path_returns_to_allocation():
    validate_transition(
        OrderState.ASSIGNMENT_PENDING_APPROVAL, OrderState.OPEN_FOR_ALLOCATION
    )


def test_reassignment_required_returns_to_allocation():
    validate_transition(OrderState.REASSIGNMENT_REQUIRED, OrderState.OPEN_FOR_ALLOCATION)

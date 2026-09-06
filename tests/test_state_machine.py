import pytest

from app.domain.exceptions import InvalidTransitionError
from app.domain.models import OrderState
from app.domain.state_machine import ALLOWED_TRANSITIONS, validate_transition


def test_valid_transition_does_not_raise():
    validate_transition(OrderState.DISCOVERED, OrderState.CLAIMED_IMPORTED)


def test_invalid_transition_raises():
    with pytest.raises(InvalidTransitionError):
        validate_transition(OrderState.DISCOVERED, OrderState.DONE)


def test_terminal_states_only_escalate_to_exception():
    # claude.md §5: any state can enter EXCEPTION, so terminal states are not sinks —
    # but they still must not re-enter the happy path directly.
    for state in (OrderState.DONE, OrderState.CANCELLED, OrderState.SKIPPED):
        with pytest.raises(InvalidTransitionError):
            validate_transition(state, OrderState.IN_PROGRESS)
        validate_transition(state, OrderState.EXCEPTION)

    assert ALLOWED_TRANSITIONS[OrderState.DONE] == {OrderState.EXCEPTION}
    assert ALLOWED_TRANSITIONS[OrderState.CANCELLED] == {OrderState.EXCEPTION}
    assert ALLOWED_TRANSITIONS[OrderState.SKIPPED] == {OrderState.DONE, OrderState.EXCEPTION}


def test_skipped_can_reconcile_to_done_or_exception():
    # QC "Skip" hands the order to the site and schedules a reconcile; the reconcile
    # either confirms completion (DONE) or lands in the exception queue.
    validate_transition(OrderState.SKIPPED, OrderState.DONE)
    validate_transition(OrderState.SKIPPED, OrderState.EXCEPTION)


def test_every_state_can_enter_exception():
    for state in OrderState:
        if state is OrderState.EXCEPTION:
            continue
        validate_transition(state, OrderState.EXCEPTION)


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

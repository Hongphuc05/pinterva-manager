from app.domain.exceptions import InvalidTransitionError
from app.domain.models import OrderState

# Matches claude.md §5. EXCEPTION can be entered from any state and, once there,
# only leaves via an explicit recovery command chosen by the operator — this table
# allows any EXCEPTION -> X transition; the application layer is responsible for
# only ever calling apply_transition() out of EXCEPTION from that explicit recovery
# command, never automatically.
ALLOWED_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.DISCOVERED: {OrderState.CLAIMED_IMPORTED, OrderState.EXCEPTION},
    OrderState.CLAIMED_IMPORTED: {OrderState.OPEN_FOR_ALLOCATION, OrderState.EXCEPTION},
    OrderState.OPEN_FOR_ALLOCATION: {
        OrderState.ASSIGNMENT_PENDING_APPROVAL,
        OrderState.EXCEPTION,
    },
    OrderState.ASSIGNMENT_PENDING_APPROVAL: {
        OrderState.ASSIGNED,
        OrderState.OPEN_FOR_ALLOCATION,
        OrderState.EXCEPTION,
    },
    OrderState.ASSIGNED: {OrderState.IN_PROGRESS, OrderState.EXCEPTION},
    OrderState.IN_PROGRESS: {
        OrderState.RESULT_SUBMITTED,
        OrderState.REASSIGNMENT_REQUIRED,
        OrderState.EXCEPTION,
    },
    OrderState.RESULT_SUBMITTED: {OrderState.QC_PENDING, OrderState.EXCEPTION},
    OrderState.QC_PENDING: {
        OrderState.SUBMITTING_TO_SITE,
        OrderState.REVISION_REQUESTED,
        OrderState.SKIPPED,
        OrderState.CANCELLED,
        OrderState.EXCEPTION,
    },
    OrderState.SUBMITTING_TO_SITE: {OrderState.DONE, OrderState.EXCEPTION},
    OrderState.REVISION_REQUESTED: {OrderState.IN_PROGRESS, OrderState.EXCEPTION},
    OrderState.REASSIGNMENT_REQUIRED: {OrderState.OPEN_FOR_ALLOCATION, OrderState.EXCEPTION},
    # Terminal states are terminal for the happy path only. claude.md §5 requires that
    # *any* state can still be escalated into EXCEPTION (e.g. a DONE order later found
    # mismatched on the external site — claude.md §12.1 group 3), and a SKIPPED order
    # reaches DONE once reconciliation confirms the site finished it.
    OrderState.SKIPPED: {OrderState.DONE, OrderState.EXCEPTION},
    OrderState.DONE: {OrderState.EXCEPTION},
    OrderState.CANCELLED: {OrderState.EXCEPTION},
    OrderState.EXCEPTION: set(OrderState),
}


def validate_transition(current: OrderState, target: OrderState) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransitionError(current, target)

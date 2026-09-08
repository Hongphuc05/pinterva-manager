from app.domain.exceptions import InvalidTransitionError
from app.domain.models import OrderState

# Matches claude.md §5. EXCEPTION can be entered from any state and, once there,
# only leaves via an explicit recovery command chosen by the operator — this table
# allows any EXCEPTION -> X transition; the application layer is responsible for
# only ever calling apply_transition() out of EXCEPTION from that explicit recovery
# command, never automatically.
ALLOWED_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.OPEN: {OrderState.IN_PROGRESS, OrderState.CANCELLED, OrderState.EXCEPTION},
    OrderState.IN_PROGRESS: {
        OrderState.QC_PENDING,
        OrderState.OPEN,
        OrderState.CANCELLED,
        OrderState.EXCEPTION,
    },
    OrderState.QC_PENDING: {
        OrderState.DONE,
        OrderState.REVISION,
        OrderState.CANCELLED,
        OrderState.EXCEPTION,
    },
    OrderState.REVISION: {
        OrderState.IN_PROGRESS,
        OrderState.QC_PENDING,
        OrderState.CANCELLED,
        OrderState.EXCEPTION,
    },
    OrderState.DONE: {OrderState.EXCEPTION},
    OrderState.CANCELLED: {OrderState.EXCEPTION},
    OrderState.EXCEPTION: set(OrderState),
}


def validate_transition(current: OrderState, target: OrderState) -> None:
    if current == target:
        return
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransitionError(current, target)

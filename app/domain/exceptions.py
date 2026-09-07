import uuid

from app.domain.models import OrderState


class InvalidTransitionError(Exception):
    def __init__(self, current: OrderState, target: OrderState):
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current} to {target}")


class CapacityExceededError(Exception):
    def __init__(self, designer_id: uuid.UUID, capacity: int, held: int, requested: int):
        self.designer_id = designer_id
        self.capacity = capacity
        self.held = held
        self.requested = requested
        super().__init__(
            f"Designer {designer_id} capacity {capacity}, already holding {held}, "
            f"cannot take {requested} more"
        )

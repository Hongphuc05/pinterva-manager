from app.domain.models import OrderState


class InvalidTransitionError(Exception):
    def __init__(self, current: OrderState, target: OrderState):
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current} to {target}")

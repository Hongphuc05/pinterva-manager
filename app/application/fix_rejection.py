"""Admin rejects Printerval's Fix: the order goes back to Review, here and on Printerval.

The one path for the web button and the Telegram callback, so both leave the order in the same
state (Designer note cleared, note_outsource hidden from the Designer) and push it the same way.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.adapters.db.models import Order, User, WorkflowEvent
from app.domain.models import OrderState

logger = logging.getLogger(__name__)


def reject_fix_to_review(
    session: Session,
    order: Order,
    *,
    admin: User,
    note_outsource: str | None = None,
    source: str = "web",
) -> None:
    """Mark the Fix rejected and the order back in Review (caller commits, then calls
    ``queue_review_push``)."""
    if note_outsource is not None:
        order.previous_note_outsource = order.note_outsource
        order.note_outsource = note_outsource.strip()
    old_state = order.state
    # Printerval's Fix is rejected, so the card waits for QC review locally too.
    order.state = OrderState.QC_PENDING.value
    order.fix_approved_by_admin = False
    order.fix_rejected_by_admin = True
    # Nothing of this Fix may reach the Designer.
    order.designer_note = ""
    order.designer_note_released_for_fix = False
    order.suppress_note_outsource_for_designer = True
    order.status_changed_at = datetime.now(UTC)

    admin_name = admin.full_name or admin.username
    via = " qua Telegram" if source == "telegram_callback" else ""
    session.add(
        WorkflowEvent(
            order_id=order.id,
            from_state=old_state,
            to_state=OrderState.QC_PENDING.value,
            actor_id=admin.id,
            evidence={
                "action": "REJECT_FIX_TO_REVIEW",
                "actor_name": admin_name,
                "actor_role": admin.role,
                "source": source,
                "description": f"Admin {admin_name} từ chối Fix{via} và gửi lại Review trên Printerval",
                "note_outsource": order.note_outsource,
            },
        )
    )


def queue_review_push(order: Order) -> None:
    """Push the order back to Review on Printerval, only if it is still the rejected Fix."""
    try:
        from app.workers.assignment_sync_tasks import sync_order_review_to_printerval_task

        sync_order_review_to_printerval_task.delay(
            str(order.id),
            order.note_outsource,
            "Review",
            expected_state=OrderState.QC_PENDING.value,
            expected_fix_approved=False,
        )
    except Exception:
        logger.warning("Could not queue the Review push for order %s", order.id, exc_info=True)

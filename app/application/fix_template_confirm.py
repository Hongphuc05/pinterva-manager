"""Admin's answer when Printerval asks to confirm a Fix raised for "Đổi template".

Printerval refuses to move such an order out of Fix until the outsource team says whether the Fix
really was about the template ("agree") or not ("disagree", with a reason), as its own page asks.
That is a person's decision: the Review push records the request (``pending_template_confirm``), the
Admin answers here, and the push is sent again carrying the answer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.adapters.db.models import User, WorkflowEvent
from app.application.concurrency import lock_order_for_command
from app.application.operations import run_idempotent
from app.application.printerval_alerts import pending_template_confirm
from app.domain.models import OrderState

DECISIONS = ("agree", "disagree")
NOTE_MAX = 500


class TemplateConfirmError(ValueError):
    pass


def confirm_fix_template(
    session: Session,
    *,
    order_id: uuid.UUID,
    platform_id: uuid.UUID,
    admin: User,
    decision: str,
    note: str | None,
    request_id: str,
) -> dict:
    """Record the answer and return what the Review push needs (the caller queues it)."""
    note = (note or "").strip()[:NOTE_MAX]
    if decision not in DECISIONS:
        raise TemplateConfirmError("Chọn xác nhận hoặc không đúng")
    if decision == "disagree" and not note:
        raise TemplateConfirmError("Ghi giải thích vì sao không phải đổi template")

    def _do() -> dict:
        order = lock_order_for_command(session, order_id=order_id, platform_id=platform_id)
        if order is None:
            raise LookupError("Không tìm thấy đơn hàng")
        alert = pending_template_confirm(session, order)
        if alert is None:
            raise TemplateConfirmError("Đơn này không chờ xác nhận đổi template")
        if order.state not in (OrderState.QC_PENDING.value, OrderState.REVISION.value):
            raise TemplateConfirmError("Đơn không còn ở Review/Fix")

        old_state = order.state
        # Sending it to Review again: the push gets a fresh window before a "fix" counts as a new Fix.
        order.state = OrderState.QC_PENDING.value
        order.status_changed_at = datetime.now(UTC)
        if old_state == OrderState.REVISION.value:
            order.fix_approved_by_admin = False
        who = admin.full_name or admin.username
        session.add(
            WorkflowEvent(
                order_id=order.id,
                from_state=old_state,
                to_state=OrderState.QC_PENDING.value,
                actor_id=admin.id,
                evidence={
                    "action": "CONFIRM_FIX_TEMPLATE",
                    "actor_name": who,
                    "actor_role": admin.role,
                    "decision": decision,
                    "note": note,
                    "description": (
                        f"Admin {who} xác nhận Fix do đổi template và gửi lại Review trên Printerval"
                        if decision == "agree"
                        else f"Admin {who} báo Fix không phải do đổi template ({note}) và gửi lại Review trên Printerval"
                    ),
                },
            )
        )
        session.flush()
        template_confirm = {"template_confirm": decision}
        if decision == "disagree":
            template_confirm["template_confirm_note"] = note
        return {
            "order_id": str(order.id),
            "order_code": order.external_order_id,
            "alert_id": str(alert.id),
            "target_status": (alert.payload or {}).get("target_status") or "Review",
            "template_confirm": template_confirm,
        }

    return run_idempotent(
        session,
        f"fix-template-confirm:{order_id}:{request_id}",
        "confirm_fix_template",
        _do,
        request_fingerprint=f"{decision}:{note}",
    )

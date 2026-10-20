"""Admin's answer when Printerval asks to confirm a Fix raised for "Đổi template".

Printerval refuses to move such an order out of Fix until the outsource team says whether the Fix
really was about the template ("agree") or not ("disagree", with a reason), as its own page asks.
That is a person's decision, asked of the Admin in two ways:

* up front (normal path): the Fix row carries ``outsource_fix_template`` with status "pending"; it is
  stored on the order (``Order.fix_template_confirm``) and the Admin answers while accepting the Fix
  (web dialog or Telegram). The Designer's Review push then carries the answer and goes through at once;
* afterwards (safety net): if Printerval still refuses the push, the refusal is recorded as an alert
  (``pending_template_confirm``), the Admin answers here and the push is sent again.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.adapters.db.models import Order, Platform, User, WorkflowEvent
from app.application.concurrency import lock_order_for_command
from app.application.operations import run_idempotent
from app.application.printerval_alerts import pending_template_confirm
from app.application.printerval_chat import ClientFactory
from app.config import get_settings
from app.domain.models import OrderState

logger = logging.getLogger(__name__)

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


# ----------------------------------------------------------------------------- up-front question

_CHECK_CACHE_SECONDS = 300
_checked_at: dict[uuid.UUID, float] = {}


def open_request(order: Order) -> dict | None:
    """The stored question that has not been sent to Printerval yet (with the answer, once given)."""
    stored = order.fix_template_confirm
    return stored if stored and not stored.get("sent_at") else None


def refresh_fix_template(
    session: Session,
    order: Order,
    *,
    client_factory: ClientFactory | None = None,
    force: bool = False,
) -> dict | None:
    """Store Printerval's pending template question for the order's Fix, or clear it when there is none.

    Reads the order's row (``outsource_fix_template``), at most once per 5 minutes per order unless
    ``force``. Never raises: when Printerval cannot be read the stored value stands. The caller commits.
    """
    if client_factory is None:
        if not get_settings().order_chat_enabled:
            return open_request(order)
        from app.application.printerval_chat import printerval_client_for as client_factory
    now = time.monotonic()
    if not force and now - _checked_at.get(order.id, -_CHECK_CACHE_SECONDS) < _CHECK_CACHE_SECONDS:
        return open_request(order)
    platform = session.get(Platform, order.platform_id) if order.platform_id else None
    if platform is None:
        return open_request(order)
    try:
        with client_factory(platform) as client:
            client.login()
            row = client.find_order(order.external_order_id, ("fix",))
    except Exception:
        logger.warning("Template question of %s unreadable", order.external_order_id, exc_info=True)
        return open_request(order)
    _checked_at[order.id] = now
    if row is None:
        return open_request(order)

    asked = row.get("outsource_fix_template")
    current = open_request(order)
    if isinstance(asked, dict) and asked.get("status") == "pending":
        if current and current.get("round") == asked.get("round"):
            return current
        order.fix_template_confirm = {
            "round": asked.get("round"),
            "url": asked.get("url"),
            "note": asked.get("note"),
            "requested_at": datetime.now(UTC).isoformat(),
            "decision": None,
        }
        return order.fix_template_confirm
    if current:
        order.fix_template_confirm = None
    return None


def record_template_answer(
    session: Session, order: Order, admin: User, decision: str, note: str | None, *, source: str
) -> dict:
    """Store the Admin's answer to the open question (sent with the Review push). The caller commits."""
    note = (note or "").strip()[:NOTE_MAX]
    if decision not in DECISIONS:
        raise TemplateConfirmError("Chọn xác nhận hoặc không đúng")
    if decision == "disagree" and not note:
        raise TemplateConfirmError("Ghi giải thích vì sao không phải đổi template")
    request = open_request(order)
    if request is None:
        raise TemplateConfirmError("Đơn này không chờ xác nhận đổi template")
    who = admin.full_name or admin.username
    order.fix_template_confirm = {
        **request,
        "decision": decision,
        "decision_note": note if decision == "disagree" else None,
        "decided_by": who,
        "decided_at": datetime.now(UTC).isoformat(),
    }
    session.add(
        WorkflowEvent(
            order_id=order.id,
            from_state=order.state,
            to_state=order.state,
            actor_id=admin.id,
            evidence={
                "action": "ANSWER_FIX_TEMPLATE",
                "actor_name": who,
                "actor_role": admin.role,
                "source": source,
                "round": request.get("round"),
                "decision": decision,
                "note": note,
                "description": (
                    f"Admin {who} xác nhận Fix do đổi template"
                    if decision == "agree"
                    else f"Admin {who} báo Fix không phải do đổi template ({note})"
                ),
            },
        )
    )
    return order.fix_template_confirm


def stored_template_answer(order: Order, row: dict | None) -> dict | None:
    """The extra fields for the Review push when the Admin already answered this Fix's question.

    ``row`` is the order's current Printerval row: the answer is used only for the question Printerval
    is asking now (same round), never for an older one. Without a row it is sent as stored.
    """
    request = open_request(order)
    if not request or request.get("decision") not in DECISIONS:
        return None
    if row is not None:
        asked = row.get("outsource_fix_template")
        if not (isinstance(asked, dict) and asked.get("status") == "pending" and asked.get("round") == request.get("round")):
            return None
    answer = {"template_confirm": request["decision"]}
    if request["decision"] == "disagree":
        answer["template_confirm_note"] = request.get("decision_note") or ""
    return answer


def mark_template_sent(order: Order) -> None:
    """The answer reached Printerval with the Review push: the question is closed."""
    request = open_request(order)
    if request:
        order.fix_template_confirm = {**request, "sent_at": datetime.now(UTC).isoformat()}

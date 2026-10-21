""""Báo fix không đúng": the Admin disputes Printerval's Fix instead of passing it to the Designer.

Printerval (since 21/10/2026, read from its own page) takes ``POST design-job/fix-dispute`` with a
reason (10-1000 characters) and up to 5 image links, moves the job to Review at once, and another
reviewer arbitrates: the dispute is ``pending``, then ``rejected`` (the job goes back to Fix, with the
arbiter's note) or accepted (the job stays in Review and that Fix does not count against the team).

``orders.fix_dispute`` keeps the Admin's dispute and Printerval's answer::

    round            fix_return_count when it was filed (one dispute per Fix round)
    note, images     what was sent
    submitted_by_id, submitted_by_name, submitted_at, source (web | telegram | printerval)
    push             queued | sent | failed   (our write to Printerval)
    push_error, sent_at
    remote_status    Printerval's dispute status (pending | rejected | ...)
    remote_can       whether Printerval lets the job be disputed now
    arbiter_note, arbiter_at
    outcome          None | accepted | rejected  (handled once)

The Designer never sees any of it.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.adapters.db.models import Order, User, WorkflowEvent
from app.domain.models import OrderState

logger = logging.getLogger(__name__)

NOTE_MIN = 10
NOTE_MAX = 1000
IMAGES_MAX = 5
_URL = re.compile(r"^https?://\S+$", re.IGNORECASE)

PENDING = "pending"
REJECTED = "rejected"
ACCEPTED = "accepted"


class FixDisputeError(Exception):
    """The dispute cannot be filed (invalid input, or the order may not be disputed)."""


def clean_input(note: str, images: list[str] | None) -> tuple[str, list[str]]:
    """Printerval's own checks: reason 10-1000 characters, at most 5 http(s) links."""
    note = (note or "").strip()
    links = [line.strip() for line in images or [] if line and line.strip()]
    if len(note) < NOTE_MIN:
        raise FixDisputeError(f"Ghi rõ vì sao FIX không đúng (ít nhất {NOTE_MIN} ký tự).")
    if len(note) > NOTE_MAX:
        raise FixDisputeError(f"Lý do tối đa {NOTE_MAX} ký tự.")
    if len(links) > IMAGES_MAX:
        raise FixDisputeError(f"Tối đa {IMAGES_MAX} link ảnh.")
    bad = next((link for link in links if not _URL.match(link)), None)
    if bad:
        raise FixDisputeError(f"Link ảnh phải bắt đầu bằng http:// hoặc https:// ({bad[:80]}).")
    return note, links


_REASON_HEAD = re.compile(r"^\s*l[ýy]\s*do\s*:\s*", re.IGNORECASE)
_IMAGES_HEAD = re.compile(r"^\s*[ảa]nh\s*:\s*", re.IGNORECASE)


def parse_reply(text: str) -> tuple[str, list[str]]:
    """The Telegram reply (template ``LÝ DO: ...`` then ``ẢNH:`` and one link per line).

    Every line that is only a link is an image; everything else is the reason, so a reply that skips
    the headings still works."""
    reason: list[str] = []
    links: list[str] = []
    for raw in (text or "").splitlines():
        line = _IMAGES_HEAD.sub("", _REASON_HEAD.sub("", raw)).strip()
        if not line:
            continue
        if line.lower().startswith(("http://", "https://")) and " " not in line:
            links.append(line)
        else:
            reason.append(line)
    return clean_input("\n".join(reason), links)


def current(order: Order) -> dict[str, Any] | None:
    """The dispute of the order's current Fix round, if any."""
    record = order.fix_dispute
    if record and record.get("round") == order.fix_return_count:
        return record
    return None


def blocked_reason(order: Order) -> str | None:
    """Why the current Fix cannot be disputed now (None = it can)."""
    if (order.state or "").upper() != OrderState.REVISION.value:
        return "Đơn không còn ở Fix."
    if order.fix_approved_by_admin:
        return "Fix đã được duyệt cho Designer."
    record = current(order)
    if record:
        if record.get("outcome") == REJECTED or record.get("remote_status") == REJECTED:
            return "Khiếu nại lượt Fix này đã bị bác."
        if record.get("push") in ("queued", "sent"):
            return "Đã gửi khiếu nại lượt Fix này."
        if record.get("remote_can") is False:
            return "Printerval không cho khiếu nại lượt Fix này."
    return None


def _event(session: Session, order: Order, from_state: str, action: str, actor_id, **evidence) -> None:
    session.add(
        WorkflowEvent(
            order_id=order.id,
            from_state=from_state,
            to_state=order.state,
            actor_id=actor_id,
            evidence={"action": action, "source": "fix_dispute", **evidence},
        )
    )


def submit(session: Session, order: Order, *, admin: User, note: str, images: list[str], source: str) -> dict:
    """Record the Admin's dispute (caller commits, then calls ``queue_send``)."""
    reason = blocked_reason(order)
    if reason:
        raise FixDisputeError(reason)
    note, images = clean_input(note, images)
    admin_name = admin.full_name or admin.username
    order.fix_dispute = {
        "round": order.fix_return_count,
        "note": note,
        "images": images,
        "submitted_by_id": str(admin.id),
        "submitted_by_name": admin_name,
        "submitted_at": datetime.now(UTC).isoformat(),
        "source": source,
        "push": "queued",
        "push_error": None,
        "sent_at": None,
        "remote_status": None,
        "remote_can": None,
        "arbiter_note": None,
        "arbiter_at": None,
        "outcome": None,
    }
    order.fix_rejected_by_admin = True  # the Admin does not accept this Fix
    _event(
        session, order, order.state, "FIX_DISPUTE_SUBMITTED", admin.id,
        actor_name=admin_name, actor_role=admin.role, note=note, images=images, via=source,
        description=f"Admin {admin_name} báo Fix không đúng (khiếu nại gửi Printerval)",
    )
    return order.fix_dispute


def queue_send(order: Order) -> None:
    try:
        from app.workers.assignment_sync_tasks import send_fix_dispute_task

        send_fix_dispute_task.delay(str(order.id))
    except Exception:
        logger.warning("Could not queue the Fix dispute of order %s", order.id, exc_info=True)


def retry(session: Session, order: Order, *, admin: User) -> None:
    """Send a dispute whose push failed again, unchanged."""
    record = current(order)
    if not record or record.get("push") != "failed":
        raise FixDisputeError("Không có khiếu nại gửi lỗi để gửi lại.")
    if (order.state or "").upper() != OrderState.REVISION.value:
        raise FixDisputeError("Đơn không còn ở Fix.")
    order.fix_dispute = {**record, "push": "queued", "push_error": None}
    _event(session, order, order.state, "FIX_DISPUTE_RETRIED", admin.id,
           actor_name=admin.full_name or admin.username)


def mark_failed(session: Session, order: Order, error: str) -> None:
    record = order.fix_dispute or {}
    order.fix_dispute = {**record, "push": "failed", "push_error": error[:500]}
    _event(session, order, order.state, "FIX_DISPUTE_FAILED", None, error=error[:500])


def mark_sent(order: Order) -> None:
    record = order.fix_dispute or {}
    order.fix_dispute = {**record, "push": "sent", "push_error": None, "sent_at": datetime.now(UTC).isoformat()}


def _back_to_review(order: Order) -> None:
    order.state = OrderState.QC_PENDING.value
    order.fix_approved_by_admin = False
    order.fix_rejected_by_admin = True
    # Nothing of this Fix may reach the Designer.
    order.designer_note = ""
    order.designer_note_released_for_fix = False
    order.suppress_note_outsource_for_designer = True
    order.status_changed_at = datetime.now(UTC)


def _back_to_fix(order: Order) -> None:
    """The dispute was rejected: the same Fix round is open again (not a new Fix, not counted twice)."""
    order.state = OrderState.REVISION.value
    order.fix_approved_by_admin = False
    order.fix_rejected_by_admin = False
    order.fix_deadline_at = None
    order.designer_note = ""
    order.designer_note_released_for_fix = False
    order.suppress_note_outsource_for_designer = True
    order.status_changed_at = datetime.now(UTC)


def observe(
    session: Session,
    order: Order,
    *,
    status: str | None,
    dispute: dict | None,
    can: bool | None,
    actor_id=None,
) -> tuple[bool, bool]:
    """Apply what Printerval says about the job's dispute. Returns (changed, back_in_fix).

    Call before the generic Fix/Review rules: a dispute's Review is not a Designer submission, and a
    rejected dispute reopens the same Fix rather than raising a new one."""
    record = dict(order.fix_dispute or {})
    if not record and not dispute:
        return False, False
    status = (status or "").strip().lower()
    changed = False
    if dispute:
        if not record:  # filed on Printerval directly
            record = {"round": order.fix_return_count, "note": dispute.get("note"), "images": [],
                      "source": "printerval", "push": "sent", "outcome": None}
        mirror = {
            "remote_status": dispute.get("status") or None,
            "arbiter_note": dispute.get("arbiter_note") or None,
            "arbiter_at": dispute.get("arbiter_at") or None,
        }
        for key, value in mirror.items():
            if record.get(key) != value:
                record[key] = value
                changed = True
    if can is not None and record.get("remote_can") != can:
        record["remote_can"] = can
        changed = True

    remote = record.get("remote_status")
    back_in_fix = False
    old_state = order.state
    if remote == PENDING and status == "review" and old_state == OrderState.REVISION.value:
        _back_to_review(order)
        _event(session, order, old_state, "FIX_DISPUTE_TO_REVIEW", actor_id, actor_name="Printerval",
               description="Printerval nhận khiếu nại Fix: đơn sang Review chờ phân xử")
        changed = True
    elif remote == REJECTED and status == "fix" and record.get("outcome") != REJECTED:
        record["outcome"] = REJECTED
        if old_state != OrderState.REVISION.value:
            _back_to_fix(order)
        _event(session, order, old_state, "FIX_DISPUTE_REJECTED", actor_id, actor_name="Printerval",
               arbiter_note=record.get("arbiter_note"),
               description="Khiếu nại bị bác — FIX đúng, đơn quay lại Fix")
        changed = back_in_fix = True
    elif remote not in (None, PENDING, REJECTED) and status != "fix" and record.get("outcome") is None:
        record["outcome"] = ACCEPTED
        _event(session, order, old_state, "FIX_DISPUTE_ACCEPTED", actor_id, actor_name="Printerval",
               remote_status=remote, arbiter_note=record.get("arbiter_note"),
               description="Khiếu nại được chấp nhận — lần Fix này không tính")
        changed = True
    if changed:
        order.fix_dispute = record
    return changed, back_in_fix


def view(order: Order) -> dict | None:
    """What the Admin web shows: the current round's dispute and whether a new one may be filed."""
    record = current(order) or (order.fix_dispute if order.fix_dispute and order.fix_dispute.get("outcome") else None)
    return {
        "dispute": record,
        "blocked_reason": blocked_reason(order),
    }

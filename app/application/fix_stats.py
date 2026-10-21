"""How often each Designer's work comes back as a Fix (Admin's "Tiến Độ Team" tab).

Read-only, computed from the order history (``workflow_events``), never from ``fix_return_count``:
that counter was bumped without an event before 21/09 and cannot say who a Fix belongs to.

* A **submission** is a move to Review by the Designer (or by an Admin on the assigned Designer's behalf).
* A **Fix** is Printerval's ``REQUEST_FIX``; it belongs to whoever made the submission QC was answering.
* A Designer's orders in a period are those they first submitted in it (Vietnam days); their Fixes are
  counted whenever they came.
* Not counted against the Designer, but listed: a **fake Fix** (reported within 5 minutes of a Fix
  resubmission, before the 20/10 guard: the sync saw the old Fix before Printerval took the Review) and
  a Fix the **Admin rejected** (sent back to Review as not a real Fix).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, load_only

from app.adapters.db.models import Assignment, ExternalObservation, Order, User, WorkflowEvent
from app.application.printerval_chat import SOURCE as CHAT_SOURCE
from app.application.sanitization import encode_proxy_url
from app.domain.access import ROLE_ADMIN, ROLE_DESIGNER, ROLE_DESIGNER_TRELLO

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
# Every Fix has had its own history event since then; earlier periods are incomplete.
FIX_HISTORY_SINCE = date(2026, 9, 21)
REPEAT_WARNING = 3  # an order Fixed this many times is called out on the Designer's card
# ponytail: timing heuristic for fake Fixes recorded before the sync guard; the chat cannot tell
# them apart for older orders (no snapshots before 19/10).
FAKE_FIX_WINDOW = timedelta(minutes=5)
FAKE_FIX_GUARD_SINCE = datetime(2026, 10, 20, tzinfo=UTC)
REASON_LAG = timedelta(minutes=10)  # the sync records a Fix a few minutes after QC opens it

DESIGNER_ROLES = (ROLE_DESIGNER, ROLE_DESIGNER_TRELLO)
NOT_A_SUBMISSION = ("REJECT_FIX_TO_REVIEW", "CONFIRM_FIX_TEMPLATE")
FAKE = "fake"
ADMIN_REJECTED = "admin_rejected"


@dataclass
class Fix:
    at: datetime
    designer_id: uuid.UUID
    excluded: str | None = None
    reason: str | None = None


@dataclass
class OrderHistory:
    first_submitted: dict[uuid.UUID, datetime] = field(default_factory=dict)
    fixes: list[Fix] = field(default_factory=list)


def period(date_from: date | None, date_to: date | None) -> tuple[datetime | None, datetime | None]:
    """Whole Vietnam days, both included; either end may be open."""
    start = datetime.combine(date_from, time.min, tzinfo=VN_TZ) if date_from else None
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=VN_TZ) if date_to else None
    return start, end


def _histories(session: Session, platform_id: uuid.UUID) -> tuple[dict[uuid.UUID, Order], dict[uuid.UUID, OrderHistory]]:
    orders = {
        o.id: o
        for o in session.query(Order)
        .options(load_only(Order.id, Order.external_order_id, Order.product_name, Order.thumbnail_url))
        .filter(Order.platform_id == platform_id)
    }
    roles = {u.id: u.role for u in session.query(User).options(load_only(User.id, User.role))}
    assigned = {
        a.order_id: a.designer_id
        for a in session.query(Assignment)
        .options(load_only(Assignment.order_id, Assignment.designer_id))
        .join(Order, Order.id == Assignment.order_id)
        .filter(Order.platform_id == platform_id, Assignment.status != "cancelled")
    }
    events = (
        session.query(WorkflowEvent)
        .options(load_only(WorkflowEvent.order_id, WorkflowEvent.from_state, WorkflowEvent.to_state,
                           WorkflowEvent.actor_id, WorkflowEvent.evidence, WorkflowEvent.created_at))
        .join(Order, Order.id == WorkflowEvent.order_id)
        .filter(Order.platform_id == platform_id)
        .order_by(WorkflowEvent.order_id, WorkflowEvent.created_at)
    )
    histories: dict[uuid.UUID, OrderHistory] = defaultdict(OrderHistory)
    last_submission: dict[uuid.UUID, tuple[uuid.UUID, datetime]] = {}
    open_fix: dict[uuid.UUID, Fix] = {}
    for event in events:
        oid, evidence = event.order_id, event.evidence or {}
        action, history = evidence.get("action"), histories[event.order_id]
        submitted = (
            (event.to_state == "QC_PENDING" and event.from_state != "QC_PENDING" and action not in NOT_A_SUBMISSION)
            or evidence.get("source") == "designer_paid_fix_resubmit"
        )
        if submitted and event.actor_id:
            role = roles.get(event.actor_id)
            designer = event.actor_id if role in DESIGNER_ROLES else assigned.get(oid) if role == ROLE_ADMIN else None
            if designer:
                last_submission[oid] = (designer, event.created_at)
                history.first_submitted.setdefault(designer, event.created_at)
        if action == "REQUEST_FIX" and event.from_state != "REVISION" and event.to_state == "REVISION":
            if oid not in last_submission:
                continue  # before any recorded submission: nobody to credit it to
            designer, submitted_at = last_submission[oid]
            fake = (
                bool(history.fixes)
                and event.created_at < FAKE_FIX_GUARD_SINCE
                and event.created_at - submitted_at < FAKE_FIX_WINDOW
            )
            fix = Fix(at=event.created_at, designer_id=designer, excluded=FAKE if fake else None)
            history.fixes.append(fix)
            open_fix[oid] = fix
        elif event.from_state == "REVISION" and event.to_state != "REVISION" and oid in open_fix:
            fix = open_fix.pop(oid)
            if action == "REJECT_FIX_TO_REVIEW" and fix.excluded is None:
                fix.excluded = ADMIN_REJECTED
    return orders, histories


def _attach_reasons(session: Session, histories: dict[uuid.UUID, OrderHistory], order_ids: set[uuid.UUID]) -> None:
    """QC's reason label ("Lỗi làm khác mockup gốc"...) from the chat, where it was captured (since 19/10)."""
    opened: dict[uuid.UUID, list[tuple[datetime, str]]] = defaultdict(list)
    rows = session.query(ExternalObservation).filter(
        ExternalObservation.source == CHAT_SOURCE, ExternalObservation.order_id.in_(order_ids)
    )
    for row in rows:
        for message in (row.evidence or {}).get("messages") or []:
            if message.get("type") == "fix_open" and message.get("sent_at") and message.get("fix_reason_label"):
                opened[row.order_id].append((datetime.fromisoformat(message["sent_at"]), message["fix_reason_label"]))
    for order_id, labels in opened.items():
        labels.sort()
        for fix in histories[order_id].fixes:
            if fix.excluded == FAKE:
                continue  # an echo of the previous Fix: that Fix's reason is not its own
            fix.reason = next((label for at, label in reversed(labels) if at <= fix.at + REASON_LAG), None)


def _in_period(moment: datetime, start: datetime | None, end: datetime | None) -> bool:
    return (start is None or moment >= start) and (end is None or moment < end)


def designer_fix_stats(
    session: Session, platform_id: uuid.UUID, date_from: date | None = None, date_to: date | None = None
) -> list[dict]:
    """One row per Designer who submitted orders in the period."""
    start, end = period(date_from, date_to)
    _, histories = _histories(session, platform_id)
    rows: dict[uuid.UUID, dict] = {}
    for history in histories.values():
        for designer, first in history.first_submitted.items():
            if not _in_period(first, start, end):
                continue
            row = rows.setdefault(designer, {
                "designer_id": str(designer), "submitted_orders": 0, "fixed_orders": 0, "fix_count": 0,
                "max_fixes_per_order": 0, "repeat_orders": 0, "distribution": {"1": 0, "2": 0, "3+": 0},
                "excluded": {FAKE: 0, ADMIN_REJECTED: 0},
            })
            row["submitted_orders"] += 1
            mine = [f for f in history.fixes if f.designer_id == designer]
            for fix in mine:
                if fix.excluded:
                    row["excluded"][fix.excluded] += 1
            counted = sum(1 for f in mine if not f.excluded)
            if counted:
                row["fixed_orders"] += 1
                row["fix_count"] += counted
                row["max_fixes_per_order"] = max(row["max_fixes_per_order"], counted)
                row["distribution"]["3+" if counted >= 3 else str(counted)] += 1
                row["repeat_orders"] += counted >= REPEAT_WARNING
    for row in rows.values():
        row["fix_rate"] = round(100 * row["fixed_orders"] / row["submitted_orders"], 1)
    return sorted(rows.values(), key=lambda r: (-r["fix_rate"], -r["fix_count"]))


def designer_fixed_orders(
    session: Session,
    platform_id: uuid.UUID,
    designer_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """The Designer's orders of the period that came back as a Fix, worst first, each Fix listed."""
    start, end = period(date_from, date_to)
    orders, histories = _histories(session, platform_id)
    picked = {
        oid: history
        for oid, history in histories.items()
        if designer_id in history.first_submitted
        and _in_period(history.first_submitted[designer_id], start, end)
        and any(f.designer_id == designer_id for f in history.fixes)
    }
    _attach_reasons(session, histories, set(picked))
    out = []
    for oid, history in picked.items():
        order = orders[oid]
        fixes = [f for f in history.fixes if f.designer_id == designer_id]
        out.append({
            "order_id": str(oid),
            "external_order_id": order.external_order_id,
            "product_name": order.product_name,
            "thumbnail_url": encode_proxy_url(order.thumbnail_url),
            "first_submitted_at": history.first_submitted[designer_id],
            "fix_count": sum(1 for f in fixes if not f.excluded),
            "fixes": [{"at": f.at, "reason": f.reason, "excluded": f.excluded} for f in fixes],
        })
    return sorted(out, key=lambda o: (-o["fix_count"], o["external_order_id"]))

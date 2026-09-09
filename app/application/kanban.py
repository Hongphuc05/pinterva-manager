from __future__ import annotations

from app.adapters.db.models import Assignment, DeadLetter, Order, User, WorkflowEvent
from app.domain.models import OrderState

KANBAN_COLUMNS = (
    ("open", "Chờ phân công", {"OPEN", "DISCOVERED", "CLAIMED_IMPORTED", "OPEN_FOR_ALLOCATION", "ASSIGNMENT_PENDING_APPROVAL"}),
    ("in_progress", "Đang làm", {"IN_PROGRESS", "ASSIGNED", "REVISION"}),
    ("qc", "Chờ duyệt (QC)", {"QC_PENDING", "RESULT_SUBMITTED", "SUBMITTING_TO_SITE"}),
    ("complete", "Hoàn thành", {"DONE", "SKIPPED"}),
    ("cancelled", "Đã hủy", {"CANCELLED"}),
    ("attention", "Lỗi / Ngoại lệ", {"EXCEPTION", "REASSIGNMENT_REQUIRED"}),
)


def _event_detail(event: WorkflowEvent | None, fallback: str) -> str:
    """Return the operator-facing reason recorded when a workflow state changed."""
    if event is None or not isinstance(event.evidence, dict):
        return fallback
    for key in ("reason", "message", "error", "error_message", "detail"):
        value = event.evidence.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _dead_letter_detail(dead_letter: DeadLetter) -> str:
    """Turn a durable dead-letter record into an actionable, safe explanation."""
    parts = [
        f"Không thể hoàn tất bước {dead_letter.source}",
        f"Loại lỗi: {dead_letter.error_class}",
    ]
    payload = dead_letter.payload if isinstance(dead_letter.payload, dict) else {}
    stage = payload.get("stage")
    if isinstance(stage, str) and stage:
        parts.append(f"Công đoạn: {stage}")
    if dead_letter.recovery_action:
        parts.append(f"Cách xử lý: {dead_letter.recovery_action}")
    return ". ".join(parts) + "."


def _alert(kind: str, label: str, detail: str, occurred_at) -> dict:
    return {
        "kind": kind,
        "label": label,
        "detail": detail,
        "occurred_at": occurred_at.isoformat() if occurred_at else None,
    }


def list_kanban(session) -> list[dict]:
    orders = (
        session.query(Order)
        .order_by(Order.deadline_at_ext.nullslast(), Order.created_at.desc())
        .all()
    )
    active_assignments = (
        session.query(Assignment.order_id, User.full_name)
        .join(User, User.id == Assignment.designer_id)
        .filter(Assignment.status == "approved")
        .all()
    )
    designer_by_order = {order_id: name for order_id, name in active_assignments}
    dead_letters_by_order: dict[str, list[DeadLetter]] = {}
    for dead_letter in (
        session.query(DeadLetter)
        .filter(DeadLetter.resolved_at.is_(None))
        .order_by(DeadLetter.created_at.desc())
        .all()
    ):
        payload = dead_letter.payload if isinstance(dead_letter.payload, dict) else {}
        order_id = payload.get("order_id")
        if isinstance(order_id, str):
            dead_letters_by_order.setdefault(order_id, []).append(dead_letter)

    state_events_by_order: dict = {}
    for event in (
        session.query(WorkflowEvent)
        .filter(WorkflowEvent.to_state.in_(["REASSIGNMENT_REQUIRED", OrderState.EXCEPTION.value]))
        .order_by(WorkflowEvent.created_at.desc())
        .all()
    ):
        state_events_by_order.setdefault(event.order_id, event)
    columns = [{"id": key, "title": title, "cards": []} for key, title, _ in KANBAN_COLUMNS]
    by_state = {}
    for column, (_, _, states) in zip(columns, KANBAN_COLUMNS):
        for state in states:
            by_state[state] = column
    for order in orders:
        column = by_state.get(order.state)
        if column is None:
            continue
        alerts: list[dict] = []
        latest_dead_letter = next(iter(dead_letters_by_order.get(order.external_order_id, [])), None)
        if latest_dead_letter:
            alerts.append(
                _alert(
                    "processing_error",
                    "Có lỗi xử lý",
                    _dead_letter_detail(latest_dead_letter),
                    latest_dead_letter.created_at,
                )
            )
        if order.state == "REASSIGNMENT_REQUIRED":
            event = state_events_by_order.get(order.id)
            alerts.append(
                _alert(
                    "reassignment_required",
                    "Cần phân lại",
                    _event_detail(
                        event,
                        "Đơn đang ở trạng thái cần phân lại. Hệ thống không có lý do chi tiết "
                        "trong lịch sử của lần chuyển trạng thái này; hãy phân công lại Designer.",
                    ),
                    event.created_at if event else None,
                )
            )
        if order.state == OrderState.EXCEPTION.value:
            event = state_events_by_order.get(order.id)
            alerts.append(
                _alert(
                    "exception",
                    "Ngoại lệ",
                    _event_detail(event, "Đơn đang ở trạng thái ngoại lệ và cần được kiểm tra thủ công."),
                    event.created_at if event else None,
                )
            )
        column["cards"].append(
            {
                "id": str(order.id), "external_order_id": order.external_order_id,
                "state": order.state, "product_name": order.product_name,
                "thumbnail_url": order.thumbnail_url, "job_type": order.job_type,
                "designer_name": designer_by_order.get(order.id),
                "deadline_at_ext": (
                    order.deadline_at_ext.isoformat() if order.deadline_at_ext else None
                ),
                "alerts": alerts,
            }
        )
    return columns

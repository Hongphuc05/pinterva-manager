from __future__ import annotations

from app.adapters.db.models import Assignment, DeadLetter, Order, User
from app.domain.models import OrderState

KANBAN_COLUMNS = (
    ("open", "Chờ phân công", {"OPEN", "DISCOVERED", "CLAIMED_IMPORTED", "OPEN_FOR_ALLOCATION", "ASSIGNMENT_PENDING_APPROVAL"}),
    ("in_progress", "Đang làm", {"IN_PROGRESS", "ASSIGNED", "REVISION"}),
    ("qc", "Chờ duyệt (QC)", {"QC_PENDING", "RESULT_SUBMITTED", "SUBMITTING_TO_SITE"}),
    ("complete", "Hoàn thành", {"DONE", "SKIPPED"}),
    ("cancelled", "Đã hủy", {"CANCELLED"}),
    ("attention", "Lỗi / Ngoại lệ", {"EXCEPTION", "REASSIGNMENT_REQUIRED"}),
)


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
    dead_letter_order_ids = {
        payload["order_id"]
        for (payload,) in session.query(DeadLetter.payload).all()
        if isinstance(payload, dict) and isinstance(payload.get("order_id"), str)
    }
    columns = [{"id": key, "title": title, "cards": []} for key, title, _ in KANBAN_COLUMNS]
    by_state = {}
    for column, (_, _, states) in zip(columns, KANBAN_COLUMNS):
        for state in states:
            by_state[state] = column
    for order in orders:
        column = by_state.get(order.state)
        if column is None:
            continue
        alerts = []
        if order.external_order_id in dead_letter_order_ids:
            alerts.append("Có lỗi xử lý")
        if order.state == OrderState.REASSIGNMENT_REQUIRED.value:
            alerts.append("Cần phân lại")
        if order.state == OrderState.EXCEPTION.value:
            alerts.append("Exception")
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

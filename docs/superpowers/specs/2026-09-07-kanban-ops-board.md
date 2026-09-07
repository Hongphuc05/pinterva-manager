# Kanban ops board

## Ruling

The first Kanban is deliberately read-only. Dragging a card between columns would imply
a workflow transition, but each transition needs its own business command, evidence and
authorization. There is no safe generic “move card” command, so the board links to the
relevant task/order views instead of writing `Order.state` directly.

`GET /api/kanban` is admin-only and returns fixed operational groups covering every
`OrderState`. Cards contain the order context, current approved designer assignment,
deadline, and derived alert badges. A dead-letter badge is matched only from a
dead-letter payload's `order_id`; `REASSIGNMENT_REQUIRED` and `EXCEPTION` are state
alerts. The endpoint performs no writes or external calls.

## Groups

1. Mới: `DISCOVERED`, `CLAIMED_IMPORTED`, `OPEN_FOR_ALLOCATION`
2. Chờ duyệt gán: `ASSIGNMENT_PENDING_APPROVAL`
3. Đang thiết kế: `ASSIGNED`, `IN_PROGRESS`, `REVISION_REQUESTED`
4. Chờ QC: `RESULT_SUBMITTED`, `QC_PENDING`
5. Đang đưa lên site: `SUBMITTING_TO_SITE`
6. Hoàn tất: `DONE`, `SKIPPED`, `CANCELLED`
7. Cần xử lý: `REASSIGNMENT_REQUIRED`, `EXCEPTION`

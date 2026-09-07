# Allocation Board (C2 + C3) — Design

**Sub-project 3/6** của chuỗi "web trung gian thay Printerval". Xây dựng cơ chế phân bổ
đơn (C2 — designer tự offer + admin gán tay, thuật toán FIFO contiguous-block) và
duyệt phân đơn (C3 — admin Approve/Cancel) trên nền React đã có (sub-project 2), cộng
UI kéo-thả (Allocation Board) theo yêu cầu gốc của người dùng.

**Phân loại brainstorming: architectural** (business logic mới hoàn toàn, chưa có
application layer nào cho C2/C3 dù state machine đã sẵn từ Phase 1) — controller tự
quyết định, không dừng hỏi user (chỉ đạo "chạy liên tục").

## 1. Điểm khởi đầu đã có sẵn (không cần tạo mới)

- Data model: `batches`, `assignments` (có `replacement_of_id`, `cancel_reason`,
  `sub_status`), `approval_requests`, `approval_decisions`, `users.capacity` — **đã đủ
  cột từ Phase 1**, không cần migration mới cho sub-project này.
- State machine: `OPEN_FOR_ALLOCATION → ASSIGNMENT_PENDING_APPROVAL → ASSIGNED` và
  `ASSIGNMENT_PENDING_APPROVAL → OPEN_FOR_ALLOCATION` (cancel) đã có trong
  `app/domain/state_machine.py` — không sửa.
- Order data: sub-project 1 đã lưu đủ product info (tên, ảnh, SKU, mẫu) vào `Order` lúc
  import → **C3 không cần gọi lại Playwright để "truy xuất Printerval"** như mô tả gốc
  trong claude.md §3 C3 — chỉ đọc thẳng cột `Order` đã có. Đây là điểm khác cố ý so với
  bản claude.md gốc, dựa trên việc sub-project 1 đã giải quyết trước.

## 2. Application layer mới cần xây (chưa tồn tại file nào)

### 2.1 Allocation tool interface (thuật toán FIFO — bản tham chiếu, không phải production)

```
app/adapters/allocation/interface.py   # Protocol
app/adapters/allocation/reference.py   # bản tham chiếu FIFO/contiguous-block
```

```python
class AllocationTool(Protocol):
    def select_block(self, remaining_order_ids: list[str], quantity: int) -> list[str]: ...
```

Bản tham chiếu: `remaining_order_ids[:quantity]` — đúng thuật toán đã chốt (khối liền
kề, không round-robin). Đặt sau interface để sau này cắm tool thật (đã chạy nơi khác)
mà không sửa domain — đúng claude.md §3 C2 ghi chú quan trọng.

### 2.2 `app/application/allocation.py`

```
open_allocation(session, batch_id, idempotency_key) -> {order_ids: [...]}
```
Chuyển toàn bộ order của batch đang ở `CLAIMED_IMPORTED` sang `OPEN_FOR_ALLOCATION`
(bulk, mỗi order 1 `apply_transition` trong cùng transaction). Batch.lifecycle_state
`"open"` → `"allocating"`.

```
request_quantity(session, allocation_tool, designer_id, batch_id, quantity, idempotency_key)
    -> {granted_order_ids: [...], assignment_ids: [...]}
```
**Cơ chế tuần tự hoá đúng theo claude.md §3 C2:** đây KHÔNG phải "đăng ký rồi chờ xử
lý theo lô" — mỗi lệnh gọi tự nó là 1 giao dịch DB nguyên tử: `SELECT ... FOR UPDATE`
trên các `Order` của batch đang `OPEN_FOR_ALLOCATION` và chưa có `Assignment` nào
(`NOT EXISTS` subquery, không dùng cột trạng thái riêng vì 1 order có Assignment nghĩa
là đã bị giữ), sắp theo `external_order_id` (thứ tự ổn định) → gọi
`allocation_tool.select_block(...)` lấy tối đa `quantity` order đầu tiên còn trống →
với mỗi order: tạo `Assignment(order_id, designer_id, status="draft")`, transition order
sang `ASSIGNMENT_PENDING_APPROVAL`, tạo 1 `ApprovalRequest(kind="assignment",
target_id=assignment.id)` riêng cho từng order (không gộp — xem lý do ở §2.3). Nếu số
order còn lại < `quantity`, chỉ giao đúng số còn lại (không lỗi, không round-robin lấy
bù từ designer khác).

**Giới hạn theo `capacity` (tận dụng cột có sẵn, chưa ai dùng):** nếu
`designer.capacity is not None`, tính "đang giữ" = số `Assignment` của designer có
`status in ("draft", "approved")` (chưa cancel), từ chối (lỗi `VALIDATION`, không tạo
gì) nếu `quantity` vượt quá `capacity - đang_giữ`. Không giới hạn nếu `capacity is
None` (designer chưa cấu hình capacity).

```
create_assignment_draft(session, order_id, designer_id, idempotency_key) -> Assignment
```
Đường "admin gán tay" — 1 order, không qua thuật toán block. Cùng validate capacity
như trên. Cùng tạo `ApprovalRequest` như `request_quantity`.

```
decide_assignment(session, allocation_tool, approval_id, decision, actor_id, idempotency_key)
    -> AssignmentResult
```
`decision` ∈ `{"approve", "cancel"}`.
- **Approve:** order `ASSIGNMENT_PENDING_APPROVAL → ASSIGNED`; `Assignment.status =
  "approved"`; `ApprovalRequest.status = "approved"`; ghi `ApprovalDecision`.
- **Cancel:** bắt buộc có `reason` (tham số mới, lưu vào `Assignment.cancel_reason`).
  **Sửa lại so với thiết kế đầu (phát hiện lúc implement Task 3, xem ghi chú dưới):**
  order `ASSIGNMENT_PENDING_APPROVAL → EXCEPTION` (KHÔNG quay lại
  `OPEN_FOR_ALLOCATION`) — state machine đã cho phép transition này sẵn
  (`app/domain/state_machine.py`). `Assignment.status = "cancelled"`;
  `ApprovalRequest.status = "cancelled"`; ghi `ApprovalDecision` với `comment =
  reason`. **Trả quota (đúng claude.md §3 C3):** ngay sau đó, gọi lại đúng logic
  `request_quantity` cho **cùng designer, quantity=1**, lấy từ phần **còn lại của
  batch** (không bao giờ là chính đơn vừa cancel — đơn đó giờ ở `EXCEPTION`, không
  còn nằm trong `OPEN_FOR_ALLOCATION` nên tự động bị loại khỏi pool, không cần lọc
  thêm) — assignment bù có `replacement_of_id` trỏ về assignment vừa bị cancel. Nếu
  batch hết order để bù, không lỗi — designer đơn giản nhận ít hơn.

  **Vì sao không quay lại `OPEN_FOR_ALLOCATION`:** Cancel nghĩa là "đơn đã làm/không
  hợp lệ" (claude.md §3 C3) — tiêu chí xác định cụ thể **chưa có** (tech debt #1,
  claude.md §17). Cho đơn quay lại pool chung ngay lập tức nghĩa là FIFO có thể cấp
  lại **chính đơn đó cho chính designer vừa bị hủy** (nếu đó là đơn sớm nhất còn
  lại) — vô hiệu hoá hoàn toàn ý nghĩa của Cancel, và tệ hơn là có thể cấp 1 đơn
  "đã làm/không hợp lệ" cho một designer khác làm tiếp. Đưa vào `EXCEPTION` khớp
  đúng bất biến #10 ("Khi không chắc chắn, đưa vào exception queue thay vì đoán
  cách recover") — admin xử lý thủ công đơn đó sau (recovery UI là claude.md §15
  bước 10, **ngoài phạm vi sub-project này**, đơn ở EXCEPTION không tự thoát ra
  được cho tới khi có UI đó — chấp nhận được cho V1, ghi vào tech debt).
- **Idempotency đa-admin (claude.md §10, "quyết định đầu tiên hợp lệ là quyết định cuối
  cùng"):** trước khi quyết định, kiểm tra `ApprovalRequest.status`; nếu đã khác
  `"pending"`, raise `ApprovalAlreadyDecidedError` kèm decision đầu tiên (actor + thời
  gian, join `ApprovalDecision`) để API trả thông báo "đã được [tên] xử lý lúc [time]"
  — không silent-ignore.

### 2.3 Vì sao 1 `ApprovalRequest`/order thay vì 1 cho cả khối

claude.md §3 C3 nói "Với từng assignment draft" (số ít) admin Approve/Cancel — và Cancel
release đúng 1 order rồi bù, không huỷ cả khối của designer đó. Gộp chung sẽ buộc
Approve/Cancel toàn khối cùng lúc, sai với hành vi "Cancel nghĩa là đơn đã làm/không hợp
lệ" (chỉ áp dụng cho 1 đơn cụ thể).

## 3. JSON API mới (`app/api/routes/allocation_api.py`)

```
POST /api/batches/{batch_id}/open-allocation          (admin) -> {order_ids}
POST /api/allocation/offer      {batch_id, quantity}   (designer, dùng chính user.id)
POST /api/allocation/assign     {order_id, designer_id} (admin — gán tay)
GET  /api/allocation/board?batch_id=                   -> board state (xem §4)
POST /api/approvals/{approval_id}/decide {decision, reason?} (admin)
```

`GET /api/allocation/board` trả dữ liệu cho UI kéo-thả:
```json
{
  "unassigned": [{order fields tối thiểu: id, external_order_id, thumbnail_url, sku, deadline_at_ext}],
  "designers": [
    {"id", "full_name", "capacity", "held": <int>, "pending_approvals": [{approval_id, order}]}
  ]
}
```
`"held"` = số Assignment draft+approved hiện tại (dùng để hiện "Nam: 5/10").
`pending_approvals` chỉ hiện cho admin (card chờ Approve/Cancel).

## 4. UI — Allocation Board (kéo-thả)

Layout matrix: cột trái "Kho đơn chưa gán" (`unassigned`), mỗi designer 1 cột kèm
`capacity`/`held` (badge "Full" khi `held >= capacity`). Dùng **`dnd-kit`**
(`@dnd-kit/core` + `@dnd-kit/sortable`) — chuẩn React, không dùng SortableJS (đó là lựa
chọn cũ cho Jinja2, đã bỏ từ sub-project 2).

- Kéo 1 đơn từ "Kho" thả vào cột designer → gọi `POST /api/allocation/assign` (đường
  admin gán tay, không qua thuật toán block vì đây là chọn thủ công 1 đơn cụ thể).
- Card đơn hiện thumbnail/SKU/deadline (đã có field từ sub-project 1).
- Mỗi cột designer có ô nhập số lượng + nút "Nhận" cho **chính designer đó tự offer**
  (không kéo-thả — offer là hành động của designer trên cột của chính mình, không phải
  admin kéo hộ) → gọi `POST /api/allocation/offer`.
- Card chờ duyệt (từ `pending_approvals`) hiện riêng, admin bấm Approve/Cancel (Cancel
  bắt buộc nhập lý do) → gọi `POST /api/approvals/{id}/decide`.
- Sau mọi action, refetch `GET /api/allocation/board` (không cần optimistic update phức
  tạp cho V1 — YAGNI, board không cần realtime multi-admin ngay).

## 5. Non-goal

- Không tích hợp tool FIFO thật (chạy nơi khác) — chỉ interface + bản tham chiếu.
- Không làm Kanban ops board (theo dõi tiến độ toàn bộ state) — sub-project 5.
- Không có real-time sync giữa nhiều admin đang mở board cùng lúc (refetch thủ công sau
  action là đủ cho V1 — nhiều admin cùng bấm Approve cùng lúc vẫn đúng nhờ DB check ở
  §2.2, chỉ là UI không tự cập nhật cho admin còn lại).
- Không đổi state machine/policy table đã có.

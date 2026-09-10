# Thiết kế: domain Đơn trùng lặp và Kanban cho Designer Trello

## Mục tiêu

Khôi phục một giao diện Kanban theo cách làm việc của Trello cho nhóm xử lý đơn
trùng lặp, nhưng không khôi phục Kanban vận hành cũ theo trạng thái workflow.

Admin có thể đưa đơn vào domain **Đơn trùng lặp**. Những đơn này xuất hiện trên
một board chung cho mọi người dùng có role `designer-trello`. Board có cột đầu
tiên **Thiếu form** và một cột cho từng `designer-trello` đang hoạt động của
platform. Kéo thả thẻ thay đổi người đang nhận đơn một cách có kiểm soát và có
audit trail.

## Phạm vi và bất biến

1. Thêm role `designer-trello`; role cũ `admin` và `designer` không đổi quyền.
2. Mỗi `Order` có `work_domain`:
   - `standard` (mặc định): luồng hiện tại.
   - `duplicate`: chỉ xuất hiện trên Trello board.
3. Đơn duplicate chỉ có tối đa một `Assignment` active (`approved`) tại một thời
   điểm. `Thiếu form` là đơn duplicate chưa có active assignment tới một
   `designer-trello` active trong platform.
4. Chuyển đơn sang duplicate domain huỷ assignment active cũ và ghi workflow
   event. Điều này ngăn một đơn đồng thời nằm ở luồng Designer thường và board
   duplicate.
5. Kéo thả không đẩy Designer hay trạng thái lên Printerval. Nó chỉ thay đổi
   ownership nội bộ; trạng thái workflow nội bộ không bị đổi bởi thao tác kéo.
6. Admin có thể kéo mọi thẻ giữa mọi cột. `designer-trello` chỉ được nhận thẻ
   vào cột của chính mình hoặc trả thẻ mình đang nhận về `Thiếu form`; không thể
   tự phân đơn cho người khác.
7. Mọi thao tác ghi đều khoá row `Order`, kiểm tra optimistic version qua ORM,
   và tạo `WorkflowEvent` có evidence. Không dùng endpoint generic để set state.

## API

### `GET /api/duplicate-board`

Quyền: `admin` hoặc `designer-trello`.

Scope theo active platform. Trả về:

```json
{
  "columns": [
    {"id": "unassigned", "title": "Thiếu form", "cards": []},
    {"id": "<user uuid>", "title": "Tên designer-trello", "cards": []}
  ]
}
```

Thẻ gồm order ID, code, tên sản phẩm, ảnh, deadline, state và assignee hiện tại.
Không trả đơn `standard`.

### `POST /api/duplicate-board/move`

Quyền: `admin` hoặc `designer-trello`.

Payload `{ "order_id": UUID, "target_designer_id": UUID | null }`.

- `null` nghĩa là `Thiếu form`.
- Target phải là `designer-trello` active, cùng platform (hoặc không gán
  platform như dữ liệu legacy).
- API trả card đã cập nhật. UI reload board sau khi thành công để loại stale
  state giữa nhiều trình duyệt.

### `POST /api/orders/duplicate-domain`

Quyền: admin. Payload `{ "order_ids": [UUID], "work_domain": "duplicate" |
"standard" }`. Admin dùng nó từ thanh bulk action của Danh sách đơn hàng.

- `duplicate`: cancel assignment active, set domain và tạo workflow event.
- `standard`: đưa đơn về luồng thường; không tạo assignment thay thế.

## UX

### Admin

Trong Danh sách đơn hàng, khi chọn đơn, có nút **Đưa vào Đơn trùng lặp**. Sau
khi thành công, toast nêu số đơn và board sẽ có các đơn này ở `Thiếu form`.
Admin có entry **Board Đơn trùng lặp** ở sidebar.

### Designer Trello

Sau đăng nhập, sidebar chỉ có **Board Đơn trùng lặp** và lịch sử. `/kanban` là
board của role này. Card có thumbnail, mã đơn, tên sản phẩm, deadline và badge
trạng thái. Một click mở chi tiết đơn; drag handle/drag thẻ thực hiện kéo thả.

Board theo bố cục Trello: nền trung tính, cột cuộn ngang, header cột cố định,
counter, vùng drop rõ ràng, card trắng, feedback khi đang kéo, empty state. Cột
không tự tạo từ client: luôn phản chiếu danh sách tài khoản server trả về.

## Không thuộc phạm vi

- Không đồng bộ board sang Trello thật.
- Không thêm realtime/WebSocket trong phase này; board refresh sau thao tác và
  có nút tải lại. API là source of truth.
- Không thay đổi flow submit/QC/Printerval của Designer thường.
- Không thêm thứ tự card bền vững; thứ tự ban đầu deadline rồi created time.

## Rủi ro và kiểm thử

- Phân quyền kéo thả phải được backend kiểm tra, không dựa UI.
- Đơn có assignment legacy phải được cancel có audit khi vào domain duplicate.
- User disabled hoặc khác platform không được dùng làm cột/target.
- Test API cho role, scope platform, move policy, cancel assignment và event.
- Test React cho cột, card, empty state và gọi move đúng payload.

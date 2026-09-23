# Quyền truy cập và riêng tư dữ liệu

## Nguyên tắc

UI ẩn dữ liệu là chưa đủ. API response, history, attachment download và external link đều
phải enforce role + platform + assignment ở backend.

## Designer standard

- Chỉ xem order standard có assignment active của chính mình.
- Không thấy upstream `note_outsource`, `previous_note_outsource`, result history, audit
  history, external order URL, design tool URL, source download-all và thông tin platform nội bộ.
- Chỉ thấy `designer_note` khi Admin đã release cho Fix được duyệt hoặc flow xử lý thiếu
  template hợp lệ.
- Work-note attachment chỉ tải được nếu caller có quyền xem order/note.

## Designer Trello

- Chỉ ở duplicate domain của platform đang active.
- Có thể thấy card cộng tác và latest result link trong Duplicate Board của cùng platform.
- Ngoại lệ này không mở dữ liệu internal/upstream đã bị sanitize, và không áp dụng sang
  standard domain.

## Admin và Support

- Admin có toàn quyền theo platform; một số endpoint quản lý platform/user là admin-only.
- Support chỉ được kiểm tra/phân loại order còn ở hàng chờ `Waiting` (bao gồm các state
  legacy tương đương). Khi Admin đã chia order cho Designer hoặc order đã sang `Doing`,
  Support không còn thấy order ở danh sách/detail và backend cũng từ chối lệnh phân loại.
- Mỗi lần Support chốt kết quả phân loại, order lưu `support_classified_by_id` và
  `support_classified_at`. Finance của Admin dùng hai trường này để đếm công theo từng
  Support; Finance của Support chỉ trả số đơn do chính tài khoản đó phân loại, không trả
  danh sách/tổng tiền tài chính của cả platform.
- Support không có quyền đọc hoặc điều khiển Duplicate Board; board chỉ dành cho Admin và
  Designer Trello. Support cũng không tự nhiên kế thừa quyền sửa state, platform credential
  hay finance admin.

## Attachment ảnh Note làm việc

- Client gửi multipart để browser tự thiết lập boundary.
- Backend chỉ nhận raster image theo validation hiện hành; không dùng URL public cố định.
- Client tải blob bằng auth giống API data; không dùng `<img src>` trực tiếp với endpoint
  private nếu endpoint cần bearer/session.
- API base URL được normalize: cấu hình có hoặc không có `/api` đều phải ra đúng một
  prefix `/api`, tránh lỗi `/api/api/...` dẫn đến 404.
- Metadata attachment (tên file, MIME type, dung lượng và storage key) ở PostgreSQL; bytes
  ảnh nằm tại private asset directory. Không ghi URL public, token hay nội dung ảnh vào log.
- Attachment private phải được backup cùng database và chỉ được lưu trên persistent volume ở
  production; trạng thái mount hiện hành được ghi rõ tại [data-storage.md](data-storage.md).

## Telegram Bot management

- Chỉ `admin` được đọc overview kết nối của các designer, gắn/xóa group ID, xác thực group, đổi
  delivery mode, gửi test và sửa template. Mọi endpoint đều kiểm tra platform scope ở backend.
- `designer` và `designer-trello` chỉ tự link/unlink chat riêng qua flow `/start <link_code>`;
  không được tự chọn group hoặc xem cấu hình của designer khác. `support` không được dùng tab
  quản trị bot theo mặc định.
- UI chỉ hiển thị metadata cần cho vận hành (chat ID/group title/trạng thái); không trả bot token,
  callback token hay credential platform. Group phải được Bot API xác thực trước khi chọn mode.
- Dynamic values trong template được escape trước khi gửi Telegram. Nội dung test ad-hoc cũng được
  escape như text; Admin chỉ sửa body và placeholder được phép, không sửa logic callback/quyền.
- Nếu mode `group` chưa sẵn sàng, notification designer không fallback âm thầm sang chat riêng.
  Admin phải kiểm tra lỗi hoặc chuyển mode một cách rõ ràng; dữ liệu order vẫn chỉ đọc/ghi qua API.

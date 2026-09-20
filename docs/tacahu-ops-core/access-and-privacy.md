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
- Support có quyền workflow giới hạn: phân loại duplicate, đọc board, xem submissions;
  không tự nhiên kế thừa quyền sửa state, platform credential hay finance admin.

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

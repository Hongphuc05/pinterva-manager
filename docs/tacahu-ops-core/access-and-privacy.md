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
- Support trên web chỉ được kiểm tra/phân loại order còn ở hàng chờ `Waiting` (bao gồm các state
  legacy tương đương). Support vẫn xem được mọi order đang `Doing` trong tab `Đang làm`
  để theo dõi, nhưng tab này chỉ read-only. Order Doing chưa kiểm tra cũng xuất hiện trong tab
  **Chưa kiểm tra** để làm nguồn cho bộ so sánh, nhưng chỉ được quyết định qua nút Telegram
  của candidate hợp lệ. Sau khi đã chốt `duplicate` hoặc
  `non_duplicate`, order vẫn hiện trong tab phân loại tương ứng để Support đối soát, kể cả
  khi đã sang `Doing`, `Review` hoặc `Done`; backend vẫn từ chối lệnh phân loại ngoài
  `Waiting` từ web.
- Mỗi lần Support chốt kết quả phân loại, order lưu `support_classified_by_id` và
  `support_classified_at`. Finance của Admin dùng hai trường này để đếm công theo từng
  Support; Finance của Support chỉ trả số đơn do chính tài khoản đó phân loại, không trả
  danh sách/tổng tiền tài chính của cả platform.
- Support không có quyền đọc hoặc điều khiển Duplicate Board; board chỉ dành cho Admin và
  Designer Trello. Support cũng không tự nhiên kế thừa quyền sửa state, platform credential
  hay finance admin.
- Support có thể nhận candidate ảnh qua Telegram riêng nếu tài khoản đã link chat và bật
  notification. Candidate `review` chỉ phục vụ test embedding/compare; callback `review` bị
  chặn. Với source live `support_unchecked`, Telegram gửi album gồm ảnh mới và ảnh historical
  top-1, kèm mã/tên hai đơn và hai nút **Trùng**/**Không trùng**. Callback gọi cùng command
  backend như web, ghi actor/version/audit; riêng order Doing chưa kiểm tra được phép đi qua
  callback scoped này, không đặt quyền quyết định vào nội dung Telegram.
- Support có thể gửi `/check` trong chat riêng với bot để đếm các order **Chưa kiểm tra** của
  đúng platform mình được gắn. Bot chỉ tạo job sau khi Support bấm **Có, bắt đầu**; token nút
  có hạn dùng, khóa theo chat/platform và không mở quyền cho tài khoản khác. Bấm **Không** chỉ
  hủy yêu cầu, không đổi trạng thái order.

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

- Chỉ `admin` được đọc overview kết nối của các Designer và Support, gắn/xóa group ID cho
  Designer, xác thực group, đổi delivery mode, gửi test và sửa template. Mọi endpoint đều kiểm
  tra platform scope ở backend.
- `designer` và `designer-trello` chỉ tự link/unlink chat riêng qua flow `/start <link_code>`;
  không được tự chọn group hoặc xem cấu hình của designer khác. `support` không được dùng tab
  quản trị bot; Admin cấu hình recipient Support trong tab này.
- Support chỉ nhận candidate duplicate qua chat riêng. Group không áp dụng cho callback candidate
  vì webhook xác thực `telegram_chat_id` của chính tài khoản Support.
- UI chỉ hiển thị metadata cần cho vận hành (chat ID/group title/trạng thái); không trả bot token,
  callback token hay credential platform. Group phải được Bot API xác thực trước khi chọn mode.
- Dynamic values trong template được escape trước khi gửi Telegram. Nội dung test ad-hoc cũng được
  escape như text; Admin chỉ sửa body và placeholder được phép, không sửa logic callback/quyền.
- Nếu mode `group` chưa sẵn sàng, notification designer không fallback âm thầm sang chat riêng.
  Admin phải kiểm tra lỗi hoặc chuyển mode một cách rõ ràng; dữ liệu order vẫn chỉ đọc/ghi qua API.

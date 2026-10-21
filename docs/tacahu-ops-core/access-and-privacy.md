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
- Support chỉ thấy đơn `Waiting` và `Doing` của platform mình, và chỉ gắn tag được cho đơn còn
  `Waiting` (bao gồm các state legacy tương đương), trên web lẫn qua nút Telegram. Đơn chưa gắn tag
  mà Admin đã chia cho designer nằm ở tab `Đang làm`, chỉ xem. Đơn designer đã nộp bài
  (Review/Fix/Done) bị backend loại khỏi danh sách và trả 404 ở trang chi tiết; Support chỉ nhận
  số lượng của chúng (`submitted_count`).
- Khi Support chốt `duplicate`, order lưu `support_classified_by_id` và
  `support_classified_at`, đồng thời ghi timeline để Finance đếm công theo từng Support.
  Chốt `non_duplicate` chỉ đổi trạng thái kiểm tra, không ghi timeline và không được tính
  công; Finance của Support chỉ trả số đơn duplicate do chính tài khoản đó xác nhận.
- Support không có quyền đọc hoặc điều khiển Duplicate Board; board chỉ dành cho Admin và
  Designer Trello. Support cũng không tự nhiên kế thừa quyền sửa state, platform credential
  hay finance admin.
- Support có thể nhận candidate ảnh qua Telegram riêng nếu tài khoản đã link chat và bật
  notification. Candidate `review` chỉ phục vụ test embedding/compare; callback `review` bị
  chặn. Với source live `support_unchecked`, Telegram gửi album gồm ảnh mới và ảnh historical
  top-1, kèm mã/tên hai đơn và hai nút **Trùng**/**Không trùng**. Callback gọi cùng command
  backend như web, ghi actor/version/audit, với cùng giới hạn: order đã được chia cho designer bị
  từ chối kèm thông báo. Quyền quyết định không nằm trong nội dung Telegram.
- Support có thể gửi `/check` trong chat riêng với bot để đếm các order **Chưa kiểm tra** của
  đúng platform mình được gắn. Bot chỉ tạo job sau khi Support bấm **Có, bắt đầu**; token nút
  có hạn dùng, khóa theo chat/platform và không mở quyền cho tài khoản khác. Bấm **Không** chỉ
  hủy yêu cầu, không đổi trạng thái order.

## Tỷ lệ Fix của Designer

Admin (đúng platform) xem tỷ lệ Fix của mọi des trên tab Tiến Độ Team (`/designers/fix-stats`). Mỗi des (thường
và Trello) chỉ xem được **tỷ lệ của chính mình** ở đầu trang My Tasks (`/my/fix-stats`: 7/30/90 ngày, so với kỳ trước
cùng độ dài, danh sách đơn của mình bị Fix kèm nhãn lý do QC như "Lỗi làm khác mockup gốc", không kèm nội dung chat);
platform lấy từ tài khoản des, không từ header. Support và Kế toán nhận 403 ở cả hai. Số liệu tính từ lịch sử đơn (`workflow_events`), không dùng `fix_return_count`: mỗi lần Fix
tính cho người đã nộp bài mà QC trả lời (Admin nộp hộ thì tính cho des được phân công); khoảng thời gian lọc
theo ngày des nộp đơn lần đầu (giờ VN), các lần Fix của đơn đó tính bất kể xảy ra lúc nào. Không tính cho des
nhưng vẫn liệt kê: Fix giả (báo trong 5 phút sau khi des nộp lại đơn Fix, trước 20/10 khi đồng bộ chưa chặn)
và Fix bị Admin từ chối. Dữ liệu đầy đủ từ 21/09/2026 (trước đó Fix chưa được ghi lịch sử từng lần).

## Ảnh mockup nộp bài và xác nhận "Đổi template"

Designer (standard và Trello) tải/xoá ảnh mockup trên đơn mình được xem; ảnh **chưa nộp** chỉ người
tải thấy, ảnh **đã nộp** thì Admin và designer xem được đơn đó thấy. Support và Accountant không truy
cập. Chỉ Admin trả lời câu hỏi "Fix có phải do đổi template không" của Printerval (role khác 403).

## Chat Printerval

Chỉ Admin (đúng platform) đọc chat Printerval của đơn; mọi role khác nhận 403. Designer, Designer Trello và
Support không thấy chat, lý do Fix (`fix_reason` chỉ có trong response của Admin) hay các snapshot
`external_observations`; Admin muốn họ biết thì ghi vào Note làm việc. Ngoại lệ duy nhất: khi Admin duyệt
Fix mà để trống Ghi chú cho Designer, nội dung Fix của QC được copy vào `designer_note`; ảnh của QC đi qua
proxy ảnh `/api/assets/proxy` nên không lộ host Printerval. Đó là quyết định của Admin, Designer vẫn không gọi được API chat.

## Note làm việc: Support

Support đọc, thêm Note làm việc (kể cả ảnh) cho các đơn mà Support được xem (`get_order_detail_for_user`:
cùng platform, trong phạm vi tab Support), ngay trong popup "Xem nhanh sản phẩm". Admin và designer
của đơn thấy các note đó như note khác (nhãn tác giả "Support"). Đơn ngoài phạm vi hoặc platform khác
trả 404.

Designer Trello đọc/thêm Note làm việc trên **mọi** đơn domain trùng lặp của platform (cùng phạm vi
với trang chi tiết đơn, vì Duplicate Board là không gian chung) — kể cả đơn chưa giao cho ai, để thấy
link "Link đơn trùng" Support gắn ở trang ẩn. Đơn domain standard vẫn trả 404.

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

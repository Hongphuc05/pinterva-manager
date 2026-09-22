# Quản lý đích gửi và nội dung Telegram — Design

## Mục tiêu

Thêm khu vực quản trị Telegram cho Admin để theo dõi trạng thái kết nối của
designer, gắn một group chat riêng cho từng designer, chọn đích gửi là chat
riêng hoặc group, và chỉnh nội dung các thông báo text của bot.

Telegram vẫn chỉ là kênh thông báo/callback tùy cấu hình. PostgreSQL vẫn là
nguồn sự thật; không chuyển workflow order, approval hay quyền hạn sang Telegram.

## Baseline hiện tại

- `users.telegram_chat_id` đang là đích chat riêng được link bằng `/start <code>`.
- Ba notification cho designer (đơn mới, Fix, thanh toán) gửi trực tiếp tới
  `designer.telegram_chat_id`.
- Notification cho Admin lấy các `telegram_chat_id` của Admin đang hoạt động.
- Callback Fix của Admin lưu `chat_id` thực tế trong `TelegramActionLog` và
  `TelegramFixConversation`; luồng này phải tiếp tục tương thích.

## Quyết định thiết kế

### Đích gửi của designer

Giữ `telegram_chat_id` làm chat riêng để không phá dữ liệu hiện tại. Thêm vào
`users`:

- `telegram_group_chat_id`: ID group/supergroup gắn với designer;
- `telegram_group_title`, `telegram_group_type`: metadata lấy từ Telegram;
- `telegram_group_verified`, `telegram_group_verified_at`;
- `telegram_group_last_error`;
- `telegram_delivery_mode`: `private` hoặc `group`.

Chỉ một group được gắn cho mỗi designer ở phiên bản này. Thêm unique partial
index cho group ID để không gắn cùng một group cho hai designer. Mặc định mode
là `private`; các user đã link vẫn giữ nguyên behavior.

### Xác thực group

Admin nhập group ID rồi gọi backend. Backend dùng token của bot để gọi
`getChat`, kiểm tra loại chat là `group`/`supergroup`, sau đó gọi
`getChatMember` cho chính bot để xác nhận bot đã ở trong group và có thể gửi.
Chỉ group đã xác thực mới được chọn làm đích gửi. Không fallback âm thầm sang
DM khi mode group bị lỗi; lỗi phải hiện trên UI và log.

### Template message

Thêm bảng `telegram_message_templates`, mỗi khóa duy nhất theo `template_key`.
Template có audience (`designer`/`admin`), nội dung text, trạng thái active,
version, người sửa và thời điểm sửa. Placeholder được allowlist theo template,
được validate trước khi lưu và render bằng context typed. Template admin chỉnh
text thôi, không chỉnh token, URL API, callback token hay quyền.

Template mặc định bao phủ các event đang có:

- `designer_new_order`, `designer_urgent_fix`, `designer_payment`;
- `admin_new_fix`, `admin_review_submitted`, `admin_missing_template`,
  `admin_excessive_fix`, `admin_deadline_overdue`, `admin_system_alert`.

Ảnh thumbnail vẫn có thể được gửi như phần media hiện hành; form quản trị chỉ
chỉnh caption/text, không quản lý media.

### Audit và authorization

API quản trị mới chỉ cho `admin`, scope theo platform hiện hành khi danh sách
designer được lấy. Thay đổi group/mode/template ghi `WorkflowEvent` không phù
hợp vì event bắt buộc order; thay vào đó thêm bảng audit Telegram cấu hình, lưu
actor, loại thay đổi, target và before/after JSON.

## API dự kiến

- `GET /telegram/admin/overview`
- `PUT /telegram/admin/designers/{user_id}/group`
- `POST /telegram/admin/designers/{user_id}/group/verify`
- `PATCH /telegram/admin/designers/{user_id}/delivery-mode`
- `POST /telegram/admin/designers/{user_id}/test`
- `GET /telegram/admin/templates`
- `PUT /telegram/admin/templates/{template_key}`
- `POST /telegram/admin/templates/{template_key}/preview`

Các endpoint đều có `require_role('admin')`, dùng session/platform scope hiện
hành và trả lỗi validation rõ ràng.

## Routing runtime

Mọi notification cho designer phải gọi một resolver duy nhất:

1. Nếu notifications bị tắt: bỏ qua có kiểm soát.
2. Nếu mode `private`: yêu cầu `telegram_chat_id`.
3. Nếu mode `group`: yêu cầu group đã verify và có `telegram_group_chat_id`.
4. Render template theo event, rồi gửi tới đúng `chat_id`.

Admin notification vẫn dùng các chat riêng hiện tại. Callback Fix tiếp tục xác
thực Admin bằng chat riêng và lưu đúng chat thực tế đã nhận message.

## UI

Thêm route `/telegram-management`, chỉ Admin truy cập, và item trong Sidebar
section Cài đặt. Trang gồm:

- card trạng thái bot;
- bảng designer: DM, group, trạng thái verify, mode, lỗi gần nhất;
- form nhập/kiểm tra group ID, chọn mode, gửi test;
- khu vực template: chọn event, sửa text, xem placeholder/preview, lưu và khôi
  phục mặc định.

## An toàn và rollback

- Không ghi token bot hoặc dữ liệu Telegram nhạy cảm vào log/UI ngoài metadata
  cần thiết.
- Không chuyển mode sang group nếu chưa verify.
- Migration nullable, mode mặc định `private`, rollback chỉ xóa cột/bảng mới;
  dữ liệu DM cũ không bị đụng.
- Nếu group hỏng, Admin chuyển lại `private`; không cần deploy lại.

## Acceptance criteria

1. Admin nhìn thấy mọi designer thuộc platform hiện hành và trạng thái DM/group.
2. Admin gắn, verify, đổi và xóa group ID; group trùng bị từ chối.
3. Admin đổi DM/group; notification designer đi đúng đích đã chọn.
4. Mode group thiếu/sai cấu hình không gửi nhầm sang DM.
5. Admin sửa template, preview được placeholder, notification mới dùng nội dung đã lưu.
6. Callback Fix/admin notification hiện tại không regression.
7. Non-admin không đọc/sửa được API hoặc route mới.
8. Migration, backend tests, frontend tests và build đều pass trong phạm vi có thể xác minh.

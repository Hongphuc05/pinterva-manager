# Dữ liệu và nơi lưu trữ

## Kết luận vận hành

Production được thiết kế là một Docker Compose stack trên VPS: PostgreSQL 16 và Redis chạy
trong container, còn dữ liệu persistent được bind-mount dưới đường dẫn tuyệt đối `DATA_DIR`
trên ổ đĩa VPS. PostgreSQL là nguồn sự thật cho nghiệp vụ nội bộ; Redis chỉ phục vụ queue,
schedule và cache.

Không coi Google Sheet, Printerval, frontend bundle hoặc Redis là bản ghi authoritative của
workflow Tacahu.

## Phân loại dữ liệu

| Nhóm | Nội dung chính | Nơi authoritative | Ghi chú |
| --- | --- | --- | --- |
| Identity và quyền | user, role, platform scope, trạng thái hoạt động, Telegram identity và private/group delivery mode | PostgreSQL | Mật khẩu lưu hash/ciphertext; credential platform/session cookie là dữ liệu nhạy cảm. Group ID là cấu hình routing, không phải bot token. |
| Đơn hàng | mã external, product/SKU/variant, deadline, note, custom config, state, optimistic version, payment | PostgreSQL | URL Printerval/Drive/thumbnail/gallery/source thường là reference/metadata, không đảm bảo file bytes nằm trong DB. |
| Phân công và QC | assignment, submission/result version, approval, Fix | PostgreSQL | Link bài nộp và feedback thuộc record nghiệp vụ/audit. |
| Audit và integration | workflow event, operation/idempotency, outbox, dead letter, external observation, sync job | PostgreSQL | Dùng để đối soát retry, external write và lỗi async. |
| Note làm việc | body, author, read state, metadata attachment | PostgreSQL | Bytes screenshot/ảnh được tách khỏi DB. |
| QR ngân hàng Designer/Support | user, thứ tự, metadata ảnh | PostgreSQL + `private_work_note_assets/bank_qr` | Chỉ endpoint có authorization mới đọc được; tối đa 3 ảnh/tài khoản. |
| Asset đã tải | crawled asset, source/order asset, checksum/storage location | PostgreSQL metadata + VPS filesystem | File bytes nằm dưới `DATA_DIR/crawled_assets` hoặc `DATA_DIR/order_assets`. |
| Browser/platform runtime | session/profile, Playwright evidence | VPS filesystem | Dưới `DATA_DIR/platform_data`, `chrome_profiles`, `playwright_evidence`; cần bảo vệ như credential/evidence. |
| Queue/cache | Celery message, schedule runtime, Redis AOF | Redis tại `DATA_DIR/redis` | Không dùng để khôi phục business state. |
| Hệ thống ngoài | dữ liệu gốc Printerval, Drive links, Google Sheet export | Dịch vụ ngoài | Printerval là integration; Google Sheet chỉ là export/backup tùy cấu hình. |
| So sánh ảnh Support | run, order image embedding, historical candidate, similarity và quyết định Telegram | PostgreSQL schema `support_compare_image` | Vector phase 1 dùng `facebook/dinov2-base`; không trộn với weight fine-tune khác model space. |

## Xóa tài khoản (Admin)

- **Khóa** (`PATCH /users/{id}/active`, `active=false`): không xóa gì — chặn đăng nhập/mất
  hiệu lực phiên ngay, thu hồi mọi máy Support đang được cấp quyền, và ẩn khỏi danh sách
  mặc định (`GET /users`, dùng `?include_locked=true` để xem lại/mở khóa). Đây là lựa chọn
  mặc định nên dùng — giữ nguyên toàn bộ lịch sử.
- **Xóa an toàn** (`DELETE /users/{id}`, không `force`): từ chối (409) nếu tài khoản còn
  bất kỳ record nào thuộc về chính nó (assignment, note, quyết định duyệt, audit Telegram...
  — danh sách đủ ở `_USER_OWNED_TABLES` trong `app/api/routes/users_api.py`).
- **Xóa toàn bộ** (`DELETE /users/{id}?force=true`): admin xác nhận tường minh muốn mất
  lịch sử. Hai nhóm FK khác chính sách (migration `f5d6e7f8a9b0`):
  - record **thuộc về chính user đó** (Assignment, OrderWorkNote, ApprovalDecision,
    PrintervalAssignmentRequest, FinanceNote, TelegramActionLog,
    TelegramConfigurationAudit) → `ON DELETE CASCADE`, xóa theo.
  - record **về thứ khác mà user chỉ là actor** (WorkflowEvent của một Order,
    `Order.processing_lock_owner_id`/`template_missing_reported_by_id`,
    `SyncJob.created_by_id`, `TelegramMessageTemplate.updated_by_id`) →
    `ON DELETE SET NULL`, record gốc (đặc biệt là audit trail của Order) được giữ nguyên,
    chỉ mất "ai đã làm". `PaymentBatch`/`Order.paid_by_id` đã `SET NULL` từ trước và còn
    lưu tên dạng text (`paid_by_name`/`designer_name`), nên lịch sử thanh toán vẫn đọc
    được dù user đã bị xóa hẳn.

## Username không còn duy nhất toàn hệ thống

`uq_users_platform_id_username` (migration `f5d6e7f8a9b0`) thay cho unique toàn cục cũ —
hai platform khác nhau được phép có cùng username (ví dụ mỗi Acc Mẹ tự có "admin"/"des1"
riêng). Đăng nhập không có bước chọn platform trước: `POST /login` thử từng tài khoản
trùng username và so khớp bằng password (`app/api/routes/auth.py`). Nơi nào từng giả định
username là khóa duy nhất toàn cục để tra cứu theo tên (không qua `user_id`) phải lọc thêm
theo `platform_id` — đã sửa ở `get_finance_stats` (map tên designer) và
`take_duplicate_orders` (tài khoản `des1` nội bộ).

## Chat Printerval của từng đơn (bản sao chỉ đọc)

Printerval có khung chat riêng cho mỗi đơn (QC báo Fix ở đó thay vì `note_outsource`). Tacahu chép về
PostgreSQL, không ghi gì ngược lại:

- `order_chat_messages`: mỗi tin một dòng, khóa duy nhất `(order_id, external_id)`; có `fix_round`,
  `message_type` (`fix_open`...), `sender_type` (`staff` = phía Printerval), `mine`, `content`,
  `image_urls` (chỉ http/https), `sent_at` (Printerval trả giờ Việt Nam không kèm múi giờ).
- `order_chat_reads`: tin cuối mỗi tài khoản đã xem trên từng đơn. Đây là trạng thái chưa đọc của
  riêng Tacahu, vì Printerval tính "đã đọc" cho cả đội ngay khi một request `messages` được gọi.
- `orders.chat_last_message_id` (con trỏ `after_id`) và `orders.chat_synced_at`.
- Giữ 30 ngày (`ORDER_CHAT_RETENTION_DAYS`) sau khi đơn Done/Cancelled rồi xóa toàn bộ tin, trạng thái
  đọc và con trỏ; đơn mở lại thì kéo lại từ đầu. Bật bằng `ORDER_CHAT_ENABLED=true`.

## Dữ liệu quản trị Telegram

- Các cột `telegram_group_*` và `telegram_delivery_mode` nằm trên `users`; group ID, title,
  loại group, trạng thái verify và lỗi gửi gần nhất phải được backup cùng PostgreSQL.
- `telegram_message_templates` lưu text template, audience, version và người sửa. Migration seed
  các template mặc định cho Designer, Admin và Support; Admin có thể sửa/preview/reset, còn
  placeholder được backend allowlist.
- `telegram_configuration_audits` lưu actor, target/template, action và before/after JSON để đối
  soát thay đổi cấu hình. Không lưu bot token hoặc raw callback token trong bảng này.
- Telegram không phải source of truth: mất message/Telegram outage không làm mất assignment,
  order state, approval hoặc payment state.
- `comparison_runs`, `comparison_items` và `comparison_candidates` là audit/queue của image
  comparison. Chúng không thay thế `orders`; quyết định `duplicate`/`non_duplicate` vẫn phải
  đi qua application service và tạo workflow event.

## Layout production theo compose

`compose.production.yaml` bind-mount các đường dẫn sau từ `DATA_DIR` trên VPS:

```text
postgres/             PostgreSQL data directory
redis/                Redis AOF
crawled_assets/       ảnh/tệp lấy khi crawl
order_assets/         source/order asset đã lưu cục bộ
private_work_note_assets/ screenshot/ảnh private của Note làm việc; QR ngân hàng nằm trong thư mục con `bank_qr/`
platform_data/        dữ liệu runtime platform
playwright_evidence/  evidence browser automation
chrome_profiles/      Chrome profile/session
```

`support_compare_image.worker_devices.agent_info` (JSONB) lưu thông tin máy agent tự báo (loại máy, tiến độ
tải pool/so sánh) để các tài khoản Support khác xem; đây là dữ liệu hiển thị, không ảnh hưởng quyền.

`support_compare_image.comparison_jobs` là hàng đợi durable để máy Support local claim job; model
checkpoint Hugging Face và cache của nó nằm trên máy Support, không nằm trong `DATA_DIR` production.
Máy local nên dùng SSH tunnel/private VPN; không mở port PostgreSQL ra Internet.

Port PostgreSQL chỉ bind `127.0.0.1` của VPS, không public Internet theo compose hiện hành.
Vì vậy không có dấu hiệu từ cấu hình rằng production dùng managed PostgreSQL riêng; database
được thiết kế lưu trên disk VPS qua `DATA_DIR/postgres`.

## Attachment screenshot của Note làm việc

`OrderWorkNoteAttachment` lưu metadata và `storage_key` trong PostgreSQL. File bytes được API
ghi vào `/app/private_work_note_assets` và download lại qua endpoint có authorization; đây là
đúng để không tạo URL public cho ảnh nội bộ.

`compose.yaml` local và `compose.production.yaml` mount thư mục này ra
`DATA_DIR/private_work_note_assets`, nên file ảnh còn tồn tại sau recreate/replace API container:

```text
${DATA_DIR}/private_work_note_assets:/app/private_work_note_assets
```

`production-preflight.sh` từ chối deploy nếu thư mục persistent chưa tồn tại;
`backup-production-assets.sh` đưa nó vào archive asset. VPS đang chạy bản release cũ vẫn cần
deploy compose mới và xác minh `docker inspect` để nhận mount này. `deploy-production.sh`
copy ảnh từ API container cũ trước recreate khi (và chỉ khi) container chưa có mount, có ảnh,
và thư mục host đích đang rỗng; dữ liệu mâu thuẫn làm deploy dừng thay vì ghi đè.

## Backup và khôi phục

Một bản backup có thể khôi phục đầy đủ cần gồm:

1. `pg_dump` PostgreSQL, bao gồm metadata asset/attachment và toàn bộ workflow.
2. Các thư mục asset persistent nêu trên, bao gồm `private_work_note_assets`.
3. Bảo mật secret/credential riêng với backup application data; không commit hay gửi vào chat.

Khôi phục DB đơn lẻ có thể tạo các reference tới file không còn. Khôi phục volume đơn lẻ có thể
tạo file mồ côi không còn record/quyền truy cập. Luôn restore cùng cặp và kiểm tra một attachment
private, một source asset và một workflow record sau restore.

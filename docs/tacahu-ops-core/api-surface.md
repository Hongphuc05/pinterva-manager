# API surface hiện hành

Base path là `/api`. Frontend client tự thêm prefix này; `VITE_API_BASE_URL` có thể là
origin hoặc origin kèm `/api` nhưng không được tạo `/api/api`.

## Nhóm API chính

| Nhóm | Endpoint tiêu biểu |
| --- | --- |
| Auth | `POST /login`, `POST /logout`, `GET /me` |
| Orders | `GET /orders`, `GET /orders/{id}`, `PATCH /orders/{id}/state`, refresh/sync/history |
| Work note | `GET/POST /orders/{id}/work-notes`, `GET .../attachments/{attachment_id}` |
| Ảnh mockup nộp bài | `GET/POST /orders/{id}/result-images` (tải trước, tối đa 3, PNG/JPEG ≤ 10 MB), `DELETE .../result-images/{image_id}` (chỉ ảnh chưa nộp), `GET .../result-images/{image_id}/file`; lần nộp gửi `image_ids` (1–3, bắt buộc với Designer) ở `POST /assignments/{id}/results` và `PATCH /orders/{id}/state` |
| Xác nhận Fix "Đổi template" (Admin) | `POST /orders/{id}/printerval-template-confirm` `{decision: agree\|disagree, note, request_id}`; yêu cầu đang chờ hiện ở `fix_template_confirm` của `GET /orders/{id}` |
| Chat Printerval (Admin) | `GET /orders/{id}/printerval-chat` (đọc ngay, 502 khi Printerval lỗi), `GET /printerval-chat/unread` (đơn còn tin chưa đọc trên Printerval; `stale: true` khi Printerval không trả lời) |
| Assignment | tạo/revoke assignment; task start/sub-status/result/flag missing template |
| Fix | `POST /orders/{id}/approve-fix`, `POST /orders/{id}/reject-fix-to-review` |
| Duplicate | `GET /duplicate-board`, move card, duplicate domain/check status/settings; Support web chỉ check order còn Waiting, callback compare có scope Doing riêng |
| Platform | CRUD platform và Printerval option/credential scope |
| Finance | rates, stats, payment mark/unmark, export, finance note |
| External sync | crawl/gallery import, SyncJob, status sync và external assignment request |
| Telegram | status/link/unlink/webhook; quản trị routing/template dưới `/telegram/admin`; là kênh phụ tùy cấu hình, không thay database authority |

## Contract command

- Command thay đổi order dùng `request_id`/idempotency theo endpoint.
- Admin và `designer-trello` gửi `expected_version` tại các luồng đã rollout concurrency.
- Conflict trả HTTP 409 với `ORDER_VERSION_CONFLICT`; frontend phải refresh thay vì retry
  mù.
- Legacy endpoint vẫn tồn tại trong migration window có header `X-Deprecated-Endpoint: true`.
  Không dùng chúng cho feature mới; danh sách code tại `app/api/main.py::DEPRECATED_PATHS`.

## Quản trị Telegram Bot (Admin-only)

Các endpoint dưới đây yêu cầu role `admin` và dùng platform scope hiện hành cho danh sách người
nhận (Designer/Support). Token bot không bao giờ được trả về frontend.

| Method | Endpoint | Mục đích |
| --- | --- | --- |
| `GET` | `/telegram/admin/overview` | Trạng thái bot và kết nối của các Designer/Support trong Acc Mẹ hiện hành |
| `PUT` | `/telegram/admin/designers/{user_id}/group` | Lưu hoặc thay group chat ID cho Designer; chưa coi là đã xác thực |
| `DELETE` | `/telegram/admin/designers/{user_id}/group` | Xóa mapping group của Designer, mode group tự chuyển về private |
| `POST` | `/telegram/admin/designers/{user_id}/group/verify` | Gọi Telegram `getChat`/`getMe`/`getChatMember` để xác thực group Designer |
| `PATCH` | `/telegram/admin/designers/{user_id}/delivery-mode` | Chọn `private` hoặc `group` cho Designer; Support chỉ dùng `private` |
| `POST` | `/telegram/admin/designers/{user_id}/test` | Gửi một tin nhắn text test tới đích đang chọn; Support gửi qua chat riêng |
| `GET` | `/telegram/admin/templates` | Đọc danh sách template và placeholder allowlist |
| `PUT` | `/telegram/admin/templates/{template_key}` | Sửa nội dung text template |
| `POST` | `/telegram/admin/templates/{template_key}/preview` | Render preview bằng dữ liệu mẫu/được cung cấp |
| `POST` | `/telegram/admin/templates/{template_key}/reset` | Khôi phục template mặc định |

Khi mode là `group` nhưng group chưa được xác thực hoặc gửi thất bại, service không tự fallback
sang private chat; cấu hình lỗi phải được Admin sửa hoặc chuyển mode rõ ràng.

Các path vẫn giữ tên `designers` để tương thích client cũ, nhưng `{user_id}` được backend kiểm
tra trong tập recipient gồm `designer`, `designer-trello` và `support`. Support group bị từ chối
vì callback duplicate chỉ xác thực chat riêng.

### Hàng đợi so sánh ảnh

- `GET /support-worker/queue` (Support): `waiting_jobs`, `jobs`, `machines` (đếm) và `hosts` — các máy đang
  được cho phép của platform kèm tài khoản chủ máy, trạng thái (`idle`/`busy`/`paused`/`offline`), loại
  máy và tiến độ tự báo của agent. Mọi tài khoản Support cùng platform thấy như nhau.
- Agent gửi `X-Agent-Info` trên mọi request; server bỏ qua field lạ hoặc sai kiểu.
- `GET /support-compare/status`, `POST /support-compare/check`, `POST /support-compare/handle` (Support):
  cùng thao tác với lệnh Telegram `/check` và `/handle` → **Có**. `/check` xếp các đơn chưa từng so sánh vào một
  job (cần tài khoản đã liên kết Telegram để nhận báo cáo); `/handle` chuyển các đơn đã so sánh mà không thấy
  trùng sang Không trùng lặp. Cả hai trả 409 khi không còn đơn nào để xử lý.

### Phân loại order và công Support

- `POST /orders/duplicate-check-status` và `POST /orders/duplicate-domain` cho phép Admin/Support,
  nhưng Support chỉ thao tác được trên order ở `Waiting` hoặc state legacy tương đương. Order đã
  được chia trả HTTP 400, kể cả khi chưa gắn tag; callback Telegram áp dụng cùng quy tắc.
- `GET /orders/page` (Admin, Support, Designer, Designer-Trello; Accountant bị chặn): trang danh sách đơn phân
  trang ở server, tab theo role — Admin `waiting|doing|review|fix|done`, Support
  `all|duplicate|non_duplicate|doing`, Designer `doing|fix|review|waiting_update|paid|done`. Tham số: `doing_sub`, `fix_sub`, `q`, `status`, `designer_id`,
  `platform_status`, `batch`, `date_field`/`date_from`/`date_to` (ngày theo UTC+7), `fix_returned`,
  `synced_images`, `sort_field`/`sort_dir`, `page`/`page_size` (≤200). Trả `items`, `total`,
  `counts` (số đơn từng tab, không áp bộ lọc), `aux` và `search_counts` khi có `q`. `ids_only=true` trả
  danh sách id của tab (tối đa 5000) cho nút đồng bộ cả tab. `GET /orders/platform-designers` trả tên
  designer Printerval cho bộ lọc quét đơn. Danh sách đơn trên web không còn tải toàn bộ `GET /orders`. Designer chỉ tìm theo tên sản phẩm; `batch` chỉ
  Admin/Support dùng.
  Admin lọc thêm theo tag kiểm tra trùng bằng `check_status=unchecked|checked` (ở tab Waiting,
  `checked` = Không trùng lặp vì đơn Trùng lặp đã sang board); popup "Chia đơn nhanh" có cùng 3 nhóm.
- `GET/POST /orders/{id}/work-notes`: Admin, Designer, Designer-Trello và Support (đơn Support được xem).
- Response API được nén gzip; `/assets` có `Cache-Control: immutable` (tên file có hash).
- `GET /orders` với role Support chỉ trả order `Waiting`/`Doing` và thêm `submitted_count`: số order
  đã qua Doing (Review/Fix/Done) của platform, không trả nội dung. `GET /orders/{id}` trả 404 cho
  các order đó.
- Khi Support chốt `duplicate`, order lưu người và thời điểm tại
  `support_classified_by_id`/`support_classified_at` và có timeline Support. Chốt
  `non_duplicate` không lưu attribution/timeline và không được tính công.
- `GET /finance/stats` với role Support bị scope theo `user.platform_id` và chỉ trả số đơn
  duplicate do chính Support đó xác nhận. Admin nhận thêm `support_classified_count` và
  `support_summary` để đối soát công theo người.

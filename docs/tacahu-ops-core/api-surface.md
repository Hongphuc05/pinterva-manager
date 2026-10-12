# API surface hiện hành

Base path là `/api`. Frontend client tự thêm prefix này; `VITE_API_BASE_URL` có thể là
origin hoặc origin kèm `/api` nhưng không được tạo `/api/api`.

## Nhóm API chính

| Nhóm | Endpoint tiêu biểu |
| --- | --- |
| Auth | `POST /login`, `POST /logout`, `GET /me` |
| Orders | `GET /orders`, `GET /orders/{id}`, `PATCH /orders/{id}/state`, refresh/sync/history |
| Work note | `GET/POST /orders/{id}/work-notes`, `GET .../attachments/{attachment_id}` |
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
- `GET /orders` với role Support chỉ trả order `Waiting`/`Doing` và thêm `submitted_count`: số order
  đã qua Doing (Review/Fix/Done) của platform, không trả nội dung. `GET /orders/{id}` trả 404 cho
  các order đó.
- Khi Support chốt `duplicate`, order lưu người và thời điểm tại
  `support_classified_by_id`/`support_classified_at` và có timeline Support. Chốt
  `non_duplicate` không lưu attribution/timeline và không được tính công.
- `GET /finance/stats` với role Support bị scope theo `user.platform_id` và chỉ trả số đơn
  duplicate do chính Support đó xác nhận. Admin nhận thêm `support_classified_count` và
  `support_summary` để đối soát công theo người.

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

### Phân loại order và công Support

- `POST /orders/duplicate-check-status` và `POST /orders/duplicate-domain` vẫn cho phép
  Admin/Support, nhưng command web chỉ cho Support thao tác trên order ở `Waiting` hoặc state
  legacy tương đương. Order đã được chia hoặc đã sang `Doing` trả HTTP 400 từ command web.
- `GET /orders` và `GET /orders/{id}` trả mọi order `Doing` cho Support; order `Doing` chưa
  kiểm tra cũng xuất hiện trong tab **Chưa kiểm tra** để scheduler so sánh. Support không có
  nút web để phân loại các order này: chỉ callback Telegram của source `support_unchecked` mới
  được phép quyết định. Order đã có phân loại `duplicate` hoặc `non_duplicate` vẫn được trả sau
  khi state chuyển sang `Doing`/`Review`/`Done`.
- Khi Support chốt `duplicate`, order lưu người và thời điểm tại
  `support_classified_by_id`/`support_classified_at` và có timeline Support. Chốt
  `non_duplicate` không lưu attribution/timeline và không được tính công.
- `GET /finance/stats` với role Support bị scope theo `user.platform_id` và chỉ trả số đơn
  duplicate do chính Support đó xác nhận. Admin nhận thêm `support_classified_count` và
  `support_summary` để đối soát công theo người.

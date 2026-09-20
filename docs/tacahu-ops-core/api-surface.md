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
| Duplicate | `GET /duplicate-board`, move card, duplicate domain/check status/settings |
| Platform | CRUD platform và Printerval option/credential scope |
| Finance | rates, stats, payment mark/unmark, export, finance note |
| External sync | crawl/gallery import, SyncJob, status sync và external assignment request |
| Telegram | status/link/unlink/webhook; là kênh phụ tùy cấu hình, không thay database authority |

## Contract command

- Command thay đổi order dùng `request_id`/idempotency theo endpoint.
- Admin và `designer-trello` gửi `expected_version` tại các luồng đã rollout concurrency.
- Conflict trả HTTP 409 với `ORDER_VERSION_CONFLICT`; frontend phải refresh thay vì retry
  mù.
- Legacy endpoint vẫn tồn tại trong migration window có header `X-Deprecated-Endpoint: true`.
  Không dùng chúng cho feature mới; danh sách code tại `app/api/main.py::DEPRECATED_PATHS`.


# API contract V1 — inventory và hướng rút gọn

Tài liệu này là baseline cho Phase 1. `POST /orders/*` legacy chưa bị xóa chỉ vì
đã có endpoint mới; mỗi endpoint chỉ được xóa sau khi không còn consumer trong UI,
extension và telemetry vận hành.

## Quy ước chung

- Tất cả route dưới đây có prefix `/api`.
- Request xác thực bằng session cookie hoặc Bearer token. Request có dữ liệu theo
  Acc Mẹ dùng `X-Platform-Id`; chỉ admin được chọn header này.
- Platform scope là bắt buộc cho Order, Sync Job, Printerval option và gallery.
- Không response nào được trả `account_password`, `session_cookie` hay gallery token
  đã lưu. Token CopyImage chỉ trả plaintext một lần khi rotate.
- Các command async trả job/lifecycle để UI poll; không suy đoán thành công chỉ vì
  request đã được nhận.

## API giữ lại và là contract mục tiêu

| Nhóm | Method + route | Role | Consumer | Ghi chú |
| --- | --- | --- | --- | --- |
| Health | `GET /health` | public | deploy | liveness |
| Auth | `POST /login`, `POST /logout`, `GET /me` | public/auth | web | giữ nguyên V1 |
| Platform | `GET, POST /platforms` | admin | settings modal | list đã redaction secret |
| Platform | `PATCH /platforms/{id}/credentials` | admin | settings modal | verify rồi mới lưu credential cho đúng Acc Mẹ |
| Platform | `POST /platforms/{id}/gallery-bridge-token` | admin | settings modal | rotate token CopyImage |
| Platform | `DELETE /platforms/{id}` | admin | settings | deactivate/delete theo hiện trạng |
| Order query | `GET /orders`, `GET /orders/{id}`, `GET /orders/{id}/history` | auth | admin/designer UI | scoped theo platform và quyền designer |
| Order read | `GET /order-states`, `GET /orders/{id}/printerval-options`, `POST /platforms/printerval-options/refresh` | auth/admin | orders UI | options cache theo platform |
| Order command | `POST /orders/refresh`, `POST /orders/{id}/refresh-detail` | admin | crawl/detail UI | crawl mới và refresh một order |
| Sync | `POST /sync-jobs`, `GET /sync-jobs/current`, `GET /sync-jobs/{id}` | admin/auth | topbar/orders | durable background status sync |
| Assignment | `POST /assignments` | admin | orders UI | một command nhận snapshot `order_ids`, single và bulk cùng contract |
| Workflow | `PATCH /orders/{id}/state`, `POST /orders/{id}/approve-fix`, `POST /orders/{id}/reject-fix-to-review` | auth/admin | detail/status UI | sẽ chuyển về action transition rõ nghĩa |
| Designer task | `GET /my-tasks`, `POST /assignments/{id}/start`, `PATCH /assignments/{id}/sub-status`, `POST /assignments/{id}/results` | designer | task UI | giữ model Assignment |
| User | `GET, POST /users`, `GET, PATCH /users/{id}/password`, `DELETE /users/{id}` | admin | users UI | password policy tách riêng |
| Report | `GET /designers/workload`, `GET /finance/stats`, `GET /orders-history` | auth | board/report | rename namespace trong Go phase |
| Integration | `POST /integrations/printerval-gallery` | CopyImage token | Chrome extension | không dùng web session |

## Legacy và lộ trình thay thế

| Endpoint | Consumer hiện tại | Thay bằng | Hành động Phase 1 |
| --- | --- | --- | --- |
| `GET /orders/sync-status` | legacy UI còn lại | `GET /sync-jobs/current` | giữ một release, frontend mới không gọi |
| `POST /orders/sync-status/run` | không còn frontend chính | `POST /sync-jobs` | deprecate |
| `POST /orders/sync-status/reset` | không còn frontend chính | không có reset public | deprecate |
| `POST /orders/sync-printerval-status` | Orders, Topbar, DesignerBoard/History cũ | `POST /sync-jobs` | Orders/Topbar đã chuyển; chuyển view còn lại ở Task 1.4 |
| `POST /orders/printerval-credentials` | test/consumer legacy | `PATCH /platforms/{id}/credentials` | compatibility adapter, không thêm consumer mới |
| `POST /orders/{id}/printerval-assignment`, `POST /orders/bulk-printerval-assignment` | `OrderStatusPage` legacy | `POST /assignments` | Orders list đã chuyển; giữ route cũ tới khi Task 1.4 gỡ page legacy |
| `/printerval-login/status`, `/start`, `/done` | browser-login legacy | cookie credential flow | route UI đã redirect; giữ rollback window |
| `POST /orders/{id}/assign`, `POST /orders/bulk-assign` | không thấy frontend | `/assignments` | không port Go |
| `GET /admin/ping`, `GET /designer/ping` | test RBAC | middleware test | không port Go |

## Contract Sync Job

`POST /sync-jobs` nhận:

```json
{ "type": "status_sync", "order_ids": ["uuid-1", "uuid-2"] }
```

- `order_ids` là snapshot order của tab tại thời điểm bấm; tối đa 500. Không gửi
  list nghĩa là toàn bộ order của platform.
- Cùng platform + cùng snapshot khi đang `queued` hoặc `running` trả lại cùng job,
  không tạo công việc trùng.
- `GET /sync-jobs/current` trả job active, hoặc job gần nhất để UI hiển thị kết quả/lỗi
  sau khi F5. Job không chứa credential hay raw request header.

## Telemetry deprecation còn thiếu

Trước khi xóa legacy route, middleware phải ghi structured event gồm: route, method,
actor role, platform id, request id và user-agent. Tuyệt đối không log request body,
Authorization header, cookie hoặc token. Phần này sẽ được thêm cùng middleware request
id ở Task 1.7, sau khi frontend chuyển hết consumer.

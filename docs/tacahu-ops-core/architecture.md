# Kiến trúc hiện hành

## Mục tiêu và boundary

Tacahu Ops là dashboard nội bộ quản lý design job từ Printerval/platform: lấy dữ liệu,
phân loại/phân công, theo dõi tiến độ, nhận bài, đồng bộ trạng thái và xử lý Fix. Đây
không phải bản sao của Printerval: **PostgreSQL là nguồn sự thật cho workflow nội bộ**.

```text
React SPA ── /api ── FastAPI command/query layer ── PostgreSQL
                    │              │
                    │              ├── Redis + Celery (queue, beat, workers)
                    │              ├── private/local asset volumes
                    │              └── Printerval HTTP API, Playwright fallback
                    │
                    └── optional Telegram notifications/control callbacks
                         └── Admin-managed private/group routing + editable text templates
```

## Thành phần runtime

- `frontend/`: React, TypeScript, Vite, Tailwind; FastAPI phục vụ `frontend/dist` khi
  build production tồn tại.
- `app/api/`: HTTP API, xác thực session/bearer, platform scope và response sanitization.
- `app/application/` + `app/domain/`: rule nghiệp vụ, state transition, idempotency,
  optimistic concurrency và audit event.
- `app/adapters/db/`: SQLAlchemy model và Alembic migration.
- `app/workers/`: Celery cho crawl, status sync, external assignment/review writes,
  Google Sheet backup và Telegram notification.
- `compose.yaml` / `compose.production.yaml`: API, migration, Redis, PostgreSQL,
  general worker, serialized assignment worker, Celery Beat và Cloudflare Tunnel.

### Telegram management boundary

Telegram là side channel tùy chọn. `User.telegram_chat_id` vẫn là kết nối chat riêng; Admin có
thể gắn thêm một group đã được Bot API xác thực và chọn mode gửi cho từng designer. Resolver trong
`telegram_service` là điểm duy nhất quyết định đích gửi designer; mode `group` thiếu verification
thì bỏ qua có kiểm soát, không âm thầm gửi sang DM. Nội dung message được render từ template lưu
trong PostgreSQL với placeholder allowlist; token bot, callback token và quyền workflow không nằm
trong template.

Các thay đổi mapping/mode/template được ghi vào `telegram_configuration_audits`. Callback Fix của
Admin vẫn dùng chat riêng hiện hành và các state/approval vẫn do API/PostgreSQL quyết định.

## Dữ liệu và side effect

| Lớp | Trách nhiệm |
| --- | --- |
| PostgreSQL | order state, assignment, result version, workflow event, operation, work note, finance và quyền truy cập |
| Redis/Celery | hàng đợi và schedule; không là source of truth |
| Printerval | hệ thống ngoài để crawl/đọc status và nhận external write có kiểm chứng |
| Local/private volumes | crawled assets, source/order assets, platform/browser profile và Playwright evidence; xem trạng thái persistence từng loại tại [data-storage.md](data-storage.md) |
| Google Sheet | backup/export tùy cấu hình, không quyết định state |

Mọi external write phải được xếp queue, có evidence/audit và tránh ghi đè state Tacahu
mới hơn. Worker review reload order trước khi ghi để bỏ job stale.

Metadata và nội dung nghiệp vụ được lưu trong PostgreSQL; file nhị phân không mặc định nằm
trong DB. Vì vậy backup/restore phải ghép cặp database dump với các private asset volume.

## Đồng thời và audit

- Các command quan trọng dùng `expected_version` với Admin và `designer-trello`; conflict
  trả HTTP 409 có chi tiết revision thay vì ghi đè âm thầm.
- `Operation`/request id hỗ trợ idempotency cho hành động có side effect.
- `WorkflowEvent`, `ResultVersion`, work note và finance note là append-only về mặt
  nghiệp vụ; không dùng chat/note thay cho quyền hoặc state transition.

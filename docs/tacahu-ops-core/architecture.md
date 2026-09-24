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
  Google Sheet backup, Telegram notification và tạo/điều phối job duplicate-image.
- `compose.yaml` / `compose.production.yaml`: API, migration, Redis, PostgreSQL,
  general worker, serialized assignment worker, Celery Beat và Cloudflare Tunnel.
  DINO không chạy trong Compose production.

### Telegram management boundary

Telegram là side channel tùy chọn. `User.telegram_chat_id` vẫn là kết nối chat riêng; Admin có
thể gắn thêm một group đã được Bot API xác thực và chọn mode gửi cho từng designer. Resolver trong
`telegram_service` là điểm duy nhất quyết định đích gửi designer; mode `group` thiếu verification
thì bỏ qua có kiểm soát, không âm thầm gửi sang DM. Nội dung message được render từ template lưu
trong PostgreSQL với placeholder allowlist; token bot, callback token và quyền workflow không nằm
trong template.

Các thay đổi mapping/mode/template được ghi vào `telegram_configuration_audits`. Callback Fix của
Admin vẫn dùng chat riêng hiện hành và các state/approval vẫn do API/PostgreSQL quyết định.

### Support duplicate-image comparison

`support_compare_image/dup-compare/local_worker.py` là process duy nhất sở hữu runtime Hugging
Face DINOv2. Nó chạy trên máy riêng của Support, kết nối PostgreSQL qua SSH tunnel/private VPN,
đọc job trong `support_compare_image.comparison_jobs`, lấy order `Waiting` chưa phân
loại từ `public.orders`, đọc baseline từ `image_embeddings` và ghi run/item/candidate vào cùng
schema. Model được cache trong process local giữa các job; production VPS không cài `torch`,
`transformers` hay tải checkpoint Hugging Face.

Job chỉ được tạo khi Support xác nhận: lệnh `/check` trên Telegram (hoặc nút **Kiểm tra trùng**
trên tab **Chưa kiểm tra**) đếm các order chưa từng được so sánh, hỏi **Có**/**Không**, rồi
enqueue tối đa một job active cho mỗi platform. Không còn job tự động theo lịch. Local worker
claim bằng `FOR UPDATE SKIP LOCKED`, embedding/compare tất cả order của lô với baseline Postgres
(các order trong cùng lô không so chéo với nhau), rồi thêm cả lô vào pool sau khi so xong và ghi
`completed` hoặc `failed`. Celery Beat trên VPS chỉ chạy notifier mỗi phút để báo cáo job và gửi
cặp ảnh Support đã chọn.

Kết quả từng order nằm ở `comparison_items.review_status`: `pending_review` (model nghi trùng),
`no_match` (không thấy trùng), rồi `selected_duplicate` hoặc `ai_wrong` sau khi Support duyệt trên
giao diện localhost của `dup-compare` (`/`, app React trong `review-ui/`). Giao diện này chỉ ghi vào schema
`support_compare_image`, không đổi order. Với `selected_duplicate`, notifier gửi cặp (ảnh gốc, ảnh
đã chọn, kèm mã đơn) qua Telegram; **Xác nhận** gọi `set_orders_duplicate_status` để gắn Trùng lặp,
**Từ chối** chuyển order sang Không trùng lặp. Các order `no_match`/`ai_wrong` vẫn nằm ở tab **Chưa
kiểm tra** cho tới khi Support gõ `/handle` để chuyển chúng sang Không trùng lặp.

Đơn đã sang `Doing` mà chưa phân loại được coi là **Không trùng lặp** trên giao diện Support (tab
Không trùng lặp, không còn ở Chưa kiểm tra) và không nằm trong `/check`, `/handle` hay job so sánh.

**Lấy đơn trùng lặp:** ở tab Trùng lặp, Support có nút **Lấy** (`POST /api/orders/support-take`) cho các
thẻ còn ở cột Đơn hàng của board (chưa có Designer nhận). Đơn được chia cho designer nội bộ
(`SUPPORT_TAKE_DESIGNER_USERNAME`, mặc định `des1`) bằng lệnh chia đơn thường (`queue_assignment_command`,
Printerval Doing), `work_domain` chuyển về `standard` nên rời board và đi theo luồng đơn thường, vẫn giữ
tag Trùng lặp. Khi hủy chia (`/assignments/revoke`), đơn có tag Trùng lặp quay lại cột Đơn hàng của board
(`work_domain=duplicate`, `IN_PROGRESS`) thay vì về Waiting.

Runner fail-closed với model: không dùng HOG fallback để so với baseline DINOv2. Hàng đợi là
PostgreSQL source of truth; Redis/Celery chỉ lo lịch tạo job và gửi Telegram, không chạy ML.

## Dữ liệu và side effect

| Lớp | Trách nhiệm |
| --- | --- |
| PostgreSQL | order state, assignment, result version, workflow event, operation, work note, finance và quyền truy cập |
| Redis/Celery | hàng đợi và schedule; không là source of truth |
| Printerval | hệ thống ngoài để crawl/đọc status và nhận external write có kiểm chứng |
| Support local worker | máy riêng giữ model DINO, claim `comparison_jobs`, tải preview và ghi kết quả; không phải production runtime |
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

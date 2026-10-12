# Claude Code Project Instructions — Tacahu Ops

> **Nguồn hiện hành:** [Tacahu Ops Core](docs/tacahu-ops-core/README.md) — kiến trúc,
> luồng đơn, quyền truy cập, data storage, API surface và vận hành production đều được
> mô tả chi tiết ở đó, cập nhật theo `main`. File này là **bối cảnh + rule làm việc** cho
> Claude khi sửa repo — không lặp lại toàn bộ core docs, chỉ tóm tắt và trỏ tới. Khi tài
> liệu này mâu thuẫn với core docs, route, migration hoặc test hiện hành thì **code/test
> luôn thắng**, không coi văn bản này là contract runtime.
>
> Đọc thêm theo mục đích: kiến trúc → `architecture.md`; dữ liệu ở đâu → `data-storage.md`;
> đơn đi qua state nào → `order-workflow.md`; quyền từng role → `access-and-privacy.md`;
> API đang dùng → `api-surface.md`; chạy/deploy → `operations.md`; spec/plan cũ còn áp
> dụng không → `archive.md`.

## 1. Sứ mệnh

Tacahu Ops là dashboard nội bộ quản lý design job outsource từ Printerval: crawl đơn,
phân loại (thường/trùng lặp), phân công designer, theo dõi tiến độ, nhận kết quả, xử lý
Fix, đồng bộ trạng thái, và trả tiền công — tất cả qua **một web dashboard** (React SPA +
FastAPI). Đây **không phải bản sao Printerval**: PostgreSQL là nguồn sự thật cho workflow
nội bộ; Printerval là external integration được crawl/đọc và ghi có kiểm chứng.

Telegram là **kênh phụ tùy cấu hình** (thông báo, một số callback thao tác nhanh cho Admin
và Support) — không phải authority quyết định state; mất Telegram không được làm mất
assignment, order state, approval hay payment state. Chi tiết boundary này xem
`architecture.md` → "Telegram management boundary".

Ưu tiên tuyệt đối khi sửa code ở repo này: **reliability, auditability, recoverability và
an toàn cho operator/tiền công designer** (nhiều thao tác ở đây ảnh hưởng trực tiếp tới
việc trả lương thật).

## 2. Bất biến bắt buộc

1. PostgreSQL là source of truth duy nhất cho state nội bộ và audit history.
2. Google Sheets là archive một chiều (export báo cáo), không phải nơi thao tác hay quyết
   định state. Google Drive link (kết quả designer nộp) là reference/metadata, không phải
   nơi lưu file bytes của hệ thống.
3. Printerval là external integration; mọi observation từ đó phải lưu lại và reconcile
   được, không tự tin dùng làm state nội bộ ngay lập tức.
4. Mọi command có side effect cần idempotency (`Operation`/idempotency key) và audit
   record (`WorkflowEvent`).
5. Chỉ application service/state machine được phép validate/đổi state; route handler, web
   UI và bất kỳ agent/LLM nào (nếu có) không write state trực tiếp.
6. Không giao task cho designer trước khi assignment có hiệu lực; không tự động quyết
   định QC.
7. Không overwrite lịch sử: append `WorkflowEvent`, dùng optimistic `version` cho
   order/assignment/result — conflict trả HTTP 409 kèm chi tiết revision, không ghi đè
   âm thầm.
8. Mọi input bên ngoài (web request, Telegram callback, Printerval, Sheet) là không đáng
   tin cậy — validate ở backend, không tin dữ liệu client gửi lên để quyết định quyền hay
   state.
9. Khi không chắc chắn cách xử lý một tình huống bất thường (external state lệch dự kiến,
   evidence không khớp 100%), đưa order vào `EXCEPTION` và để operator xử lý thủ công —
   không đoán cách recover.
10. LLM/agent (nếu có trong tương lai) không được điều khiển Playwright theo
    selector/tọa độ, không tự approve QC/assignment, không coi hội thoại là authorization.

## 3. Vai trò và quyền

5 role hiện có trong `users.role` (`app/domain/access.py`): `admin`, `support`,
`designer`, `designer-trello`, `accountant`. Mỗi user thuộc một `platform_id`; **mọi
query/command order phải scope theo platform** — không tin `X-Platform-Id` từ client cho
role không phải admin.

| Role | Phạm vi chính |
|---|---|
| `admin` | Toàn quyền theo platform: user, order, assignment, Fix, tài chính, Telegram config, audit. |
| `support` | Phân loại duplicate ở hàng chờ `Waiting`; xem read-only order `Doing`; duyệt bộ so ảnh trùng lặp (`/duplicate-review`, ẩn, có mật khẩu riêng); Support-lấy đơn trùng lặp cho `des1`. |
| `designer` | Chỉ thấy assignment standard của chính mình; không thấy `note_outsource`, audit history, URL platform nội bộ. |
| `designer-trello` | Làm việc trên domain trùng lặp (Duplicate Board) của platform đang active; không mở rộng sang domain standard. |
| `accountant` | **Chỉ** trả tiền công cho designer (trang `/payments`), xem QR ngân hàng và lịch sử thanh toán — bị chặn mặc định (deny-by-default ở `get_current_user`, xem `app/api/deps.py`) khỏi mọi route khác. Thêm route mới cho role này phải tự thêm vào allowlist, không tự động mở. |

Chi tiết đầy đủ (private data bị ẩn với từng role, ngoại lệ Duplicate Board, quyền Telegram
management...) xem `access-and-privacy.md`. Không suy diễn quyền từ UI ẩn — mọi enforcement
phải ở backend.

## 4. Kiến trúc và boundary

```text
React SPA (Vite+TS+Tailwind) ── /api ── FastAPI ── PostgreSQL (source of truth)
                                          │
                                          ├── Redis + Celery (queue/beat/worker)
                                          ├── Printerval HTTP API client, Playwright fallback
                                          ├── Google Sheets (export một chiều), Drive (link reference)
                                          └── Telegram (side channel tùy cấu hình)

Support duplicate-image agent (facebook/dinov2-base) chạy TRÊN MÁY SUPPORT, không phải VPS —
nói chuyện với API qua HTTPS bằng device token, không có quyền vào PostgreSQL.
```

- Application service (`app/application/`) + state machine (`app/domain/state_machine.py`)
  là nơi duy nhất validate/đổi state; route handler chỉ gọi qua đây.
- `app/domain/` không phụ thuộc FastAPI/SQLAlchemy/Playwright — giữ nguyên tắc này khi
  thêm code mới.
- Route ghi lên Printerval luôn qua adapter (`app/adapters/printerval/`), không gọi
  Playwright/HTTP trực tiếp từ route hay application service.

**Cấu trúc thư mục chính** (khớp repo hiện tại, không phải bản aspirational cũ):

```text
app/
  domain/        state machine, role/access constant, exception — không phụ thuộc framework
  application/   business logic (assignment, finance/payment, telegram_service, support_compare...)
  adapters/
    db/          SQLAlchemy model + Alembic migration
    printerval/  API client (đường chính) + Playwright adapter (fallback) cho Printerval
    google/      Sheets adapter (export một chiều), Drive adapter (đọc/validate link)
    allocation/  interface + bản tham chiếu FIFO — KHÔNG được wire vào production, xem §17
  workers/       Celery: crawl, status sync, assignment sync, Telegram, Sheet backup, support-compare
  api/routes/    FastAPI routers, mỗi domain nghiệp vụ một file (orders, finance, accountant,
                 telegram, support_worker, support_review, duplicate_board...)
frontend/        React SPA (Vite, TS, Tailwind 4, dnd-kit cho Duplicate Board)
migrations/      Alembic (root schema)
support_compare_image/  schema + migration RIÊNG cho subsystem so ảnh trùng lặp (Alembic riêng)
docs/tacahu-ops-core/   tài liệu hiện hành (đọc trước khi đoán kiến trúc)
tests/          pytest, DB-backed, chạy tuần tự trên `pinterval_test`
```

Không còn Jinja2/HTMX/Alpine — toàn bộ frontend là React SPA, FastAPI chỉ serve JSON API
(và `frontend/dist` khi có build production).

Stack: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16,
Redis + Celery, Playwright (fallback cho Printerval; Chrome thật, không headless — Cloudflare
chặn Chromium headless 403), Google Sheets/Drive API. Auth: bảng `users`
(5 role ở §3), token ký (`itsdangerous`) gửi qua `Authorization: Bearer` (localStorage ở
SPA) hoặc cookie `session` — cả hai đường đều được `get_current_user` chấp nhận.

Frontend: React 19 + TypeScript + Vite + Tailwind 4, gọi thẳng FastAPI JSON API; kéo-thả
dùng `@dnd-kit/core` (Duplicate Board). Business logic luôn ở backend — SPA chỉ trình bày.

## 5. State model

State canonical hiện tại (xem `app/domain/models.py::OrderState`) chỉ còn **8 giá trị**:
`OPEN`, `WAITING`, `IN_PROGRESS`, `QC_PENDING`, `REVISION`, `DONE`, `CANCELLED`,
`EXCEPTION`. Các tên state đời cũ/dài hơn (`DISCOVERED`, `CLAIMED_IMPORTED`, `ASSIGNED`,
`RESULT_SUBMITTED`, `FIX`, `SKIPPED`...) được `_missing_()` tự normalize về 8 giá trị này
khi đọc dữ liệu cũ — **không phải state canonical mới**, đừng thêm code so sánh trực tiếp
với tên cũ.

Sơ đồ transition đầy đủ và luồng nghiệp vụ (crawl → phân loại → làm việc → nộp bài → đồng
bộ status → Fix) nằm ở `order-workflow.md` — đọc file đó trước khi sửa transition, đừng
suy luận lại từ đầu. Nguyên tắc chung vẫn giữ:

- Transition tập trung trong `state_machine.py`, kiểm tra current state, evidence, actor
  role, `version` và idempotency key; ghi `WorkflowEvent` append-only cùng transaction.
- `EXCEPTION` chỉ rời bằng recovery tường minh của operator, application layer không tự
  động recover.

## 6. Mô hình dữ liệu

Repo đã lớn hơn nhiều so với thiết kế ban đầu — `app/adapters/db/models.py` hiện có hơn 30
bảng (order/assignment/result-version như thiết kế gốc, cộng thêm finance & payment
(`PaymentBatch`, `FinanceNote`), Telegram (`TelegramMessageTemplate`,
`TelegramActionLog`, `TelegramConfigurationAudit`...), support duplicate-image
(`SupportCompareRun/Job/Item/Candidate`, `SupportWorkerDevice`...), work note, bank QR,
sync job...). Đừng liệt kê lại toàn bộ ở đây — đọc `data-storage.md` để biết bảng nào
authoritative, dữ liệu nào nằm trên filesystem VPS (asset, Playwright evidence, bank QR
image) thay vì DB.

Nguyên tắc vẫn giữ khi thêm bảng/migration mới:

- Unique constraint theo external ID nguồn (Printerval order id...) và theo idempotency
  scope.
- Không dùng số dòng Google Sheet làm identity.
- Mọi schema change phải có Alembic migration — **root** (`migrations/`) và
  **support_compare_image** (`support_compare_image/migrations/`) là hai chain Alembic
  riêng biệt, kiểm tra đúng cái nào cần sửa.
- `WorkflowEvent`, `ResultVersion`, work note, finance note là append-only về nghiệp vụ.

## 7. Playwright — chỉ dùng làm fallback cho Printerval

Đường chính để nói chuyện với Printerval là `app/adapters/printerval/api_adapter.py`
(HTTP API client). Playwright (`playwright_adapter.py`) là **fallback** khi API không đủ
(ví dụ một số thao tác chỉ có trên UI) — không phải đường mặc định như thiết kế V1 gốc.

- Playwright là implementation detail trong adapter; không bao giờ là tool lộ ra
  cho route/LLM.
- Một adapter method làm đúng một business action, trả `success`, external
  id/status, evidence, error class và retryability.
- Dùng Chrome thật (`channel="chrome"`, không headless — Cloudflare chặn Chromium
  headless 403), explicit wait, retry/backoff có giới hạn, verify sau khi ghi.
- Lỗi thì lưu evidence đã redact (không log cookie/password); click có thể đã thành công
  nhưng chưa verify được → đặt `UNKNOWN_OUTCOME`, reconcile trước khi retry.
- Không dùng click tọa độ hay JS injection tùy tiện để "chữa cháy".

## 8. Google Sheets, Drive

- Sheet là **archive một chiều** (`app/workers/order_sheet_backup_tasks.py` +
  `order_sheet_backup_enabled`) — không đọc ngược lại Sheet để quyết định state. Idempotent
  bằng `exported_at`/operation marker.
- Drive link do designer tự dán khi nộp bài (`note_outsource`/`ResultVersion.drive_url`) —
  hệ thống chỉ validate URL hợp lệ, không tải/lưu file Drive về DB.
- Sửa tay trên Sheet archive không có quyền bypass state/approval.

## 9. Web dashboard, Telegram và approval

- Web dashboard là giao diện thao tác chính cho mọi role; business logic luôn ở backend.
- Auth: xem §4. Route phân theo role (`app/api/deps.py::require_role`,
  `require_any_role`, và allowlist riêng cho `accountant`).
- Approval action (assignment, QC, Fix) đi qua application service với `expected_version`;
  conflict trả 409 có chi tiết thay vì ghi đè.
- Nhiều admin cùng platform đều có quyền duyệt như nhau — không có single point of
  failure ở tầng quyền, nhưng đừng giả định thứ tự xử lý request đồng thời nếu chưa đọc
  code lock cụ thể (`with_for_update`) ở chỗ đó.
- **Telegram** là side channel tùy cấu hình cho thông báo và một số callback thao tác
  nhanh (Admin duyệt/từ chối Fix, Support chọn ảnh trùng...). Nó **không** phải nơi
  approval chính thức — callback vẫn gọi đúng application service như route web, ghi
  actor/version/audit giống hệt, không đặt quyền quyết định vào nội dung tin nhắn. Chi
  tiết resolver, template, audit ở `architecture.md` → "Telegram management boundary" và
  `access-and-privacy.md` → "Telegram Bot management".
- Tab "Trạng Thái Đơn" mirror `printerval_status` một chiều từ job nền (không ghi lên
  Printerval khi sync đọc); nút sửa Designer/trạng thái ở tab đó đi qua
  `PrintervalAssignmentRequest`/`create_request`/`execute_request`
  (`app/application/printerval_assignment_requests.py`) — cùng một đường ghi có audit với
  `OrdersListPage`, không phải một đường ghi song song, và không tự thay `Order.state` nội
  bộ.

## 10. Error handling, retry và reconciliation

Phân loại lỗi: `VALIDATION`, `AUTH`, `RATE_LIMIT`, `TRANSIENT_NETWORK`,
`EXTERNAL_CHANGED`, `UNKNOWN_OUTCOME`, `PERMANENT_EXTERNAL`, `BUG`.

- Chỉ retry loại retryable, backoff có giới hạn.
- Redis/Celery chỉ hỗ trợ queue/schedule; correctness luôn dựa vào DB
  constraint/transaction (`Operation`, `expected_version`).
- Hết retry đưa vào `DeadLetter` kèm recovery action cho operator.
- Printerval trả trạng thái ngoài dự kiến → `EXCEPTION`, không đoán cách map.
- `GET /api/orders/sync-status` chỉ đọc `PlatformSyncState`; watchdog Celery (mỗi phút)
  mới được đánh dấu job `failed` khi heartbeat quá hạn
  (`STATUS_SYNC_HEARTBEAT_STALE_SECONDS`, mặc định 180s) — polling UI không tự ý đổi
  `is_running`.

## 11. Nếu thêm LLM/agent (chưa có trong repo hiện tại)

Repo hiện **không có** LLM/agent nào gọi business tool (phần "MCP façade"/tool contract ở
thiết kế gốc chưa từng được implement — đừng giả định nó tồn tại). Nếu tương lai có nhu
cầu thêm, giữ các nguyên tắc an toàn sau, áp dụng cho bất kỳ cơ chế agent nào được thêm:

- Agent chỉ được gọi qua business tool hẹp, typed, validate bằng Pydantic — không truy
  cập Playwright/DOM/browser credential/raw DB write/shell/generic HTTP.
- Agent không được tự nghĩ state transition, bypass approval, coi prose là authorization,
  hay tự approve QC/assignment. Chat history không là record chính thức.
- **4 nhóm quyết định luôn phải dừng lại hỏi operator, không tự quyết** (không ngoại lệ):
  quyết định assignment (approve/cancel), quyết định QC (approve/edit/skip/cancel — áp
  dụng lại cho mọi result version mới, không tái dùng quyết định cũ), bất kỳ exception hay
  reconciliation mismatch nào không có evidence khớp 100%, và hủy đơn/assignment ngoài
  luồng approval có sẵn.
- Logic bên trong tool (chọn order cho designer nào...) vẫn phải deterministic theo bất
  biến #5 (§2), không phải LLM suy luận tự do.

## 12. Quy tắc code và test

- Python type hint đầy đủ, Pydantic model rõ, error type riêng.
- Giữ tách `domain/` không phụ thuộc FastAPI/Playwright/Sheet/LLM framework (xem §4).
- Function nhỏ, deterministic; inject interface, dùng fake adapter khi test.
- Mọi schema change có migration (nhớ 2 chain Alembic riêng, xem §6); không sửa DB
  production ad hoc.
- Không thêm dependency/framework mới nếu không phục vụ nhu cầu thật đang làm.
- Test tối thiểu cho thay đổi liên quan state/quyền/tiền: transition, permission,
  idempotency, optimistic-version conflict; test adapter qua fake, không gọi Printerval
  thật; E2E các case: duplicate request, order đã hoàn tất, link lỗi, stale
  QC/result-version, reconciliation mismatch.
- Chạy test: `export DATABASE_URL=postgresql+psycopg://hongphuc@localhost:5432/pinterval_test`
  rồi `.venv/bin/pytest -q tests` (DB-backed, **chạy tuần tự**, không parallel trên cùng
  `pinterval_test` — dễ deadlock/che lỗi concurrency). Full suite hiện ~470-490 test,
  mất khoảng 13-15 phút — chạy nền (`run_in_background`), đừng block chờ trong foreground.
  Frontend: `cd frontend && npx vitest run && npx tsc -b && npm run build`.
- `ruff check app tests migrations` trước khi commit — nhưng **không chạy `ruff --fix`**
  trên các file legacy trong `support_compare_image/` (đã có tiền lệ nó sửa lan sang file
  không liên quan).
- Không test bằng live customer data/credential mặc định; test phải deterministic.

## 13. Observability và security

- Structured log có `order_id`/`batch_id`/`assignment_id`/`operation_id`, state, adapter,
  outcome khi có thể.
- Secret chỉ qua environment injection đã duyệt; không commit `.env`, browser profile,
  token, cookie, hay export nhạy cảm. Không in secret ra chat/log.
- Redact mặc định, least-privilege cho DB/Google scope.
- Token phiên đăng nhập ký bằng `itsdangerous`, gửi qua `Authorization: Bearer` (SPA lưu ở
  localStorage) hoặc cookie `session` (httponly) — cả hai đường được chấp nhận, xem §4.
- Attachment private (work note, bank QR) lưu bytes ở filesystem private volume + metadata
  ở PostgreSQL, tải qua endpoint có authorization, không tạo URL public cố định — chi tiết
  ở `access-and-privacy.md`.

## 14. Vận hành production

- Production chạy trên VPS bằng Docker Compose (`compose.production.yaml`): API,
  migration, Redis, PostgreSQL, `celery-general`, `celery-assignment`, Celery Beat,
  Cloudflare Tunnel. **Không chạy Support duplicate-image agent (DINO) trong Compose
  production** — agent đó chạy trên máy của từng Support, chỉ nói HTTPS với API.
- Deploy tự động: push lên `main` → GitHub Actions (`.github/workflows/deploy-production.yml`)
  tự SSH vào VPS và deploy. **Không tự deploy tay sau khi push** — CI lo việc đó (mất
  khoảng 1-1.5 phút). Nếu build SPA mới cục bộ, deploy vẫn phải build lại trên VPS/CI,
  không giả định VPS đã có bundle mới chỉ vì local build pass.
- Backup PostgreSQL + toàn bộ private asset volume trước deploy/rollback ảnh hưởng dữ
  liệu; không `down -v` lên data production.
- Chi tiết đầy đủ (routing Telegram, migration head cho `support_compare_image`, kiểm tra
  tối thiểu trước bàn giao...) ở `operations.md` — đọc trước khi thao tác production thật,
  đừng đoán lại quy trình.

## 15. Thư mục `adapters/allocation/` — legacy, chưa wire

`app/adapters/allocation/` (interface + bản tham chiếu thuật toán FIFO/contiguous-block)
còn tồn tại trong repo nhưng **không được import ở bất kỳ đâu khác** — đây là code sót lại
từ thiết kế "designer tự offer số lượng" ban đầu, chưa từng được wire vào luồng phân công
thật. Luồng phân công hiện hành là Admin gán tay (standard) + Duplicate Board cộng tác
(duplicate domain) — xem `order-workflow.md`. Đừng giả định FIFO allocation đang chạy khi
đọc code hoặc trả lời câu hỏi về cách chia đơn.

## 16. Ghi chú khi sửa tài liệu

Khi thay đổi ảnh hưởng state, authorization, external write hoặc persistence, cập nhật
tài liệu `docs/tacahu-ops-core/*.md` tương ứng **trong cùng lúc** (quy ước đã ghi ở
`docs/tacahu-ops-core/README.md`) — đừng chỉ sửa code rồi để core docs lạc hậu.

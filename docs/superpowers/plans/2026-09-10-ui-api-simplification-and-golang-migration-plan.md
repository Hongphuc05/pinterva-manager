# Plan — Tinh gọn UI/API và chuyển backend sang Go/Gin

**Trạng thái:** Proposed — tài liệu này chưa bắt đầu thay đổi production hay xóa endpoint nào.

## Mục tiêu

Hệ thống hiện có 46 endpoint, nhiều trang cùng đọc và sửa một `Order`, đồng thời có
hai đường đi cho cùng một nghiệp vụ (sync status, assignment, browser login). Kế hoạch
này chia công việc thành hai phase tuần tự:

1. **Phase 1 — Chuẩn hóa trước khi chuyển nền tảng:** giảm UI/endpoint trùng lặp,
   chuẩn hóa job đồng bộ và khóa API contract. Backend vẫn là Python/FastAPI/Celery.
2. **Phase 2 — Chuyển backend sang Go/Gin:** port chính xác API contract đã được
   rút gọn, chạy song song với Python, đối soát rồi cutover.

Không rewrite Python và UI/API cùng lúc. Phase 1 tạo một contract nhỏ, ổn định để
Phase 2 chỉ port một API thay vì phải port cả legacy behavior.

## Ràng buộc toàn cục

- PostgreSQL vẫn là source of truth. Không tạo database song song, không thay đổi
  định danh `Order`, `Platform`, `Assignment`, `WorkflowEvent` hay lịch sử audit.
- Không để frontend, browser extension hoặc log nhận password Printerval, session
  cookie Printerval hay plaintext encryption key.
- `session_cookie` không được trả bởi `GET /platforms` sau Phase 1.
- Mọi external write tới Printerval vẫn tuân thủ `snapshot -> act -> verify ->
  restore -> verify restore` khi test thật. CI không gọi Printerval hay Google thật.
- Các write command phải idempotent theo `request_id`/idempotency key và giữ audit
  trail. Retry sau timeout phải được xem là `UNKNOWN_OUTCOME` cho tới khi reconcile.
- Một platform không được dùng dữ liệu, job hoặc credentials của platform khác.
- API mới phải có contract test trước khi frontend chuyển sang dùng. Endpoint cũ chỉ
  được xóa sau giai đoạn telemetry/deprecation đã định.
- Không thay đổi state machine chỉ để làm URL đẹp hơn.

## Hiện trạng và quyết định

### Endpoint legacy sẽ deprecate, không port sang Go

| Endpoint | Lý do |
| --- | --- |
| `GET /api/admin/ping` | Chỉ dùng test RBAC. Thay bằng test middleware/auth trực tiếp. |
| `GET /api/designer/ping` | Chỉ dùng test RBAC. |
| `POST /api/orders/{id}/assign` | Assignment đường cũ, không thấy frontend dùng. |
| `POST /api/orders/bulk-assign` | Assignment đường cũ, không thấy frontend dùng. |
| `/api/printerval-login/*` | Deprecate nếu cookie flow đủ thay browser-login flow. Chỉ xóa sau khi xác nhận vận hành. |

### Contract API đích

```text
/api/health

/api/auth/login
/api/auth/logout
/api/auth/me

/api/platforms
/api/platforms/{platformId}
/api/platforms/{platformId}/credentials
/api/platforms/{platformId}/printerval-options
/api/platforms/{platformId}/gallery-token

/api/users
/api/users/{userId}
/api/users/{userId}/password

/api/orders
/api/orders/{orderId}
/api/orders/{orderId}/events
/api/orders/{orderId}/refresh
/api/orders/{orderId}/transitions

/api/assignments
/api/assignments/{assignmentId}/start
/api/assignments/{assignmentId}/sub-status
/api/assignments/{assignmentId}/results
/api/tasks/me

/api/sync-jobs
/api/sync-jobs/{jobId}
/api/sync-jobs/current

/api/reports/workload
/api/reports/finance
/api/reports/order-history

/api/integrations/copyimage/gallery
```

`POST /orders/{id}/transitions` và `POST /assignments` là command endpoint có chủ
đích; không thay bằng `PATCH state` chung chung. Các endpoint password, result submit
và CopyImage vẫn tách riêng vì chúng có authorization/security contract khác nhau.

---

# Phase 1 — Tinh gọn UI, dữ liệu và API contract trên Python

## Kết quả cần đạt

- Admin sidebar còn bốn khu vực: **Đơn hàng**, **Tiến độ team**, **Báo cáo**,
  **Cài đặt**.
- `OrderStatusPage` không còn là một danh sách order độc lập; nó trở thành mode/tab
  trong Orders.
- Một sync request ở bất cứ UI nào tạo một `SyncJob` thống nhất, có progress và kết
  quả có thể đọc lại.
- Single và bulk assignment dùng chung một contract.
- State transition dùng action rõ nghĩa và audit được.
- Frontend dùng query cache chung, không blank dữ liệu cũ khi đang refetch.
- API legacy được đo usage, không bị xóa mù.

## Information architecture đích

```text
Vận hành
  - Đơn hàng
  - Tiến độ team

Báo cáo
  - Tài chính & công lao
  - Lịch sử tiến độ

Cài đặt
  - Tài khoản người dùng
  - Acc Mẹ Printerval (modal/settings, không là page sidebar)
```

`Orders` có hai mode:

```text
[Danh sách] [Đồng bộ Printerval]
```

- **Danh sách:** thao tác hàng ngày, assign, filter, mở detail.
- **Đồng bộ Printerval:** status nội bộ/external, last sync, lỗi, sync tab hiện tại.

Order detail là nguồn duy nhất cho dữ liệu sâu:

```text
[Tổng quan] [SKU] [Gallery] [Source] [Custom] [Lịch sử]
```

## Task 1.1 — Lập API inventory và telemetry deprecation

**Files:** `docs/api-contract-v1.md` (new), `app/api/main.py`, middleware/logging
module mới nếu cần.

**Consumes:** danh sách endpoint hiện tại, frontend API calls, CopyImage bridge calls.

**Produces:**

- inventory có method, request/response schema, role, platform scope, consumer;
- header/metric `X-Deprecated-Endpoint: true` cho endpoint cũ;
- structured log cho endpoint deprecated gồm route, actor role, platform ID, request
  ID; tuyệt đối không log body credentials/cookie.

**Acceptance:** sau một release vận hành, có số liệu xác nhận endpoint legacy không còn
consumer trước khi xóa.

## Task 1.2 — Bảo mật platform response và credential flow

**Files:** `app/api/routes/platforms_api.py`, `app/api/routes/orders_api.py`,
`frontend/src/components/PrintervalSettingsModal.tsx`, type frontend liên quan.

**Consumes:** platform ID trong `X-Platform-Id`, credential modal hiện tại.

**Produces:**

- `GET /platforms` trả `id`, name, account username, team, active, verification
  summary; không trả password/session cookie/token bridge;
- `PATCH /platforms/{id}/credentials` verify credentials + team trước khi save;
- `GET /platforms/{id}/printerval-options` đọc cache options theo platform;
- `POST /platforms/{id}/gallery-token` rotate token, trả plaintext đúng một lần;
- migration frontend khỏi `POST /orders/printerval-credentials`.

**Acceptance:** DevTools Network không có session cookie Printerval trong response JSON;
credential save thành công xóa trạng thái lỗi sync cũ của đúng platform.

## Task 1.3 — Xóa page navigation dư thừa

**Files:** `frontend/src/components/Sidebar.tsx`, `frontend/src/App.tsx`,
`frontend/src/pages/PrintervalLoginPage.tsx`, `frontend/src/pages/MyTasksPage.tsx`.

**Consumes:** cookie settings modal, role-based route guard.

**Produces:**

- sidebar theo information architecture đích;
- route `/printerval-login` chỉ redirect hoặc 404 sau deprecation; không còn sidebar
  item;
- xác nhận `MyTasksPage` không còn consumer trước khi xóa; Designer luôn vào orders
  scope riêng hoặc `/tasks/me` khi page đó được tái sử dụng;
- các redirect legacy `/allocation`, `/kanban`, `/my-tasks` được giữ một release,
  sau đó xóa cùng telemetry.

**Acceptance:** Admin thấy tối đa sáu nav item gồm section header; Designer chỉ thấy
task, lịch sử và tài chính cá nhân; không có link chết.

## Task 1.4 — Hợp nhất Order Status vào Orders

**Files:** `frontend/src/pages/OrdersListPage.tsx`, `frontend/src/pages/OrderStatusPage.tsx`,
route và tests liên quan.

**Consumes:** `GET /orders`, platform filter, sync job API của Task 1.5.

**Produces:**

- tab/mode `list` và `sync` trong Orders;
- URL query giữ mode/filter/page, ví dụ `/orders?view=sync&state=WAITING&page=2`;
- `OrderStatusPage` redirect về `Orders?view=sync` trong một release rồi xóa;
- một `OrderTable` shared hoặc shared query mapper, không copy request/filter state.

**Acceptance:** chuyển tab không reset filter/platform; refresh browser khôi phục view
và danh sách gần nhất; status editing vẫn phải authorization đúng role.

## Task 1.5 — Chuẩn hóa Sync Job

**Files:** migration mới, `app/adapters/db/models.py`, `app/application/sync_jobs.py`
(new), Celery task files, orders routes, `frontend/src/hooks/useSyncJob.ts` (new).

**Consumes:** Redis/Celery, platform credentials server-side, current selected order IDs,
`PRINTERVAL_MANUAL_SYNC_CONCURRENCY`.

**Produces:**

```text
POST /api/sync-jobs
GET  /api/sync-jobs/{jobId}
GET  /api/sync-jobs/current
```

`POST /sync-jobs` accepts `type`, `scope`, `order_ids`, optional filter snapshot. The
worker records `queued/running/succeeded/failed/cancelled`, processed, total, updated,
failed count, timestamps and a redacted error summary.

**Rules:**

- Unique active job per `{platform_id, type, scope fingerprint}`.
- UI receives existing active job instead of creating duplicate sync work.
- Per-platform concurrency remains limited; no unbounded goroutine/task burst.
- `reset` becomes an audited admin action only if an old active lease genuinely expired;
  it is not a public button in normal UI.

**Acceptance:** Topbar, Orders list, Orders sync mode and Designer Board all render the
same job ID/progress. Repeated click does not enqueue duplicate status sync.

## Task 1.6 — Hợp nhất assignment single/bulk

**Files:** `app/api/routes/orders_api.py` or new `assignments_api.py`,
`app/application/printerval_assignment_requests.py`, frontend assignment modal/tests.

**Consumes:** `order_ids[]`, internal designer ID, exact external Designer option,
external status, active platform ID.

**Produces:**

```http
POST /api/assignments
```

Payload always uses `order_ids`, including one order. Backend validates all orders belong
to active platform before any request is persisted. Response returns a request/job summary
per order, not only a global success count.

**Acceptance:** single and bulk UI use one mutation function; one failed Printerval order
does not hide successful results of other orders; request audit remains per-order.

## Task 1.7 — Chuẩn hóa state transition command

**Files:** `app/application/order_transitions.py`, `app/api/routes/orders_api.py` or
new `transitions_api.py`, `frontend/src/components/AdminFixActionModal.tsx`, order detail,
Designer Board, tests.

**Consumes:** order ID, actor, `action`, note/drive URL, `request_id`.

**Produces:**

```http
POST /api/orders/{orderId}/transitions
```

Allowed actions:

```text
start
submit_review
request_fix
approve_fix
return_to_review
approve_done
set_waiting
```

The endpoint maps action to state-machine transition, role authorization, workflow event,
Printerval side effect and idempotency record. Client cannot submit arbitrary target state.

**Acceptance:** old `PATCH state`, `approve-fix`, `reject-fix-to-review` are no longer
called by frontend; prohibited transition returns a stable typed error; every accepted
transition creates exactly one audit event.

## Task 1.8 — Query cache và dữ liệu không nhấp nháy

**Files:** `frontend/src/api/client.ts`, new query provider/hooks, all pages using
`apiFetch`, frontend tests.

**Consumes:** API contract, active platform ID, URL filters.

**Produces:**

- TanStack Query hoặc SWR dùng chung với query keys theo platform + filter + page;
- stale-while-revalidate: giữ bảng cũ khi fetch mới;
- persist ngắn hạn bằng `sessionStorage`, không persist cookie/token/credentials;
- invalidate đúng query sau assignment, transition, refresh detail và gallery import;
- one shared error/loading model.

**Acceptance:** F5 không vẽ empty-state trước khi response trả về nếu cache còn hợp lệ;
không có nhiều request `/orders` trùng nhau từ cùng màn hình.

## Task 1.9 — Rút gọn interaction và visual hierarchy

**Files:** Orders page, Topbar, Designer Board, order detail components, style tests.

**Produces:**

- một primary action mỗi page;
- Topbar chỉ: platform selector, quét đơn mới, sync progress, user menu;
- action phụ của order nằm trong menu `...`;
- filter cơ bản: search, status, designer, date; filter nâng cao nằm trong popover;
- order list chỉ hiển thị summary; gallery/source/SKU/custom/history ở detail tab;
- Lucide line icons cho action, bỏ icon màu/emoji trang trí.

**Acceptance:** table ở desktop hiển thị không quá các cột: thumbnail, order, status,
designer, SKU/source count, deadline, updated/sync, actions. Không có secondary action
button lặp lại trên từng row.

## Task 1.10 — Contract tests, rollout và xóa legacy

**Files:** API tests, frontend tests, docs API contract, release notes.

**Steps:**

1. Chạy API cũ/v2 song song trên Python.
2. Chuyển frontend từng domain: platform -> sync -> assignment -> transition.
3. Theo dõi deprecated endpoint tối thiểu một release.
4. Xóa route, tests, UI page và worker code legacy khi usage bằng zero.
5. Cập nhật `RUNME.md` và vận hành docs.

**Phase 1 exit criteria:**

- Không còn `/assign`, `/bulk-assign`, `sync-status/run`, `sync-status/reset` và state
  mutation cũ được frontend gọi.
- Credentials không lộ qua API list platform.
- Một source of truth cho sync progress.
- Tests backend/frontend pass; manual smoke test với local DB và fake Printerval adapter.

**Ước lượng:** 2–4 tuần cho một người, tùy mức refactor component và mức coverage test.

---

# Phase 2 — Chuyển backend sang Go/Gin

## Mục tiêu

Port **contract đã được chốt ở Phase 1**, không port endpoint legacy. Go API và Go worker
chạy song song Python trong giai đoạn kiểm chứng, dùng cùng PostgreSQL và Redis nhưng chỉ
một implementation được phép ghi cho từng command tại một thời điểm.

## Kiến trúc đích

```text
React/Vite/Vercel
        |
        v
Gin API
  |- PostgreSQL: pgx + sqlc
  |- Redis: queue/cache
  |- Go worker: sync/crawl/assignment scheduler
  |- Printerval HTTP client
  |- CopyImage gallery bridge
  `- browser automation service (chuyển sau cùng nếu vẫn cần)
```

### Go packages đề xuất

| Nhu cầu | Hướng chọn |
| --- | --- |
| HTTP | Gin, middleware tự viết nhỏ và rõ ràng |
| Validation | struct tags + validator rõ lỗi response |
| PostgreSQL | `pgxpool` + `sqlc` |
| Database migration | migration tool Go riêng, ledger riêng; không ghi đè `alembic_version` |
| Queue/scheduler | Redis-backed queue có retry/scheduling; interface nội bộ để không khóa vendor |
| Auth | session/token mới do Go ký; bcrypt hash giữ tương thích |
| Metrics/logging | structured JSON log, request/job ID, Prometheus/OpenTelemetry nếu cần |

## Task 2.1 — Baseline, worktree và compatibility harness

**Files:** new `backend-go/`, `docs/api-contract-v1.md`, fixtures sanitized, CI workflow.

**Consumes:** Phase 1 API contract, sanitized response fixtures, PostgreSQL schema.

**Produces:**

- Go module, pinned Go toolchain version, lint/test/build targets;
- Docker image chạy API ở port riêng, ví dụ `8080`;
- contract harness gửi cùng request vào Python và Go read endpoint, chuẩn hóa field
  volatile rồi so sánh response;
- no production traffic, no database write từ Go ở task này.

**Acceptance:** `go test ./...`, build container và contract read smoke test pass trên
local PostgreSQL snapshot.

## Task 2.2 — Config, health, logging và store layer

**Files:** `backend-go/cmd/api`, `internal/config`, `internal/http`, `internal/store`.

**Consumes:** environment variables hiện hữu: DB, Redis, secret, CORS, asset path.

**Produces:**

- fail-fast config validation;
- health/readiness endpoint phân biệt DB/Redis unavailable;
- pgx connection pool;
- sqlc queries read-only cho platform, order list/detail, history;
- request ID propagated to logs and jobs.

**Acceptance:** API không start nếu production secret/default config sai; healthcheck
không tiết lộ secret; query luôn scope theo active platform.

## Task 2.3 — Port read API trước

**Order thực hiện:**

1. `/health`
2. `/auth/me` read side sau auth bridge tạm
3. `/platforms` redacted response
4. `/orders`, `/orders/{id}`, `/orders/{id}/events`
5. `/tasks/me`
6. report workload, finance, order history
7. sync job read endpoints

**Produces:** Gin response contract byte-level/semantic compatible theo fixtures.

**Acceptance:** frontend development có thể trỏ read-only traffic sang Go mà không có
khác biệt hiển thị; authorization leak test pass.

## Task 2.4 — Auth và migration credential encryption

**Files:** `internal/auth`, one-off Python migration utility, Go migration, security tests.

**Decisions:**

- bcrypt password hash giữ nguyên;
- Go phát session/token mới; tại final cutover bắt buộc login lại, không cố parse
  Python `itsdangerous` token lâu dài;
- `password_ciphertext` Python/Fernet được decrypt bằng one-off tool, re-encrypt sang
  AES-256-GCM hoặc envelope encryption có Go implementation;
- migration idempotent, backup encrypted trước và sau migration;
- password reveal là admin-only, audit event bắt buộc, response `no-store`.

**Acceptance:** Go verify được bcrypt user cũ; migration rollback/read compatibility đã
được test trên snapshot; plaintext password không xuất hiện trong DB/log/test fixture.

## Task 2.5 — Port write API và state machine

**Order thực hiện:**

1. User management.
2. Platform credential update/verification.
3. `POST /assignments`.
4. `POST /orders/{id}/transitions`.
5. Designer task start/substatus/result.
6. CopyImage gallery bridge.

**Rules:** mỗi command dùng database transaction, row lock khi cần, idempotency table
và audit event trong cùng transaction trước khi enqueue external work.

**Acceptance:** state machine test suite chạy cùng assertions trên Python và Go;
repeat request với cùng request ID không tạo duplicate assignment/result/history.

## Task 2.6 — Port worker, scheduler và Printerval HTTP adapter

**Consumes:** job table Phase 1, Redis, Printerval adapter contract, rate/concurrency
settings per platform.

**Produces:**

- Go worker queues: general sync/crawl, serialized external write queue, scheduler;
- exponential retry cho network/transient error; `UNKNOWN_OUTCOME` với external write
  timeout;
- per-platform limiter and lock;
- read-after-write verification for external assignment/status changes;
- queue/job metrics and redacted evidence.

**Acceptance:** mỗi job Phase 1 có Go equivalent; worker restart không mất active job;
retry không tạo external write trùng.

## Task 2.7 — Browser automation boundary

**Decision gate:** chỉ làm sau khi HTTP crawler, cookie flow và CopyImage đã ổn định.

**Options:**

1. Port browser adapter sang Go/chromedp.
2. Giữ Python browser worker như một service độc lập sau Go API cutover.
3. Bỏ browser automation nếu cookie + HTTP + CopyImage đã phủ đủ use case.

Không được nhét Chromium vào Gin API process. Browser automation chạy service/worker
riêng, có profile/evidence volume và retry boundary độc lập.

**Acceptance:** quyết định có evidence từ traffic/feature inventory; không port browser
automation chỉ vì mục tiêu “100% Go” khi nó chưa mang giá trị vận hành.

## Task 2.8 — Shadow traffic và cutover

**Steps:**

1. Go read API shadow cùng PostgreSQL, chỉ compare response/log.
2. Canary một admin/local environment sang Go; Python vẫn là writer.
3. Backup PostgreSQL, Redis state và deployment manifest.
4. Drain Celery queues; chặn Python nhận command mới.
5. Chuyển API/worker writer sang Go.
6. Force logout để session Go có hiệu lực đồng nhất.
7. Theo dõi order count, assignment count, workflow event count, gallery count,
   sync latency, queue failure rate.
8. Giữ Python read-only rollback window tối thiểu một chu kỳ vận hành.

**Rollback:** route frontend/API gateway quay về Python; Go worker dừng trước khi
rollback để tránh dual writer. Không rollback bằng cách restore database nếu không có
đối soát tác động ngoài Printerval.

## Phase 2 exit criteria

- Go xử lý toàn bộ API contract Phase 1, trừ browser automation đã được quyết định rõ.
- Không có dual writer trên cùng command/queue.
- Contract, integration, authorization, idempotency và worker-retry tests pass.
- Một tuần vận hành không có mismatch dữ liệu/audit giữa Go và PostgreSQL.
- Python routes/workers chỉ được gỡ sau khi rollback window kết thúc.

**Ước lượng:** 8–12 tuần cho một người làm full-time. Nếu browser automation cần port
hoàn toàn sang Go, thêm 2–3 tuần xác minh site thật có kiểm soát.

## Không nằm trong hai phase này

- Chuyển frontend React sang framework khác.
- Tự động hóa ghi dữ liệu thật lên Printerval không có verify/reconcile.
- Đưa PostgreSQL public Internet.
- Scale nhiều VPS/Kubernetes. Single VPS Docker Compose vẫn là mục tiêu triển khai đầu
tiên; chỉ tách service khi telemetry cho thấy cần thiết.

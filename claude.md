# Claude Code Project Instructions — Web Dashboard Vận Hành V1

## 1. Sứ mệnh

Implement **V1** cho hệ thống vận hành nội bộ xử lý order ảnh/sản phẩm: nhận đơn, chia
designer, duyệt phân đơn, theo dõi tiến độ, thu kết quả, QC bởi con người — tất cả qua
**một web dashboard nội bộ** (admin + designer), không qua Telegram.

Ưu tiên tuyệt đối: **reliability, auditability, recoverability và an toàn cho operator**.
Web dashboard là giao diện chính; MCP/adapter là lớp tích hợp với hệ thống ngoài
(Printerval, Google Sheets, Google Drive). LLM (nếu có, V2 trở đi) chỉ là lớp hỗ trợ,
không phải nơi quyết định workflow.

> Xem `docs/superpowers/specs/2026-09-06-web-dashboard-design.md` để có đầy đủ bối cảnh
> quyết định kiến trúc và các lựa chọn đã cân nhắc.

## 2. Bất biến bắt buộc

1. PostgreSQL là source of truth duy nhất cho state nội bộ và audit history.
2. Google Sheets là archive một chiều (xuất báo cáo/lưu trữ), không phải nơi thao tác hay
   database quyết định.
3. Website Printerval là external integration; phải lưu external observation và
   reconcile.
4. Mọi command có side effect cần idempotency key và operation/audit record.
5. Chỉ state machine được phép validate/đổi state; web UI, adapter và LLM (nếu có) không
   write state trực tiếp — mọi thao tác trên web đều đi qua application service/state
   machine như bất kỳ client nào khác.
6. LLM (nếu có) không được điều khiển Playwright theo selector/element/tọa độ.
7. Không giao task cho designer trước assignment approval; không tự động quyết định QC
   trong V1.
8. Không overwrite lịch sử: append event, version assignment/result.
9. Mọi input bên ngoài (web request, Sheet, website Printerval, LLM output nếu có) là
   không đáng tin cậy.
10. Khi không chắc chắn, đưa vào exception queue thay vì đoán cách recover.

## 3. Workflow V1 phải triển khai

> **Ghi chú thuật ngữ:** Printerval là **một website duy nhất** — nơi khách giao batch
> đơn (status `waiting`, chưa có designer), và cũng chính nơi đó đơn đi hết
> `waiting → doing → review → done`. Chỉ có 1 adapter website, không có 2 adapter riêng.
> Telegram **không còn** trong kiến trúc V1 (có thể thêm lại ở V2 như kênh thông báo phụ,
> xem §10).

### C1 — Crawl & claim (thay B1+B2 cũ)

Job nền định kỳ quét đơn `waiting` (mặc định **tất cả loại job** — "Tất cả 2D&3D",
scoped theo tài khoản công ty) trên Printerval, tự động đổi designer sang `ntth` để
claim, tải asset, xác minh từng write, rồi lưu thẳng vào Postgres (không qua Sheet
intake). Loại job (2D/3D/ART/WOOD/CALENDAR/EMBROIDERY/AI) chỉ là phân loại hiển thị,
không phải rào cản nghiệp vụ — filter theo loại cụ thể là tuỳ chọn trên web (bổ sung
UI chọn sau nếu cần), không hard-code cứng như bản nháp đầu. Không đổi internal state
thành `CLAIMED_IMPORTED` nếu asset chưa xác minh. Đơn mới hiện ngay trên web dashboard
cho admin xem.

### C2 — Phân bổ đơn (thay B3 cũ)

Hai lối vào cùng một bộ máy phân bổ deterministic:

- **Designer tự "offer"** số lượng muốn nhận ngay trên web (thay đăng ký Telegram).
- **Admin gán tay** cho trường hợp đặc biệt.

**Thuật toán chia (V1, đã chốt, không đổi so với bản gốc):** FIFO theo thứ tự đăng ký,
khối liền kề (contiguous block) trên danh sách order còn lại của batch. Người offer trước
nhận khối trước; nếu số lượng còn lại không đủ, người offer sau chỉ nhận phần còn lại
(không round-robin, không chia lại của người trước). Không có ưu tiên theo skill/độ khó
trong V1. Vì nhiều designer có thể bấm offer gần như đồng thời, việc "giữ chỗ" khối order
phải là một transaction DB tuần tự hóa theo thứ tự request đến, dùng lock/
`SELECT … FOR UPDATE` trên order còn `unassigned` của batch — không được có 2 designer
cùng giữ chung 1 order.

**Ghi chú quan trọng:** có một tool phân bổ FIFO/contiguous-block khác đã chạy ổn định ở
nơi khác (ngoài repo này). V1 **không viết lại tool đó cho production** — chỉ viết một bản
tham chiếu đúng thuật toán trên để test, đặt sau một interface/adapter riêng để sau này cắm
tool thật vào mà không phải sửa domain.

### C3 — Admin approval assignment (thay B4 cũ)

Với từng assignment draft: truy xuất Printerval để lấy/check thông tin đơn (tên, ảnh, mẫu,
màu) cùng designer; hiện card trên web cho admin **Approve** hoặc **Cancel**.

Cancel nghĩa là đơn đã làm/không hợp lệ. Lưu lý do và bằng chứng, release order, trả quota
còn thiếu của designer, quay lại C2 để chọn đơn bù. Tuyệt đối không thay đơn âm thầm.

### C4 — Designer làm việc & nộp kết quả (thay B5 cũ)

Designer thấy task được giao thẳng trên web (không qua Sheet dispatch). Tự cập nhật
sub-status làm việc (`đang làm` / `đang sửa` / `đã xong`) — chỉ để hiển thị tiến độ, không
phải input cho state machine chính. Khi xong, dán link Drive + bấm "Nộp" trên web → tạo
`result_version` mới, vào hàng chờ QC nội bộ. **Chưa đụng gì tới Printerval ở bước này.**

### C5 — QC bởi con người và vòng sửa (thay B6+B7 cũ, đã đảo thứ tự)

Admin xem order ở hàng chờ QC kèm context/result link trên web, bắt buộc chọn:

- **Approve:** ghi nhận duyệt. Job nền tự động chạy Playwright gắn link Drive lên
  Printerval (placeholder của đơn) và verify chuyển `doing → review` (hoặc trạng thái đích
  phù hợp — xem mục 17 nợ kỹ thuật #6 về `Fix`/`Confirm`). Chỉ sau khi verify thành công
  mới coi đơn `DONE`.
- **Edit:** bắt buộc có feedback; gửi designer sửa. **Không đụng Printerval.**
- **Skip:** Printerval tạm xử lý và dự kiến tự đổi trạng thái; lên lịch reconcile. Không
  đụng Printerval từ phía mình.
- **Cancel + Reply:** hủy có lý do và gửi/lưu phản hồi. Không đụng Printerval.

Khi designer gửi result đã sửa, kiểm tra có result version mới, tạo QC approval request
mới. Không dùng quyết định QC cũ cho result version mới.

**Lý do đảo thứ tự so với bản gốc:** QC nội bộ xảy ra **trước** khi submit lên Printerval,
nên Edit/Skip/Cancel không bao giờ phải "gắn rồi gỡ" trên site khách — chỉ có kết quả đã
Approve mới bao giờ chạm tới Printerval.

## 4. Kiến trúc và boundary

```text
                 ┌─────────────────────────────┐      ┌─────────────────────┐
                 │  FastAPI JSON API (backend)  │◄─────┤  React SPA (Vite)   │
                 │  role: admin | designer      │      │  TypeScript+Tailwind│
                 └───────────────┬─────────────┘      └─────────────────────┘
                                 │
                 Application service + state machine (domain/)
                                 │
                 ┌───────────────┼─────────────────┐
                 ▼               ▼                 ▼
           PostgreSQL      Redis + Celery     Business tools
        (source of truth)  (background jobs)   (MCP façade)
                                 │                 │
                    ┌────────────┼───────┐         │
                    ▼            ▼       ▼         ▼
              Crawl job    Submit job  Sheet export  Playwright adapter
          (đơn mới, mọi loại)(link→site)  (archive)    → Printerval (1 site)
```

- Web dashboard là **giao diện duy nhất** cho admin và designer trong V1. Không có
  Telegram adapter.
- Application service + state machine là nơi duy nhất validate/đổi state; web dashboard
  chỉ gọi qua đây, không tự ý update DB.
- Business tools/MCP façade expose tool hẹp, typed, không lộ Playwright primitive.
- Optional local LLM agent (nếu làm ở V2) chỉ gọi business tool được whitelist, ngồi trên
  cùng lớp MCP façade — không có quyền gì hơn web dashboard.

Stack backend: Python 3.12, FastAPI (JSON API thuần), Pydantic v2, SQLAlchemy 2, Alembic,
PostgreSQL 16, Redis + Celery/Dramatiq, **Playwright** (không dùng Selenium — đã xác nhận
Playwright + Chrome thật vượt được chặn Cloudflare của Printerval, Chromium headless bị
chặn 403), Google Sheets/Drive API. Auth: bảng `users` (role `admin`/`designer`, password
hash), session cookie (httponly, same-origin, SPA build được FastAPI serve như static —
không đổi sang JWT/OAuth) — không OAuth trong V1.

Stack frontend: **React + TypeScript + Vite + Tailwind CSS** (quyết định lại 2026-09-07,
thay cho Jinja2+HTMX+Alpine của Phase 4 — xem
`docs/superpowers/specs/2026-09-07-frontend-platform-migration-design.md`). SPA gọi thẳng
FastAPI JSON API; kéo-thả dùng `dnd-kit`. Business logic vẫn luôn nằm ở backend
(application service/state machine) — SPA chỉ là lớp trình bày/tương tác, không tự
validate/đổi state.

Correctness của hệ thống không được phụ thuộc LLM (áp dụng nếu/khi thêm agent ở V2).

## 5. State model

Luồng chính (rút gọn so với bản gốc — không còn `IMPORTED` riêng, không còn
`DISPATCHED`/`SUBMITTED_FOR_REVIEW` là bước tách biệt trước QC):

`DISCOVERED → CLAIMED_IMPORTED → OPEN_FOR_ALLOCATION → ASSIGNMENT_PENDING_APPROVAL → ASSIGNED → IN_PROGRESS → RESULT_SUBMITTED → QC_PENDING → SUBMITTING_TO_SITE → DONE`

Nhánh thay thế:

- `ASSIGNMENT_PENDING_APPROVAL → OPEN_FOR_ALLOCATION`: admin cancel do đơn không hợp
  lệ/đã làm (C3).
- `IN_PROGRESS → REASSIGNMENT_REQUIRED`: designer không thể thực hiện; cần recovery rõ
  ràng. SLA im lặng để đề xuất trạng thái này **chưa chốt — nợ kỹ thuật**: tạm dùng công
  thức tuyến tính theo quantity của assignment (mặc định 10 order ≈ 1 giờ, scale theo số
  lượng); công thức này chỉ tạo cảnh báo cho operator, không tự chuyển state — quyết định
  chuyển vẫn qua exception queue (12.1, nhóm 3).
- `QC_PENDING → REVISION_REQUESTED → IN_PROGRESS`: QC chọn **Edit**.
- `QC_PENDING → SKIPPED`: QC chọn **Skip**, sau đó reconcile.
- `QC_PENDING → CANCELLED`: QC chọn **Cancel + Reply**.
- Bất kỳ state nào cũng có thể vào `EXCEPTION` kèm error class và recovery owner; chỉ
  explicit command mới được ra khỏi state này.

Đặt transition trong một module/policy table duy nhất. Mỗi transition phải kiểm tra
current state, external evidence bắt buộc, actor/role, result version (nếu có) và
idempotency key. Ghi `workflow_event` append-only trong cùng transaction.

## 6. Yêu cầu mô hình dữ liệu

Tối thiểu phải có migration cho:

- `orders`: UUID nội bộ, external order IDs bất biến, state hiện tại, external
  observation, batch ID, timestamp, optimistic version.
- `order_assets`: source image ref, checksum, vị trí download/upload.
- `batches`: source/filter, owner, count, lifecycle.
- `users`: tên chuẩn hóa, role (`admin`/`designer`), password hash, active/capacity —
  thay cho `designers` cũ, không còn cột Telegram ID.
- `assignments`: order, designer (user), trạng thái, thời gian, lý do cancel và liên kết
  replacement; thêm sub-status làm việc (`doing`/`fixing`/`done`) chỉ để hiển thị tiến độ.
- `result_versions`: assignment, Drive link, checksum/version marker, validation,
  submitted time.
- `approval_requests`, `approval_decisions`: loại, target version, actor được phép,
  expiry, decision/comment, **web request/session ref** (thay Telegram message ref).
- `external_refs` / `external_observations`: ID web Printerval, sheet ID + row key ổn
  định, observed state/evidence/time.
- `operations`: idempotency key, command, request fingerprint, status, evidence, retry
  count.
- `workflow_events`, `outbox`, `dead_letters`.

Tạo unique constraint theo external ID nguồn và idempotency scope. Không dùng số dòng
Sheet làm identity; có cột UUID cố định ẩn/protected. Sheet export dùng `exported_at`/
operation marker để tránh xuất trùng (không cần `external_sync_version` 2 chiều vì Sheet
giờ chỉ 1 chiều).

## 7. Business tool contracts

Expose tool hẹp, typed và validate bằng Pydantic. Trả JSON có cấu trúc. Không expose
Playwright primitive. Các tool này được gọi từ web dashboard (qua application service),
không phải từ Telegram callback.

```text
discover_waiting_orders(source, limit) -> {orders, cursor}
claim_batch(order_ids, owner="ntth", idempotency_key) -> BatchResult
import_claimed_batch(batch_id, idempotency_key) -> BatchResult
open_allocation(batch_id, idempotency_key) -> AllocationOpenResult
request_quantity(designer_id, batch_id, quantity, idempotency_key) -> AllocationDraft
create_assignment_draft(order_id, designer_id, idempotency_key) -> Assignment
validate_assignment(assignment_id, idempotency_key) -> ValidationResult
create_assignment_approval(assignment_id, idempotency_key) -> ApprovalRequest
decide_assignment(approval_id, decision, actor_id, idempotency_key) -> AssignmentResult
record_result(order_id, drive_url, source_version, idempotency_key) -> ResultVersion
create_qc_request(order_id, result_version_id, idempotency_key) -> ApprovalRequest
decide_qc(approval_id, decision, actor_id, comment, idempotency_key) -> QCResult
submit_approved_result_to_site(order_id, result_version_id, idempotency_key) -> SubmissionResult
reconcile_order(order_id, idempotency_key) -> ReconciliationResult
```

Write tool luôn cần authorization, state check, idempotency và observability. Approval
tool phải validate request (session/CSRF trên web), role, expiry, target state và result
version.

## 8. Playwright execution rules

- Playwright là implementation detail trong adapter; không bao giờ là MCP/LLM tool.
- Một adapter method làm đúng một business action, trả `success`, external IDs/status,
  evidence, error class và retryability.
- Dùng Chrome thật (`channel="chrome"`, không headless mặc định — Cloudflare chặn
  Chromium headless), stable selector, explicit wait, retry/backoff có giới hạn,
  read-after-write verification.
- Khi lỗi, lưu screenshot đã redaction và HTML/URL metadata cần thiết; không log
  cookie/password/nội dung khách không cần thiết.
- Dùng service account/profile riêng, lock theo order, concurrency giới hạn và global
  kill switch cho outbound write.
- Khi click có thể thành công nhưng chưa verify được: đặt operation là
  `UNKNOWN_OUTCOME`; reconcile trước retry.
- Không dùng click tọa độ, JS injection tùy tiện hay destructive shortcut để recover.

## 9. Google Sheets, Drive và Apps Script

- PostgreSQL là source of truth; Sheet chỉ là **archive một chiều** — job nền export
  snapshot đơn (ví dụ theo ngày) ra Sheet để lưu trữ/tra cứu, không đọc ngược lại để quyết
  định state.
- Sync Sheet phải idempotent bằng `exported_at`/operation marker (không xuất trùng dòng
  khi job chạy lại).
- Xác minh Drive URL, quyền truy cập, file tồn tại và version trước khi submit lên
  Printerval.
- Sửa tay trên Sheet archive không có quyền bypass state/approval — Sheet không phải nơi
  thao tác.

## 10. Web dashboard và approval của con người

- Web dashboard là giao diện chính; business logic nằm ở backend (application
  service/state machine), không nằm ở template/route handler.
- Auth: bảng `users` (role admin/designer), session cookie; route theo role.
- Approval action (C3, C5) submit qua form/HTMX với CSRF token hợp lệ, không dựa vào
  raw state/order data phía client.
- Card/màn hình duyệt phải hiển thị order ref, thông tin khách, designer, result
  link/version, feedback cũ và deadline (nếu có).
- Request idempotent; database là authority cho quyết định.
- Bắt buộc comment với **Edit** và **Cancel + Reply**; gửi feedback qua outbox.
- **Nhiều admin cùng quyền duyệt (V1, đã chốt):** bất kỳ ai trong allowlist admin role
  đều duyệt được từ web — chỉ yêu cầu luôn có ≥1 admin hoạt động, không có single point
  of failure. Quyết định đầu tiên hợp lệ (đúng role, đúng expiry) là quyết định cuối
  cùng; mọi request đến sau trên cùng approval ID phải bị từ chối kèm thông báo "đã được
  [tên admin] xử lý lúc [time]" — không silent-ignore.
- **Telegram không còn trong V1.** Có thể thêm lại ở V2 làm kênh **thông báo phụ**
  (push notification khi có task mới/QC mới) — không có nút bấm thao tác, mọi hành động
  vẫn bắt buộc làm trên web.

## 11. Error handling, retry và reconciliation

Phân loại: `VALIDATION`, `AUTH`, `RATE_LIMIT`, `TRANSIENT_NETWORK`, `EXTERNAL_CHANGED`,
`UNKNOWN_OUTCOME`, `PERMANENT_EXTERNAL`, `BUG`.

- Chỉ retry loại retryable, exponential backoff + jitter, có giới hạn attempt.
- Redis lock/queue chỉ hỗ trợ; correctness phải dựa vào DB constraint/transaction.
- Dùng transactional outbox cho message và scheduling external work (bao gồm crawl job,
  submit-to-site job, Sheet export job).
- Hết retry đưa vào `dead_letters` kèm recovery action cho operator, hiển thị trên web.
- Xây reconciliation sớm: đối chiếu DB, Printerval và Sheet; trả diff rõ ràng, không tự
  sửa nếu chưa có policy an toàn. Nếu Printerval trả về trạng thái ngoài dự kiến (`Fix`/
  `Confirm` bất ngờ, xem mục 17 #6) → vào exception queue, không đoán.

## 12. Quy tắc LLM/agent (V2, không phải V1)

V1 **không có LLM/agent**. Mục này giữ lại để định hướng nếu thêm agent ở V2, ngồi trên
cùng lớp MCP façade với web dashboard, không thay thế web.

Local LLM agent (nếu làm) được phép parse intent thành command có cấu trúc, giải thích
status/tóm tắt batch/exception, đề xuất plan và gọi business tool whitelist theo policy.

Agent không được truy cập Playwright/DOM/browser credential/raw DB write/shell/generic
HTTP; không được tự nghĩ state transition, bypass approval, coi prose là authorization
hay tự approve QC/assignment. Chat history không là record chính thức.

Phải có command validator giữa output agent và tool execution. Yêu cầu mơ hồ/high-impact
phải tạo approval request hoặc hỏi operator xác nhận có cấu trúc trên web.

### 12.1 Ranh giới tự quyết (autonomy boundary, áp dụng nếu có agent)

Agent vận hành theo mô hình lai: được tự gọi tool cho việc cơ học, nhưng bắt buộc dừng
lại và tạo approval request cho 4 nhóm quyết định sau — **không có ngoại lệ, không suy
luận thay**:

1. `decide_assignment` (C3) — Approve/Cancel assignment.
2. `decide_qc` (C5) — Approve/Edit/Skip/Cancel; áp dụng lại cho **mọi** result version
   mới, kể cả sau khi designer đã sửa theo feedback. Không tái dùng quyết định QC của
   version cũ, không tự suy luận bản sửa "chắc là ổn" để bỏ qua bước này.
3. Bất kỳ exception hoặc reconciliation mismatch nào không có evidence rõ ràng khớp
   100% (DB/Sheet/website lệch nhau, `UNKNOWN_OUTCOME`, link/asset không xác minh được)
   — luôn vào exception queue cho operator xử lý, giữ nguyên bất biến #10.
4. Hủy đơn/assignment ngoài luồng approval có sẵn (operator yêu cầu hủy thủ công,
   ad-hoc, không qua C3/C5) — cần lệnh tường minh, có xác nhận cấu trúc từ operator;
   không suy luận ý định hủy từ hội thoại tự do.

Ngoài 4 nhóm trên, agent được tự gọi trực tiếp các tool whitelist khi input rõ ràng và
không mơ hồ: `discover_waiting_orders`, `claim_batch`, `import_claimed_batch`,
`open_allocation`, `request_quantity`, `create_assignment_draft`, `validate_assignment`,
`create_assignment_approval`, `record_result`, `create_qc_request`,
`submit_approved_result_to_site` (chỉ sau khi QC đã approved), `reconcile_order` (chỉ
phần tính diff read-only).

Việc "tự gọi tool" chỉ là bỏ qua bước hỏi xác nhận trước khi gọi — logic bên trong tool
(chọn order nào cho designer nào, v.v.) vẫn phải deterministic theo bất biến #5, không
phải do LLM suy luận tự do. Nếu agent không chắc một hành động thuộc nhóm nào, mặc định
coi là nhóm phải hỏi (nhóm 1–4).

## 13. Quy tắc code và test

- Python type hint đầy đủ, Pydantic model rõ, error type riêng.
- Tách `domain/`, `application/`, `adapters/`, `workers/`, `api/` (routes + templates),
  `tests/`, `migrations/`; domain không phụ thuộc FastAPI/Jinja2/Playwright/Sheet/LLM
  framework.
- Function nhỏ, deterministic; inject interface, dùng fake adapter khi test (Playwright
  adapter fake, allocation tool interface fake).
- Mọi schema change có migration; không sửa DB production ad hoc.
- Không thêm dependency, multi-agent hoặc framework nếu không phục vụ acceptance
  criterion V1 (không thêm OAuth trong V1). Frontend là SPA React+TS+Vite+Tailwind
  (quyết định 2026-09-07) — Jinja2/HTMX/Alpine của Phase 4 sẽ được thay thế hoàn toàn,
  không giữ song song 2 bộ UI.
- Test tối thiểu: transition, permission, idempotency, allocation/replacement; contract
  adapter; integration fake adapter; E2E happy path, duplicate request, timeout-after-write,
  order already completed, link lỗi, stale QC, result version revision, reconciliation
  mismatch, crawl job dedupe, submit-to-site chỉ chạy sau Approve, Sheet export không
  trùng dòng.
- Không test live customer data/credential mặc định; test phải deterministic.

## 14. Observability và security

- Structured log luôn có `correlation_id`, `order_id`, `batch_id`, `assignment_id`,
  `operation_id`, state, adapter, outcome.
- Metrics: queue depth, retry, unknown outcome, state stuck, approval age, external
  mismatch, selector failure.
- Trace xuyên suốt web route → application service → worker → adapter.
- Secret chỉ qua secret mechanism/environment injection được duyệt; không commit `.env`,
  browser profile, token, cookie hay export nhạy cảm.
- Redact mặc định và least-privilege cho DB/Google scope. Session cookie: httponly,
  secure, rotate on login.

## 15. Thứ tự implement

1. Scaffold, config, Postgres local, migration, test harness, audit/event primitive.
2. State machine, operation/idempotency ledger, role (`users` table), outbox,
   reconciliation skeleton.
3. Adapter Playwright read-only cho Printerval (crawl), Sheets/Drive adapter, tài liệu
   field map (đã có ở `docs/phase0-field-map.md`).
4. C1 crawl & claim workflow, dry-run rồi pilot.
5. Web dashboard khung: auth, danh sách đơn (đọc), role admin/designer. (Ban đầu làm bằng
   Jinja2+HTMX+Alpine — đã thay thế hoàn toàn bằng React SPA từ bước 5b.)
5b. Order detail mirror: mở rộng `orders` với field-map thật từ Printerval (product info,
    SKU, custom config, 3 mốc thời gian, note...) để designer/admin làm việc hoàn toàn
    trên web mình, không cần mở Printerval.
5c. Frontend platform migration: React + TypeScript + Vite + Tailwind thay thế Jinja2 —
    scaffold, auth flow, order list/detail port sang SPA.
6. C2 phân bổ (offer + admin gán tay, bản tham chiếu thuật toán FIFO) với UI kéo-thả
   (Allocation Board, `dnd-kit`), C3 validation/approval trên web.
7. Task view cho designer (nhận task, sub-status, nộp kết quả) — C4.
7b. Kanban ops board: theo dõi tiến độ toàn bộ đơn qua các state, kéo-thả đổi sub-status.
8. C5 QC trên web (màn hình so sánh mẫu gốc/kết quả cạnh nhau) + job tự động submit-to-site
   sau Approve, revision loop, skipped reconciliation.
9. Sheet export job (archive một chiều).
10. Monitoring, runbook, backup, kill switch, recovery commands/UI.
11. (V2, ngoài phạm vi bây giờ) optional local LLM agent, kênh thông báo Telegram phụ.

## 16. Bối cảnh vận hành đã xác nhận (2026-09)

- **Website khách:** một website duy nhất (Printerval), dùng chung cho toàn bộ luồng —
  nhận batch mới (`waiting`), claim, `doing → review → done`, và cũng là nơi gán link
  Drive kết quả. Công ty vận hành qua **một tài khoản cố định** do khách cấp — không cần
  adapter đa-site, không cần đa-tài khoản trong V1.
- **Playwright đã xác nhận thay Selenium:** Chromium headless bị Cloudflare chặn (403);
  dùng Chrome thật (`channel="chrome"`, không headless) + giảm fingerprint bot
  (`--disable-blink-features=AutomationControlled`) chạy được.
- **Kênh designer (V1):** designer tự offer số lượng ngay trên web dashboard (không qua
  Telegram); nhận task, cập nhật sub-status, dán link Drive, bấm nộp — tất cả trên web.
  Designer không có tài khoản riêng trên Printerval (chỉ tài khoản `ntth` dùng để
  claim/phân biệt đơn).
- **Khối lượng:** biến động, đỉnh có thể tới vài trăm order/ngày, tồn đọng quan sát được
  529 đơn tại 1 thời điểm — xác nhận Redis/Celery/Dramatiq và phân trang/queue đàng hoàng
  từ V1 là cần thiết.
- **Phạm vi loại job V1 (đã đổi 2026-09-07, không còn lọc cứng 2D):** crawl mặc định
  **tất cả loại job** ("Tất cả 2D&3D" — option thật đã xác nhận trên site, xem
  `docs/phase0-field-map.md`). Loại job chỉ là nhãn phân loại từ khách, không ảnh hưởng
  quy trình xử lý V1 (team vẫn xử lý được, không cần loại trừ). Có thể thêm UI chọn lọc
  theo loại cụ thể trên web sau nếu cần, không bắt buộc cho V1.
- **Hạ tầng production 24/7:** build/pilot hiện tại chạy trên MacBook Pro M3 Pro 32GB
  (máy dev). Cấu hình phần cứng production **chưa chốt** — không block V1 vì V1 không có
  LLM.

## 17. Quyết định còn mở / nợ kỹ thuật (theo dõi tới khi chốt)

| # | Vấn đề | Trạng thái | Ghi chú |
|---|---|---|---|
| 1 | Tiêu chí xác định "đơn đã làm" (dùng cho `validate_assignment`/Cancel C3) | Chưa có rule cụ thể | Cần khảo sát thực tế Printerval |
| 2 | SLA timeout cho `REASSIGNMENT_REQUIRED` | Placeholder tuyến tính (10 order ≈ 1h) | Xem mục 5; chỉ cảnh báo, không tự chuyển state |
| 3 | Nơi lưu trữ `order_assets` (ảnh tải về) | Chưa chốt: VPS hoặc hạ tầng local | V1 dùng local disk cho pilot, thiết kế adapter lưu trữ qua interface để đổi backend sau không phải sửa domain |
| 4 | Giới hạn concurrency Playwright (số session song song) | Chưa đo | Đo thực tế ở Phase 2, mặc định an toàn: 1 session/site cho tới khi có số liệu |
| 5 | Cấu hình phần cứng production 24/7 | Chưa chốt, không block V1 | V1 không có LLM nên không cần Apple Silicon/GPU; chỉ cần host web+Postgres bình thường |
| 6 | Cơ chế chính xác `review → done` trên Printerval | Cần xác nhận — status thật có 6 giá trị `Waiting/Doing/Review/Fix/Confirm/Done`. Xem `docs/phase0-field-map.md` | `Fix`/`Confirm` là gì, ai/khi nào set — chưa rõ. Nghi vấn: `Fix` = kết quả Edit của QC nội bộ (có cơ chế -5 điểm khi chuyển Fix); `Confirm` chưa rõ là bước nội bộ hay do khách tự xác nhận (giống case Skip). **Phát hiện mới (Phase 2, 2026-09-07):** tài khoản outsource admin dùng để claim/thao tác **không tự set được `Confirm → Done` trực tiếp** qua control admin này — xác nhận thực tế: `select_option` sang "Done" không bắn request mạng nào, kể cả dispatch JS thủ công. Nghi vấn mạnh: `Done` do "web mẹ" (site khách-facing) hoặc một quyền cao hơn set, không phải quyền outsource admin. Chưa xác nhận ai/khi nào thật sự set được `Done`. |
| 7 | Cơ chế điểm designer (-5đ/lần Fix) + tiền phạt đã có sẵn trên website | Cần xác nhận | Có cần đồng bộ vào Postgres để ảnh hưởng thứ tự phân đơn C2, hay đây là tính năng riêng của website, hệ thống mình không cần đụng vào? |
| 8 | 3 mốc thời gian mỗi đơn: `Created at` / `Order created at` / `Deadline at` | Cần xác nhận | Chưa rõ cái nào tính SLA/trễ hạn, cái nào là mốc claim. **Liên quan (Phase 2):** `PlaywrightPrintervalAdapter.get_order_detail` hiện chưa populate cả 3 mốc này (và `order_note`, `thumbnail_url` ở `discover_orders`) — cố tình để trống/default thay vì đoán field, vì chưa biết field nào đúng; cần khảo sát DOM thật (giống cách Task 5/6 đã làm cho các field khác) sau khi mục #8 này được chốt. |
| 9 | Tool phân bổ FIFO production thật (đã có sẵn, chạy nơi khác) | Chưa tích hợp | V1 chỉ viết bản tham chiếu để test; tích hợp tool thật qua interface riêng ở giai đoạn sau |
| 10 | Đơn bị Cancel ở C3 vào `EXCEPTION`, không có đường thoát tự động | Chấp nhận cho V1, cần recovery UI sau | Phát hiện lúc implement sub-project 3 (allocation board): nếu đơn Cancel quay lại `OPEN_FOR_ALLOCATION` ngay, FIFO có thể cấp lại chính đơn đó (hoặc cho designer khác) trong khi tiêu chí "đơn đã làm/không hợp lệ" (#1) chưa xác minh được — sai theo bất biến #10. V1 đưa đơn vào `EXCEPTION`, admin phải xử lý thủ công (chưa có UI, xem claude.md §15 bước 10) mới đưa đơn ra khỏi EXCEPTION được. |

## 18. Definition of done V1

V1 chỉ hoàn tất khi pilot đơn thật C1–C5 chạy an toàn trên web dashboard và đạt tất cả
điều kiện:

- Mọi order có unique internal record và audit trail append-only.
- Transition/approval được backend enforce, không bị bypass qua web route.
- Batch/resume/retry idempotent và reconciliation được.
- Assignment cancel có quy trình bù đơn traceable.
- Result version và QC revision loop chính xác.
- Playwright/Sheet lỗi thành exception nhìn thấy được trên web, không mất dữ liệu âm
  thầm.
- Admin có quyền xem, pause, retry, escalate từ web dashboard.
- Designer có thể tự offer, xem task, cập nhật sub-status, nộp kết quả từ web dashboard.
- Đã cover edge case bằng test và backup/restore drill pass.
- Chỉ Approve QC mới bao giờ chạm tới Printerval (Edit/Skip/Cancel không đụng site
  khách).

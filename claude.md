# Claude Code Project Instructions — AI Operations Agent V1

## 1. Sứ mệnh

Implement **V1** cho hệ thống vận hành nội bộ xử lý order ảnh/sản phẩm: nhận đơn, chia designer, duyệt phân đơn, phân phát, thu link kết quả, submit review và QC bởi con người.

Ưu tiên tuyệt đối: **reliability, auditability, recoverability và an toàn cho operator**. Chat model chỉ là lớp hỗ trợ, không phải nơi quyết định workflow.

## 2. Bất biến bắt buộc

1. PostgreSQL là source of truth duy nhất cho state nội bộ và audit history.
2. Google Sheets là projection/collaboration surface, không phải database quyết định.
3. Website là external integration; phải lưu external observation và reconcile.
4. Mọi command có side effect cần idempotency key và operation/audit record.
5. Chỉ state machine được phép validate/đổi state; adapter và LLM không write state trực tiếp.
6. LLM không được điều khiển Selenium theo selector/element/tọa độ.
7. Không dispatch đơn trước assignment approval; không tự động quyết định QC trong V1.
8. Không overwrite lịch sử: append event, version assignment/result.
9. Mọi input bên ngoài (Telegram, Sheet, website, LLM output) là không đáng tin cậy.
10. Khi không chắc chắn, đưa vào exception queue thay vì đoán cách recover.

## 3. Workflow V1 phải triển khai

### B1 — Claim đơn trên web mẹ

Customer gửi batch đơn (ví dụ 100) lên web mẹ. Đơn hợp lệ ở trạng thái `waiting`. Đổi designer sang `ntth` để claim và phân biệt với đơn cũ/đơn designer khác. Xác minh từng write.

### B2 — Import batch và bắt đầu làm

Lọc các đơn `waiting + ntth`; tải ảnh; upload/đăng ký vào intake Google Sheet; đổi status web mẹ `waiting → doing` nhưng vẫn giữ `ntth`. Không đổi internal state thành `IMPORTED` nếu asset và mapping Sheet chưa được xác minh.

### B3 — Designer đăng ký và chia đơn

Thông báo Telegram để designer đăng ký số lượng (ví dụ Lâm nhận 20). Hệ thống phải chọn các order cụ thể, ghi designer vào row và tạo assignment draft. Đăng ký quantity không được coi là assignment cho đến khi order IDs đã được persist.

**Thuật toán chia (V1, đã chốt):** FIFO theo thứ tự đăng ký, khối liền kề (contiguous block) trên danh sách order còn lại của batch. Lâm đăng ký trước nhận 20 order đầu tiên còn `unassigned`; Hoa đăng ký sau nhận 20 order tiếp theo ngay sau khối của Lâm; cứ thế tới hết batch. Không có ưu tiên theo skill/độ khó trong V1. Vì nhiều designer có thể nhắn đăng ký gần như đồng thời trong group, việc "giữ chỗ" khối order phải là một transaction DB tuần tự hóa theo thứ tự tin nhắn đến (message timestamp/ID), không được có 2 designer cùng giữ chung 1 order — dùng lock/`SELECT … FOR UPDATE` trên order còn `unassigned` của batch. Nếu số lượng còn lại không đủ, designer đăng ký sau chỉ nhận phần còn lại (không round-robin, không chia lại của người trước).

### B4 — Validate và admin approval

Với từng assignment draft: truy xuất web khách để lấy/check thông tin đơn (tên, ảnh, mẫu, màu) cùng designer; gửi Telegram card cho admin **Approve** hoặc **Cancel**.

Cancel nghĩa là đơn đã làm/không hợp lệ. Lưu lý do và bằng chứng, release order, trả quota còn thiếu của designer, quay lại B3 để chọn đơn bù. Tuyệt đối không thay đơn âm thầm. Chỉ assignment approved được projection sang Sheet 2.

### B5 — Dispatch và thu kết quả

Từ Sheet 2, dispatch order approved sang bảng riêng của designer. Designer gắn Drive result link. Collector kiểm tra và map link về order/bảng tổng.

### B6 — Submit kết quả lên web khách

Đọc result đã kiểm tra từ bảng tổng, post lên web khách và verify `doing → review`.

### B7 — QC bởi con người và vòng sửa

Gửi order ở review kèm context/result link vào Telegram QC. Admin bắt buộc chọn:

- **Approve:** ghi nhận duyệt và hoàn tất đơn.
- **Edit:** bắt buộc có feedback; gửi designer sửa.
- **Skip:** web khách tạm xử lý và dự kiến tự đổi trạng thái; lên lịch reconcile.
- **Cancel + Reply:** hủy có lý do và gửi/lưu phản hồi.

Khi designer gửi result đã sửa, kiểm tra có result version mới, submit lại review, rồi tạo QC approval request mới. Không dùng quyết định QC cũ cho result version mới.

## 4. Kiến trúc và boundary

```text
Telegram gateway / API
      │
      ▼
Application service + deterministic workflow/state machine
      │                 │
      │                 └─ PostgreSQL: state, event, approval, operation
      ▼
Business tools / MCP façade
 ├─ Parent website adapter → Selenium worker
 ├─ Customer website adapter → Selenium worker
 ├─ Google Sheets / Drive adapter
 └─ Telegram adapter

Optional local Qwen agent → chỉ gọi business tool được whitelist
```

Stack gợi ý: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16, Redis + Celery/Dramatiq, Selenium 4, Google APIs và Telegram bot library. Dùng MLX-LM trên Apple Silicon. Thử Qwen3-30B-A3B quantized; fallback Qwen3-14B quantized. Correctness của hệ thống không được phụ thuộc LLM.

## 5. State model

Luồng chính:

`DISCOVERED → CLAIMED → IMPORTED → OPEN_FOR_SIGNUP → ASSIGNMENT_PENDING_APPROVAL → ASSIGNED → DISPATCHED → RESULT_RECEIVED → SUBMITTED_FOR_REVIEW → QC_PENDING → DONE`

Nhánh thay thế:

- `ASSIGNMENT_PENDING_APPROVAL → OPEN_FOR_SIGNUP`: admin cancel do đơn không hợp lệ/đã làm.
- `DISPATCHED → REASSIGNMENT_REQUIRED`: designer không thể thực hiện; cần recovery rõ ràng. SLA im lặng để đề xuất trạng thái này **chưa chốt — nợ kỹ thuật**: tạm dùng công thức tuyến tính theo quantity của assignment (mặc định 10 order ≈ 1 giờ, scale theo số lượng); công thức này chỉ tạo cảnh báo cho operator, không tự chuyển state — quyết định chuyển vẫn qua exception queue (12.1, nhóm 3).
- `QC_PENDING → REVISION_REQUESTED → DISPATCHED`: QC chọn **Edit**.
- `QC_PENDING → SKIPPED`: QC chọn **Skip**, sau đó reconcile.
- `QC_PENDING → CANCELLED`: QC chọn **Cancel + Reply**.
- Bất kỳ state nào cũng có thể vào `EXCEPTION` kèm error class và recovery owner; chỉ explicit command mới được ra khỏi state này.

Đặt transition trong một module/policy table duy nhất. Mỗi transition phải kiểm tra current state, external evidence bắt buộc, actor/role, result version (nếu có) và idempotency key. Ghi `workflow_event` append-only trong cùng transaction.

## 6. Yêu cầu mô hình dữ liệu

Tối thiểu phải có migration cho:

- `orders`: UUID nội bộ, external order IDs bất biến, state hiện tại, external observation, batch ID, timestamp, optimistic version.
- `order_assets`: source image ref, checksum, vị trí download/upload.
- `batches`: source/filter, owner, count, lifecycle.
- `designers`: tên chuẩn hóa, Telegram ID, active/capacity.
- `assignments`: order, designer, trạng thái, thời gian, lý do cancel và liên kết replacement.
- `result_versions`: assignment, Drive link, checksum/version marker, validation, submitted time.
- `approval_requests`, `approval_decisions`: loại, target version, actor được phép, expiry, decision/comment, Telegram message ref.
- `external_refs` / `external_observations`: ID web, sheet ID + row key ổn định, observed state/evidence/time.
- `operations`: idempotency key, command, request fingerprint, status, evidence, retry count.
- `workflow_events`, `outbox`, `dead_letters`.

Tạo unique constraint theo external ID nguồn và idempotency scope. Không dùng số dòng Sheet làm identity; có cột UUID cố định ẩn/protected.

## 7. Business tool contracts

Expose tool hẹp, typed và validate bằng Pydantic. Trả JSON có cấu trúc. Không expose Selenium primitive.

```text
discover_waiting_orders(source, limit) -> {orders, cursor}
claim_batch(order_ids, owner="ntth", idempotency_key) -> BatchResult
import_claimed_batch(batch_id, idempotency_key) -> BatchResult
open_signup(batch_id, idempotency_key) -> SignupResult
request_quantity(designer_id, batch_id, quantity, idempotency_key) -> AllocationDraft
create_assignment_draft(order_id, designer_id, idempotency_key) -> Assignment
validate_assignment(assignment_id, idempotency_key) -> ValidationResult
create_assignment_approval(assignment_id, idempotency_key) -> ApprovalRequest
decide_assignment(approval_id, decision, actor_id, idempotency_key) -> AssignmentResult
dispatch_approved_assignment(assignment_id, idempotency_key) -> DispatchResult
record_result(order_id, drive_url, source_version, idempotency_key) -> ResultVersion
submit_result_for_review(order_id, result_version_id, idempotency_key) -> SubmissionResult
create_qc_request(order_id, result_version_id, idempotency_key) -> ApprovalRequest
decide_qc(approval_id, decision, actor_id, comment, idempotency_key) -> QCResult
reconcile_order(order_id, idempotency_key) -> ReconciliationResult
```

Write tool luôn cần authorization, state check, idempotency và observability. Approval tool phải validate callback Telegram, role, expiry, target state và result version.

## 8. Selenium execution rules

- Selenium là implementation detail trong adapter; không bao giờ là MCP/LLM tool.
- Một adapter method làm đúng một business action, trả `success`, external IDs/status, evidence, error class và retryability.
- Dùng stable selector, explicit wait, retry/backoff có giới hạn, read-after-write verification.
- Khi lỗi, lưu screenshot đã redaction và HTML/URL metadata cần thiết; không log cookie/password/nội dung khách không cần thiết.
- Dùng service account/profile riêng, lock theo order, concurrency giới hạn và global kill switch cho outbound write.
- Khi click có thể thành công nhưng chưa verify được: đặt operation là `UNKNOWN_OUTCOME`; reconcile trước retry.
- Không dùng click tọa độ, JS injection tùy tiện hay destructive shortcut để recover.

## 9. Google Sheets, Drive và Apps Script

- PostgreSQL điều khiển mọi projection write; giữ canonical order UUID, assignment ID, result version ID ở cột protected.
- Sync Sheet phải idempotent bằng `external_sync_version` hoặc operation marker.
- Apps Script có thể phân dòng/thu kết quả nhưng phải gọi backend webhook hoặc được reconciliation worker ghi nhận; không trở thành source of truth.
- Xác minh Drive URL, quyền truy cập, file tồn tại và version trước transition.
- Manual edit là event để reconcile, không phải quyền bypass state/approval.

## 10. Telegram và approval của con người

- Telegram chỉ là UI/gateway; business logic nằm ở backend.
- Allowlist chat/user và map Telegram user ID sang internal role.
- Button phải chứa opaque signed approval ID, không chứa raw state/order data có thể bị giả mạo.
- Card phải hiển thị order ref, thông tin khách, designer, result link/version, feedback cũ và deadline (nếu có).
- Callback idempotent; có thể edit/disable message sau quyết định nhưng database mới là authority.
- Bắt buộc comment với **Edit** và **Cancel + Reply**; gửi feedback qua outbox.
- **Nhiều admin cùng quyền duyệt (V1, đã chốt):** approval card (assignment B4, QC B7) gửi vào group chat chung, bất kỳ ai trong allowlist admin role đều bấm được — chỉ yêu cầu luôn có ≥1 admin hoạt động, không có single point of failure. Quyết định đầu tiên hợp lệ (đúng role, đúng expiry) là quyết định cuối cùng; mọi callback đến sau trên cùng approval ID phải bị từ chối kèm thông báo "đã được [tên admin] xử lý lúc [time]" — không silent-ignore.

## 11. Error handling, retry và reconciliation

Phân loại: `VALIDATION`, `AUTH`, `RATE_LIMIT`, `TRANSIENT_NETWORK`, `EXTERNAL_CHANGED`, `UNKNOWN_OUTCOME`, `PERMANENT_EXTERNAL`, `BUG`.

- Chỉ retry loại retryable, exponential backoff + jitter, có giới hạn attempt.
- Redis lock/queue chỉ hỗ trợ; correctness phải dựa vào DB constraint/transaction.
- Dùng transactional outbox cho message và scheduling external work.
- Hết retry đưa vào `dead_letters` kèm recovery action cho operator.
- Xây reconciliation sớm: đối chiếu DB, hai website và Sheet; trả diff rõ ràng, không tự sửa nếu chưa có policy an toàn.

## 12. Quy tắc LLM/agent

Local Qwen agent được phép parse intent thành command có cấu trúc, giải thích status/tóm tắt batch/exception, đề xuất plan và gọi business tool whitelist theo policy.

Agent không được truy cập Selenium/DOM/browser credential/raw DB write/shell/generic HTTP; không được tự nghĩ state transition, bypass approval, coi prose là authorization hay tự approve QC/assignment. Chat history không là record chính thức.

Phải có command validator giữa output agent và tool execution. Yêu cầu mơ hồ/high-impact phải tạo approval request hoặc hỏi operator xác nhận có cấu trúc.

### 12.1 Ranh giới tự quyết (autonomy boundary)

Agent vận hành theo mô hình lai: được tự gọi tool cho việc cơ học, nhưng bắt buộc dừng lại và tạo approval request cho 4 nhóm quyết định sau — **không có ngoại lệ, không suy luận thay**:

1. `decide_assignment` (B4) — Approve/Cancel assignment trước dispatch.
2. `decide_qc` (B7) — Approve/Edit/Skip/Cancel; áp dụng lại cho **mọi** result version mới, kể cả sau khi designer đã sửa theo feedback. Không tái dùng quyết định QC của version cũ, không tự suy luận bản sửa "chắc là ổn" để bỏ qua bước này.
3. Bất kỳ exception hoặc reconciliation mismatch nào không có evidence rõ ràng khớp 100% (DB/Sheet/website lệch nhau, `UNKNOWN_OUTCOME`, link/asset không xác minh được) — luôn vào exception queue cho operator xử lý, giữ nguyên bất biến #10.
4. Hủy đơn/assignment ngoài luồng approval có sẵn (operator yêu cầu hủy thủ công, ad-hoc, không qua card B4/B7) — cần lệnh tường minh, có xác nhận cấu trúc từ operator; không suy luận ý định hủy từ hội thoại tự do.

Ngoài 4 nhóm trên, agent được tự gọi trực tiếp các tool whitelist khi input rõ ràng và không mơ hồ — không cần hỏi lại người mỗi lần: `discover_waiting_orders`, `claim_batch`, `import_claimed_batch`, `open_signup`, `request_quantity`, `create_assignment_draft`, `validate_assignment`, `create_assignment_approval`, `dispatch_approved_assignment` (chỉ sau khi assignment đã approved), `record_result`, `submit_result_for_review`, `create_qc_request`, `reconcile_order` (chỉ phần tính diff read-only).

Việc "tự gọi tool" chỉ là bỏ qua bước hỏi xác nhận trước khi gọi — logic bên trong tool (chọn order nào cho designer nào, v.v.) vẫn phải deterministic theo bất biến #5, không phải do LLM suy luận tự do. Nếu agent không chắc một hành động thuộc nhóm nào, mặc định coi là nhóm phải hỏi (nhóm 1–4).

## 13. Quy tắc code và test

- Python type hint đầy đủ, Pydantic model rõ, error type riêng.
- Tách `domain/`, `application/`, `adapters/`, `workers/`, `api/`, `tests/`, `migrations/`; domain không phụ thuộc FastAPI/Selenium/Sheet/Telegram/LLM framework.
- Function nhỏ, deterministic; inject interface, dùng fake adapter khi test.
- Mọi schema change có migration; không sửa DB production ad hoc.
- Không thêm dependency, multi-agent hoặc framework nếu không phục vụ acceptance criterion V1.
- Test tối thiểu: transition, permission, idempotency, allocation/replacement; contract adapter; integration fake adapter; E2E happy path, duplicate callback, timeout-after-write, order already completed, link lỗi, stale QC, result version revision, reconciliation mismatch.
- Không test live customer data/credential mặc định; test phải deterministic.

## 14. Observability và security

- Structured log luôn có `correlation_id`, `order_id`, `batch_id`, `assignment_id`, `operation_id`, state, adapter, outcome.
- Metrics: queue depth, retry, unknown outcome, state stuck, approval age, external mismatch, selector failure.
- Trace xuyên suốt API → workflow → worker → adapter.
- Secret chỉ qua secret mechanism/environment injection được duyệt; không commit `.env`, profile browser, token, cookie hay export nhạy cảm.
- Redact mặc định và least-privilege cho DB/Google scope.

## 15. Thứ tự implement

1. Scaffold, config, Postgres local, migration, test harness, audit/event primitive.
2. State machine, operation/idempotency ledger, role, outbox, reconciliation skeleton.
3. Adapter read-only cho web mẹ, web khách, Sheets/Drive, Telegram và tài liệu field map.
4. B1–B2 deterministic workflow, dry-run rồi pilot.
5. B3–B4 signup, allocation, validation, approval/replacement.
6. B5 dispatch/result collection và result versioning.
7. B6–B7 submit, QC, revision loop, skipped reconciliation.
8. Monitoring, runbook, backup, kill switch, recovery commands/UI.
9. Chỉ sau đó mới thêm optional local-Qwen tool-calling gateway.

## 16. Bối cảnh vận hành đã xác nhận (2026-09)

- **Web khách:** một website duy nhất. Công ty vận hành như "công ty con" qua **một tài khoản cố định** do khách cấp (tài khoản A trong số nhiều tài khoản A/B/C/D khách chia cho các đối tác khác nhau) — không cần adapter đa-site, không cần đa-tài khoản trong V1.
- **Kênh designer:** designer đăng ký số lượng ngay trong group Telegram chung; sau khi được chia, tự lên Google Sheet lấy mã đơn được giao, tự lên web khách (đã scope theo tài khoản công ty) xem chi tiết/ảnh mẫu bằng trình duyệt cá nhân (không qua Selenium), làm xong tự upload Drive rồi dán link vào sheet tổng để hệ thống thu thập. Selenium chỉ dùng cho các thao tác backend (claim, submit, QC-related), không dùng để tự động hoá việc designer xem đơn.
- **Khối lượng:** biến động, đỉnh có thể tới vài trăm order/ngày — xác nhận việc dùng Redis/Celery/Dramatiq từ V1 (roadmap mục 3) là hợp lý, không phải over-engineering.
- **Hạ tầng chạy Qwen/production:** build/pilot hiện tại chạy trên MacBook Pro M3 Pro 32GB (máy dev). Production dự kiến build local server 24/7 riêng, cấu hình phần cứng **chưa chốt**. Gợi ý nhanh (không chặn V1): giữ nguyên hệ Apple Silicon (Mac mini/Studio M-series, tối thiểu 32–48GB unified memory) để tận dụng MLX-LM đã chọn trong stack, tránh phải đổi runtime LLM khi lên production; nếu chấp nhận đổi sang llama.cpp/vLLM thì một máy Linux + GPU 16–24GB VRAM là phương án thay thế.

## 17. Quyết định còn mở / nợ kỹ thuật (theo dõi tới khi chốt)

| # | Vấn đề | Trạng thái | Ghi chú |
|---|---|---|---|
| 1 | Tiêu chí xác định "đơn đã làm" (dùng cho `validate_assignment`/Cancel B4) | Chưa có rule cụ thể | Cần khảo sát thực tế web khách ở Phase 0 |
| 2 | SLA timeout cho `REASSIGNMENT_REQUIRED` | Placeholder tuyến tính (10 order ≈ 1h) | Xem mục 5; chỉ cảnh báo, không tự chuyển state |
| 3 | Nơi lưu trữ `order_assets` (ảnh tải về) | Chưa chốt: VPS hoặc hạ tầng local | V1 dùng local disk cho pilot, thiết kế adapter lưu trữ qua interface để đổi backend sau không phải sửa domain |
| 4 | Giới hạn concurrency Selenium (số session song song) | Chưa đo | Đo thực tế ở Phase 2, mặc định an toàn: 1 session/site cho tới khi có số liệu |
| 5 | Cấu hình phần cứng production 24/7 | Chưa chốt | Xem gợi ý mục 16; quyết định sau khi có ngân sách |

## 18. Definition of done V1

V1 chỉ hoàn tất khi pilot đơn thật B1–B7 chạy an toàn và đạt tất cả điều kiện:

- Mọi order có unique internal record và audit trail append-only.
- Transition/approval được backend enforce.
- Batch/resume/retry idempotent và reconciliation được.
- Assignment cancel có quy trình bù đơn traceable.
- Result version và QC revision loop chính xác.
- Browser/Sheet lỗi thành exception nhìn thấy được, không mất dữ liệu âm thầm.
- Operator có quyền xem, pause, retry, escalate.
- Đã cover edge case bằng test và backup/restore drill pass.
- Workflow vẫn hoạt động khi Qwen service tắt.

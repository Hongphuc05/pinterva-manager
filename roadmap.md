# Web Dashboard Vận Hành — Roadmap V1

> **Phiên bản:** V1
> **Mục tiêu:** Xây web dashboard nội bộ (admin + designer) làm giao diện chính điều phối
> nhận đơn, chia đơn, sản xuất, duyệt và QC giữa website Printerval, Google Sheets/Drive.
> Không có Telegram, không có LLM trong V1 — mọi thay đổi trạng thái do state machine xác
> định thực hiện, mọi thao tác con người đi qua web.
>
> Xem `docs/superpowers/specs/2026-09-06-web-dashboard-design.md` để có đầy đủ bối cảnh
> quyết định kiến trúc.

## 1. Kết quả cần đạt

Hệ thống xử lý một batch đơn hàng từ đầu đến cuối theo luồng có thể kiểm tra, khôi phục và
audit, tất cả thao tác qua web:

1. Crawl job tự động phát hiện đơn `waiting` (2D) trên Printerval, claim (`ntth`), lưu
   thẳng vào Postgres — hiện lên web cho admin xem.
2. Designer tự offer số lượng trên web (hoặc admin gán tay) → hệ thống chọn cụ thể order
   theo thuật toán FIFO/contiguous-block, tạo assignment draft.
3. Admin duyệt assignment trên web (Approve/Cancel). Đơn đã làm/không hợp lệ bị hủy, trả
   lại quota để bù đơn.
4. Designer thấy task trên web, tự cập nhật sub-status, dán link Drive, bấm nộp — vào
   hàng chờ QC nội bộ.
5. Admin QC trên web: **duyệt**, **chỉnh sửa**, **bỏ qua**, hoặc **hủy + phản hồi**. Chỉ
   khi **Approve**, job nền mới tự động gắn link lên Printerval và verify chuyển
   `doing → review`. Khi designer sửa xong, hệ thống nhận diện version kết quả mới và tạo
   QC request mới.

### Chỉ số thành công V1

- Không giao task hoặc submit kết quả trùng khi worker retry.
- Mọi hành động nghiệp vụ có người/hệ thống thực hiện, thời gian, request ID, kết quả và
  bằng chứng.
- Lỗi thao tác ngoài hệ thống có thể retry an toàn hoặc đi vào hàng đợi xử lý thủ công,
  hiển thị trên web.
- Không có thay đổi không đảo ngược hoặc quyết định QC nào vượt qua approval gate.
- Admin/designer truy được ngay trên web: đơn đang ở đâu, ai đang phụ trách, đã xảy ra gì.
- Chỉ đơn đã Approve QC mới chạm tới Printerval — Edit/Skip/Cancel không đụng site khách.

## 2. Nguyên tắc kiến trúc

- **PostgreSQL là source of truth.** Sheet và Printerval chỉ là hệ thống tích hợp/archive,
  không phải nơi quyết định trạng thái thật.
- **State machine thay vì phán đoán của con người/LLM.** Backend luôn kiểm tra transition
  và điều kiện trước khi đổi state — web route không tự ý update DB.
- **Web dashboard là giao diện duy nhất.** Không có Telegram, không có LLM trong V1.
- **Business-level tools.** Ví dụ `claim_batch`, `decide_assignment`,
  `submit_approved_result_to_site`; tuyệt đối không expose `click`, `type`,
  `find_element` của Playwright.
- **Con người duyệt phân đơn và QC.** Form/HTMX action trên web chỉ xử lý approval record
  đã tạo ở server, có CSRF token, không dựa vào state client-side.
- **Idempotency mặc định.** Mọi tool ghi dữ liệu phải có idempotency key; side effect bên
  ngoài được lưu trước/sau và xác minh.
- **Quan sát trước, tự động hóa sau.** Bắt đầu bằng dry-run, reconciliation read-only và
  pilot batch nhỏ.
- **QC trước, submit-site sau.** Đảo thứ tự so với thiết kế Telegram cũ để tránh phải gắn
  rồi gỡ link trên Printerval khi QC từ chối.

## 3. Kiến trúc V1 đích

```text
                 ┌─────────────────────────────┐
                 │   Web Dashboard (FastAPI)    │
                 │  Jinja2 + HTMX + Alpine.js   │
                 │  role: admin | designer      │
                 └───────────────┬─────────────┘
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
           (đơn mới, 2D)  (link→site)  (archive)    → Printerval (1 site)
```

### Stack đề xuất

| Tầng | Chọn cho V1 |
|---|---|
| Web / API | Python 3.12, FastAPI, Jinja2 + HTMX + Alpine.js (server-rendered, không SPA riêng) |
| Domain / dữ liệu | Pydantic v2, SQLAlchemy 2, Alembic |
| Worker / workflow nền | Celery hoặc Dramatiq với Redis; transactional outbox cho crawl job, submit-to-site job, Sheet export job |
| CSDL | PostgreSQL 16 chạy Docker/OrbStack; backup mã hóa hằng ngày |
| Browser automation | **Playwright** + Chrome thật (`channel="chrome"`, không headless — Cloudflare chặn Chromium headless); explicit wait và lưu bằng chứng lỗi |
| Sheets / Drive | Google Sheets API + Drive API — Sheet chỉ archive một chiều |
| Auth | Session cookie + bảng `users` (role admin/designer); không OAuth trong V1 |
| Quan sát | JSON structured logs, dashboard đơn giản trên chính web (queue depth, exception, retry) |

Không có Telegram, không có LLM/Qwen trong V1 (xem mục 9 "Ngoài phạm vi V1" và mục 10
"Hướng V2"). Các luồng xác định, approval và reconciliation phải chạy được độc lập với bất
kỳ thành phần AI nào — vì V1 không có thành phần đó.

## 4. Workflow/state machine chuẩn

| Internal state | Ý nghĩa | State tiếp theo chính |
|---|---|---|
| `DISCOVERED` | Đã phát hiện trên Printerval, chưa claim | `CLAIMED_IMPORTED` / `EXCEPTION` |
| `CLAIMED_IMPORTED` | Đã claim (`ntth`), asset đã tải và xác minh, Printerval đã `doing` | `OPEN_FOR_ALLOCATION` |
| `OPEN_FOR_ALLOCATION` | Chờ designer offer hoặc admin gán tay | `ASSIGNMENT_PENDING_APPROVAL` |
| `ASSIGNMENT_PENDING_APPROVAL` | Phân đơn dự kiến đã gửi admin duyệt | `ASSIGNED` / `OPEN_FOR_ALLOCATION` / `EXCEPTION` |
| `ASSIGNED` | Admin đã duyệt | `IN_PROGRESS` |
| `IN_PROGRESS` | Designer đang làm, có thể thấy sub-status (doing/fixing) | `RESULT_SUBMITTED` / `REASSIGNMENT_REQUIRED` |
| `RESULT_SUBMITTED` | Designer đã dán link Drive + bấm nộp trên web | `QC_PENDING` |
| `QC_PENDING` | Đợi admin QC quyết định trên web | `SUBMITTING_TO_SITE` / `REVISION_REQUESTED` / `SKIPPED` / `CANCELLED` |
| `SUBMITTING_TO_SITE` | QC đã Approve, job nền đang gắn link lên Printerval và verify | `DONE` / `EXCEPTION` |
| `REVISION_REQUESTED` | Đã có feedback yêu cầu designer sửa | `IN_PROGRESS` |
| `SKIPPED` | Printerval sẽ tự đổi trạng thái (do phía khách xử lý); cần reconcile | kết thúc sau khi reconcile |
| `DONE` / `CANCELLED` | Hoàn tất / hủy có lý do | terminal |
| `EXCEPTION` | Cần operator xử lý trên web | chỉ recovery transition đã ghi rõ |

`REASSIGNMENT_REQUIRED` không được ghi đè im lặng: phải release assignment lỗi, giữ bằng
chứng hủy, cập nhật số đơn còn thiếu của designer và chọn đơn thay thế từ danh sách hợp lệ.

## 5. Phases, deliverables và acceptance criteria

### Phase 0 — Khảo sát và baseline an toàn (đã hoàn tất phần lớn)

**Deliverables**

- Từ điển status và bản đồ trường dữ liệu Printerval — đã có ở `docs/phase0-field-map.md`.
- Xác nhận Playwright + Chrome thật vượt Cloudflare.
- Chính sách quyền, approval, retry và tiêu chí nhận biết "đơn đã làm" — **còn nợ** (mục
  17 #1 claude.md).

**Acceptance criteria**

- Mỗi thao tác thủ công map được sang một command và một kết quả xác minh.
- Có unique identifier ổn định cho từng order (`DJ#######`).
- Stakeholder chấp thuận state machine V1 và các human gate — spec đã duyệt ở
  `docs/superpowers/specs/2026-09-06-web-dashboard-design.md`.

### Phase 1 — Nền tảng và mô hình dữ liệu

**Deliverables**

- Project skeleton, môi trường local, migration, kiểm tra cấu hình, CI cho lint/test.
- Schema: `users`, `orders`, `order_assets`, `batches`, `assignments`, `result_versions`,
  `external_refs`, `approval_requests`, `approval_decisions`, `workflow_events`,
  `operations`, `outbox`, `dead_letters`.
- Module state machine và audit event append-only.
- Role: `admin`, `designer` (bảng `users`).
- Auth cơ bản (session cookie, password hash).

**Acceptance criteria**

- Transition atomic, có audit và từ chối transition không hợp lệ.
- Cùng write request chạy lại không tạo side effect thứ hai.
- Demonstrate được migration, backup và restore.
- Đăng nhập được với 2 role, route phân quyền đúng.

### Phase 2 — Adapter tích hợp xác định

**Deliverables**

- Adapter Printerval (Playwright, một adapter duy nhất, cùng 1 site): lọc đơn 2D
  `waiting`, claim `ntth`, tải asset, đổi/xác minh status, lấy detail đơn, kiểm tra đơn đã
  làm, submit kết quả (gắn link Drive).
- Adapter Google Sheets: export archive một chiều; Drive: verify URL/quyền/tồn tại.
- Playwright reliability package: session, explicit wait, retry có giới hạn,
  screenshot/HTML khi lỗi, kiểm tra selector.

**Acceptance criteria**

- Mỗi adapter trả typed result: external ID/status, evidence và error class.
- Timeout sau click vẫn reconcile được trước khi retry, không ghi đúp.
- Reconciliation report chỉ rõ sai khác DB–Sheet–Printerval.

### Phase 3 — Crawl & claim (C1)

**Deliverables:** job nền `discover_waiting_orders` + `claim_batch` + `import_claimed_batch`
chạy định kỳ; web hiển thị danh sách "Đơn mới"; exception queue trên web.

**Acceptance criteria:** pilot 10 rồi 100 đơn có số liệu khớp (claimed/imported/
status-updated/failed/pending); không `CLAIMED_IMPORTED` khi thiếu asset chưa xác minh;
rerun chỉ tiếp tục phần dang dở; crawl lại không tạo đơn trùng.

### Phase 4 — Web dashboard khung

**Deliverables:** khung web (layout, nav theo role), màn hình danh sách đơn (filter theo
status/batch/designer), màn hình chi tiết đơn, đăng nhập/đăng xuất, phân quyền route.

**Acceptance criteria:** admin thấy toàn bộ đơn, designer chỉ thấy đơn của mình; UI hiển
thị đúng state hiện tại và lịch sử event của từng đơn.

### Phase 5 — Phân bổ và approval (C2–C3)

**Deliverables**

- Màn "offer" trên web để designer tự đăng ký số lượng, kèm capacity ledger.
- Allocation service (bản tham chiếu) chọn chính xác các order có sẵn và tạo draft —
  thuật toán V1 đã chốt: FIFO theo thứ tự request, cấp khối liền kề trên danh sách order
  còn `unassigned` của batch; giữ chỗ bằng transaction tuần tự hóa (lock theo order) để
  tránh 2 designer nhận trùng order khi offer gần như đồng thời. Không ưu tiên theo skill
  trong V1. Chi tiết: claude.md §3 C2. Đặt sau interface riêng để sau này cắm tool FIFO
  thật đã có sẵn (claude.md §17 #9).
- Màn admin gán tay cho trường hợp đặc biệt — cùng đi qua assignment draft + approval,
  không bypass.
- Validation Printerval và màn duyệt **Approve** / **Cancel** trên web.
- Cancel phải lưu lý do, release order, khôi phục quota cần bù và tạo nhiệm vụ bù đơn.

**Acceptance criteria:** request idempotent, có quyền; cancel không âm thầm thay đơn;
không đơn nào xuất hiện ở task view designer trước khi admin approve.

### Phase 6 — Task view designer & nộp kết quả (C4)

**Deliverables:** màn "Task của tôi" cho designer — xem đơn được giao, deadline, cập nhật
sub-status (doing/fixing/done), form dán link Drive + nộp; validate link Drive
(URL/quyền/tồn tại) trước khi tạo `result_version`.

**Acceptance criteria:** nộp trùng không tạo `result_version` trùng; link không hợp lệ bị
chặn kèm thông báo rõ; mỗi lần nộp lại (sau Edit) tạo version mới, giữ lịch sử version cũ.

### Phase 7 — QC loop & submit-to-site (C5)

**Deliverables**

- Màn QC trên web: **Approve**, **Edit**, **Skip**, **Cancel + Reply**.
- Job nền `submit_approved_result_to_site`: chỉ chạy sau **Approve**, gắn link Drive lên
  Printerval, verify chuyển trạng thái đích, xử lý `UNKNOWN_OUTCOME`.
- Gửi feedback (Edit/Cancel) lưu vào outbox; nhận diện result version mới → tạo QC
  approval request mới; timed reconciliation cho `SKIPPED`.

**Acceptance criteria:** quyết định QC có admin, thời gian, comment/lý do và evidence; chỉ
re-review sau khi có result mới xác minh; request đã xử lý không có effect lần hai; Edit/
Skip/Cancel không bao giờ gọi tới Playwright submit; chỉ Approve mới gọi.

### Phase 8 — Sheet export, monitoring, vận hành ổn định

**Deliverables:** job export archive một chiều ra Sheet (idempotent theo `exported_at`);
runbook, alert, dashboard đơn giản trên web (queue depth, exception, approval age), backup/
restore drill, quy trình khi selector hỏng, kill switch dừng Playwright write.

**Acceptance criteria:** export không trùng dòng khi chạy lại; admin tự điều tra và
recover được theo runbook; backup/restore drill pass.

## 6. Testing và release

- **Unit:** state transition, allocation (bản tham chiếu), idempotency, quyền, retry
  policy.
- **Contract:** fake adapter Printerval (Playwright)/Google theo tool contract.
- **Integration:** test DB, sandbox Sheet/Drive.
- **E2E:** happy path, duplicate request, timeout sau write, đơn đã làm, Drive link lỗi,
  selector hỏng, QC revision, crawl dedupe, submit-to-site chỉ chạy sau Approve.
- **Load/soak:** pilot 100 đơn với rate limit; không tăng song song browser write trước
  khi chứng minh an toàn.
- **Shadow mode:** chỉ ghi action đề xuất, không write Printerval; so sánh với quy trình
  thủ công.
- **Canary:** 5–10 đơn thật → 25 → 100 sau khi reconciliation sạch.

## 7. Deployment, bảo mật và rủi ro

- Chạy dịch vụ bằng Compose/OrbStack; worker tách process, Postgres có persistent volume.
- Dùng Chrome profile/account riêng cho Playwright; không dùng chung session browser cá
  nhân.
- Lưu secret trong Keychain/1Password CLI/secret store được duyệt; `.env` chỉ local,
  không commit.
- Backup Postgres hằng ngày, bản sao mã hóa ngoài máy, chính sách retention và restore
  test.
- Alert khi dead-letter, approval quá hạn, state bị kẹt, mismatch, selector lỗi lặp lại,
  submit lỗi.
- Có kill switch dừng browser write nhưng vẫn cho read/reconcile.
- Session cookie httponly/secure; rate limit đăng nhập.

| Rủi ro | Giảm thiểu |
|---|---|
| Website đổi UI/selector | contract test, screenshot, selector health check, manual fallback/runbook |
| Không chắc thao tác đã thành công sau timeout | idempotency, operation ledger, read-after-write, reconcile trước retry |
| Sheet bị sort/sửa row | hidden/protected UUID; không dùng row number làm identity |
| Admin duyệt nhầm | CSRF token, role check, single-use decision, context rõ, expiry, audit |
| Race khi browser write song song | lock theo order/batch, serialized status mutation, concurrency có giới hạn |
| 50 designer + 10 admin cùng thao tác trên web | DB transaction/lock cho allocation, session riêng từng user, rate limit route ghi |

## 8. Ngoài phạm vi V1

- Tool phân bổ FIFO production thật (dùng bản tham chiếu, tích hợp tool thật sau).
- Telegram (dưới mọi hình thức, kể cả thông báo).
- LLM/agent dưới mọi hình thức.
- QC tự động hoặc tự diễn giải nội dung khách.
- Payroll, phân tích/báo cáo nâng cao, dashboard BI.
- Đa loại design job ngoài 2D (3D/ART/WOOD/CALENDAR/EMBROIDERY/AI).
- OAuth/SSO, đa tài khoản Printerval, multi-tenant/SaaS, HA đa máy.
- Cơ chế điểm/phạt designer trên Printerval (đồng bộ vào Postgres) — chưa xác nhận cần
  hay không (claude.md §17 #7).

## 9. Hướng V2

- Thêm lại Telegram như kênh **thông báo phụ** (không thao tác) khi có task mới/QC mới.
- Optional local LLM agent (Qwen hoặc tương đương) ngồi trên MCP façade, tuân thủ
  claude.md §12/§12.1 — không thay thế web.
- Tích hợp tool phân bổ FIFO production thật đã có sẵn (thay bản tham chiếu).
- Dashboard nâng cao: capacity, SLA, audit search; tối ưu phân đơn theo skill/deadline/
  priority/workload.
- Đồng bộ cơ chế điểm/phạt designer từ Printerval nếu xác nhận cần.
- Mở rộng loại job ngoài 2D nếu team mở rộng phạm vi làm việc.

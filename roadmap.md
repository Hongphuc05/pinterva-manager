# AI Operations Agent — Roadmap V1

> **Phiên bản:** V1  
> **Mục tiêu:** Xây hệ thống vận hành nội bộ đáng tin cậy để điều phối nhận đơn, chia đơn, sản xuất, duyệt và QC giữa website khách, Google Sheets/Drive và Telegram. AI chỉ hỗ trợ hiểu yêu cầu, tóm tắt và đề xuất có kiểm soát; mọi thay đổi trạng thái phải do workflow xác định thực hiện.

## 1. Kết quả cần đạt

Hệ thống xử lý một batch đơn hàng từ đầu đến cuối theo luồng có thể kiểm tra, khôi phục và audit:

1. Nhận các đơn `waiting` trên website khách, đổi designer sang `ntth` để claim đơn.
2. Lọc `waiting + ntth`, tải ảnh, đưa dữ liệu vào Google Sheet, rồi đổi trạng thái website khách `waiting → doing` nhưng vẫn giữ `ntth`.
3. Thông báo Telegram để designer đăng ký số lượng; ghi cụ thể designer vào các dòng đơn trên Sheet.
4. Đối chiếu từng đơn với website khách và gửi admin duyệt trên Telegram. Đơn đã làm/không hợp lệ bị hủy, trả lại quota để bù đơn ở B3.
5. Chỉ các đơn đã duyệt mới được copy sang Sheet 2, phân phát tới bảng riêng của designer và kéo link Drive kết quả về bảng tổng.
6. Đẩy kết quả lên website khách, xác minh chuyển `doing → review`.
7. Gửi đơn ở review sang Telegram cho QC quyết định **duyệt**, **chỉnh sửa**, **bỏ qua**, hoặc **hủy + phản hồi**. Khi designer sửa xong, hệ thống nhận diện version kết quả mới và đưa đơn quay lại review.

### Chỉ số thành công V1

- Không phát đơn hoặc submit kết quả trùng khi worker retry.
- Mọi hành động nghiệp vụ có người/hệ thống thực hiện, thời gian, request ID, kết quả và bằng chứng.
- Lỗi thao tác ngoài hệ thống có thể retry an toàn hoặc đi vào hàng đợi xử lý thủ công.
- Không có thay đổi không đảo ngược hoặc quyết định QC nào vượt qua approval gate.
- Operator truy được ngay: đơn đang ở đâu, ai đang phụ trách và đã xảy ra những gì.

## 2. Nguyên tắc kiến trúc

- **PostgreSQL là source of truth.** Sheet và website chỉ là hệ thống tích hợp/projection, không phải nơi quyết định trạng thái thật.
- **State machine thay vì phán đoán của LLM.** Backend luôn kiểm tra transition và điều kiện trước khi đổi state.
- **LLM chỉ làm ở tầng nghiệp vụ.** LLM hiểu intent từ Telegram, lập kế hoạch, tóm tắt ngoại lệ, gọi business tool an toàn; không thấy HTML, selector, tọa độ hay lệnh Selenium thấp cấp.
- **Business-level tools.** Ví dụ `claim_batch`, `approve_assignment`, `submit_result_for_review`; tuyệt đối không expose `click`, `type`, `find_element`.
- **Con người duyệt phân đơn và QC.** Telegram button chỉ xử lý approval record đã tạo ở server, không dựa vào text tự do.
- **Idempotency mặc định.** Mọi tool ghi dữ liệu phải có idempotency key; side effect bên ngoài được lưu trước/sau và xác minh.
- **Quan sát trước, tự động hóa sau.** Bắt đầu bằng dry-run, reconciliation read-only và pilot batch nhỏ.

## 3. Kiến trúc V1 đích

```text
Telegram / chat của operator
        │
        ▼
FastAPI chat gateway ──► Agent Orchestrator (Qwen, tool calling)
        │                         │
        ├──────────► PostgreSQL ◄──┤ workflow/state-machine service
        │               │          │
        │               ├── audit events / approval records / outbox
        │               ▼
        │             Redis (queue, lock, rate limit; có thể thêm sau)
        ▼
Business tool / MCP gateway
 ├─ Adapter website khách ─ Selenium execution worker
 ├─ Adapter Google Sheets + Drive ─ API / Apps Script
 └─ Adapter Telegram ─ message, button, callback verification
```

### Stack đề xuất cho MacBook Pro M3 Pro 32GB

| Tầng | Chọn cho V1 |
|---|---|
| API / điều phối | Python 3.12, FastAPI, Pydantic, SQLAlchemy, Alembic |
| Worker / workflow nền | Celery hoặc Dramatiq với Redis; transactional outbox cho tác vụ quan trọng |
| CSDL | PostgreSQL 16 chạy Docker/OrbStack; backup mã hóa hằng ngày |
| Browser automation | Selenium 4 + Chrome profile riêng của service; explicit wait và lưu bằng chứng lỗi |
| Sheets / Drive | Google Sheets API + Drive API; Apps Script chỉ cho tác vụ cục bộ của Sheet |
| Telegram | `python-telegram-bot` hoặc `aiogram`; callback được ký/xác minh |
| LLM runtime | MLX-LM ưu tiên trên Apple Silicon; endpoint tương thích OpenAI khi phù hợp |
| LLM | Thử Qwen3-30B-A3B quantized trước; Qwen3-14B quantized là phương án fallback ổn định hơn |
| Quan sát | JSON structured logs, OpenTelemetry, Sentry hoặc tương đương, dashboard đơn giản |

Các luồng xác định, approval và reconciliation vẫn phải chạy được khi LLM không hoạt động.

## 4. Workflow/state machine chuẩn

Lưu **internal state** riêng (nhiều state hơn status thô của website, vì cần theo dõi thêm assignment/approval/QC nội bộ), đồng thời lưu trạng thái quan sát được từ website khách.

| Internal state | Ý nghĩa | State tiếp theo chính |
|---|---|---|
| `DISCOVERED` | Đã phát hiện trên website khách, chưa claim | `CLAIMED` / `EXCEPTION` |
| `CLAIMED` | Designer đã là `ntth`, web vẫn waiting | `IMPORTED` / `EXCEPTION` |
| `IMPORTED` | Sheet/asset đã xác minh; website khách đã doing | `OPEN_FOR_SIGNUP` |
| `OPEN_FOR_SIGNUP` | Chờ designer đăng ký/chia đơn | `ASSIGNMENT_PENDING_APPROVAL` |
| `ASSIGNMENT_PENDING_APPROVAL` | Phân đơn dự kiến đã gửi admin duyệt | `ASSIGNED` / `OPEN_FOR_SIGNUP` / `EXCEPTION` |
| `ASSIGNED` | Admin đã duyệt, đã tạo projection sang Sheet 2 | `DISPATCHED` |
| `DISPATCHED` | Đã có ở bảng riêng của designer | `RESULT_RECEIVED` / `REASSIGNMENT_REQUIRED` |
| `RESULT_RECEIVED` | Link Drive kết quả đã hợp lệ ở bảng tổng | `SUBMITTED_FOR_REVIEW` |
| `SUBMITTED_FOR_REVIEW` | Đã post lên website khách và xác minh review | `QC_PENDING` |
| `QC_PENDING` | Đợi admin QC bấm quyết định | `DONE` / `REVISION_REQUESTED` / `SKIPPED` / `CANCELLED` |
| `REVISION_REQUESTED` | Đã có feedback yêu cầu designer sửa | `DISPATCHED` |
| `SKIPPED` | Website khách sẽ tự đổi trạng thái (do phía khách xử lý); cần reconcile | kết thúc sau khi reconcile |
| `DONE` / `CANCELLED` | Hoàn tất / hủy có lý do | terminal |
| `EXCEPTION` | Cần operator xử lý | chỉ recovery transition đã ghi rõ |

`REASSIGNMENT_REQUIRED` không được ghi đè im lặng: phải release assignment lỗi, giữ bằng chứng hủy, cập nhật số đơn còn thiếu của designer và chọn đơn thay thế từ danh sách hợp lệ.

## 5. Phases, deliverables và acceptance criteria

### Phase 0 — Khảo sát và baseline an toàn

**Deliverables**

- Từ điển status chính xác và rule chuyển status của website khách.
- SOP/video một đơn đi đủ luồng, bao gồm hủy và QC revision.
- Test account, test order, browser profile, giới hạn tốc độ thao tác.
- Bản đồ trường dữ liệu: order/image ID, sheet row key, designer ID, result link, comment, deadline.
- Chính sách quyền, approval, retry và tiêu chí nhận biết “đơn đã làm”.

**Acceptance criteria**

- Mỗi thao tác thủ công map được sang một command và một kết quả xác minh.
- Có unique identifier ổn định cho từng order; nếu không có phải quy định composite key.
- Stakeholder chấp thuận state machine V1 và các human gate.

### Phase 1 — Nền tảng và mô hình dữ liệu

**Deliverables**

- Project skeleton, môi trường local, migration, kiểm tra cấu hình, CI cho lint/test.
- Schema: `orders`, `order_assets`, `batches`, `designers`, `assignments`, `external_refs`, `approval_requests`, `workflow_events`, `operations`, `outbox`, `dead_letters`.
- Module state machine và audit event append-only.
- Role: operator, allocator, QC admin, system worker.
- Lệnh/dashboard tối thiểu để xem trạng thái và reconciliation read-only.

**Acceptance criteria**

- Transition atomic, có audit và từ chối transition không hợp lệ.
- Cùng write request chạy lại không tạo side effect thứ hai.
- Demonstrate được migration, backup và restore.

### Phase 2 — Adapter tích hợp xác định

**Deliverables**

- Adapter website khách (một adapter duy nhất, cùng 1 site): lọc đơn, claim `ntth`, tải asset, đổi/xác minh status, lấy detail đơn, kiểm tra đơn đã làm, submit kết quả, đọc ngữ cảnh review/QC.
- Adapter Google: import/sync mapping row; dispatch sheet và result link.
- Selenium reliability package: session, explicit wait, retry có giới hạn, screenshot/HTML khi lỗi, kiểm tra selector.

**Acceptance criteria**

- Mỗi adapter trả typed result: external ID/status, evidence và error class.
- Timeout sau click vẫn reconcile được trước khi retry, không ghi đúp.
- Reconciliation report chỉ rõ sai khác DB–Sheet–website.

### Phase 3 — Batch intake (B1–B2)

**Deliverables:** workflow `claim_batch`, workflow `import_claimed_batch`, Telegram/dashboard summary và exception queue.

**Acceptance criteria:** pilot 10 rồi 100 đơn có số liệu khớp (claimed/imported/status-updated/failed/pending); không `IMPORTED` khi thiếu asset hoặc row mapping; rerun chỉ tiếp tục phần dang dở.

### Phase 4 — Signup, phân đơn, approval (B3–B4)

**Deliverables**

- Telegram flow để designer đăng ký số lượng, kèm capacity ledger.
- Allocation service chọn chính xác các order có sẵn và tạo draft — thuật toán V1 đã chốt: FIFO theo thứ tự đăng ký, cấp khối liền kề trên danh sách order còn `unassigned` của batch (designer đăng ký trước nhận khối trước); giữ chỗ bằng transaction tuần tự hóa (lock theo order) để tránh 2 designer nhận trùng order khi đăng ký gần như đồng thời. Không ưu tiên theo skill trong V1. Chi tiết: claude.md §3 B3.
- Assignment approval gửi vào group chat chung, nhiều admin cùng quyền bấm, quyết định đầu tiên hợp lệ thắng (claude.md §10).
- Validation website khách và Telegram card **Approve** / **Cancel**.
- Cancel phải lưu lý do, release row, khôi phục quota cần bù và tạo nhiệm vụ bù đơn.
- Chỉ copy assignment đã approved sang Sheet 2.

**Acceptance criteria:** callback single-use, có quyền, idempotent; cancel không âm thầm thay đơn; không đơn nào xuất hiện trong bảng designer trước approval.

### Phase 5 — Dispatch và nhận kết quả (B5)

**Deliverables:** worker phân phát sang bảng designer; collector kiểm tra link Drive, lưu version/timestamp và sync về bảng tổng; quy trình xử lý link lỗi/thiếu hoặc reassign.

**Acceptance criteria:** event Sheet trùng không tạo dispatch/result trùng; result link gắn với order/assignment cụ thể; bảng tổng dựng lại được từ PostgreSQL.

### Phase 6 — Submit và QC loop (B6–B7)

**Deliverables**

- Submit result hợp lệ lên website khách và xác minh `doing → review`.
- QC Telegram card: **Approve**, **Edit**, **Skip**, **Cancel + Reply**.
- Gửi feedback, nhận diện result version mới, resubmit review; timed reconciliation cho `SKIPPED`.

**Acceptance criteria:** quyết định QC có admin, thời gian, comment/lý do và evidence; chỉ re-review sau khi có result mới xác minh; callback đã xử lý không có effect lần hai.

### Phase 7 — Agent interface và vận hành ổn định

**Deliverables:** local Qwen agent để hỏi status/summary/dry-run/exceptions; MCP gateway schema chặt chẽ; runbook, alert, dashboard, backup/restore drill, quy trình khi selector hỏng.

**Acceptance criteria:** agent không thể gọi Selenium thấp cấp hoặc bypass policy; workflow core chạy khi tắt LLM; operator tự điều tra và recover được theo runbook.

## 6. Testing và release

- **Unit:** state transition, allocation, idempotency, quyền, callback signature, retry policy.
- **Contract:** mock adapter web/Google/Telegram theo tool contract.
- **Integration:** test DB, sandbox Sheet/Drive và Telegram group test.
- **E2E:** happy path, duplicate, timeout sau write, stale callback, đơn đã làm, Drive link lỗi, selector hỏng, QC revision.
- **Load/soak:** pilot 100 đơn với rate limit; không tăng song song browser write trước khi chứng minh an toàn.
- **Shadow mode:** chỉ ghi action đề xuất, không write website; so sánh với quy trình thủ công.
- **Canary:** 5–10 đơn thật → 25 → 100 sau khi reconciliation sạch.

## 7. Deployment, bảo mật và rủi ro

- Chạy dịch vụ bằng Compose/OrbStack; worker tách process, Postgres có persistent volume.
- Dùng Chrome profile/account riêng; không dùng chung session browser cá nhân.
- Lưu secret trong Keychain/1Password CLI/secret store được duyệt; `.env` chỉ local, không commit.
- Backup Postgres hằng ngày, bản sao mã hóa ngoài máy, chính sách retention và restore test.
- Alert khi dead-letter, approval quá hạn, state bị kẹt, mismatch, selector lỗi lặp lại, submit lỗi.
- Có kill switch dừng browser write nhưng vẫn cho read/reconcile.

| Rủi ro | Giảm thiểu |
|---|---|
| Website đổi UI/selector | contract test, screenshot, selector health check, manual fallback/runbook |
| Không chắc thao tác đã thành công sau timeout | idempotency, operation ledger, read-after-write, reconcile trước retry |
| Sheet bị sort/sửa row | hidden/protected UUID; không dùng row number làm identity |
| Admin duyệt nhầm Telegram | allowlist role, callback ký/single-use, context rõ, expiry, audit |
| Local LLM chậm/tắt | workflow độc lập LLM; Qwen 14B fallback; giới hạn tool turn/context |
| Race khi browser write song song | lock theo order/batch, serialized status mutation, concurrency có giới hạn |

## 7b. Bối cảnh đã xác nhận và quyết định còn mở

Xem chi tiết đầy đủ ở `claude.md` §16–17 (bối cảnh vận hành đã xác nhận + bảng nợ kỹ thuật). Tóm tắt ảnh hưởng roadmap:

- Website khách là **một site duy nhất** cho toàn bộ luồng (claim, doing, review, done — không tách "web mẹ"/"web khách"), công ty vận hành qua **một tài khoản cố định** khách cấp → không cần thiết kế adapter đa-site/đa-account ở Phase 2.
- Khối lượng đỉnh **vài trăm order/ngày** → xác nhận Redis/Celery/Dramatiq đưa vào từ V1 (mục 3) là đúng mức, không hoãn được xuống V2.
- Concurrency Selenium, nơi lưu `order_assets`, tiêu chí "đơn đã làm", và cấu hình phần cứng production 24/7 **chưa chốt** — theo dõi ở claude.md §17, không block Phase 0–1.

## 8. Ngoài phạm vi V1

- QC tự động hoặc tự diễn giải nội dung khách.
- Multi-agent hierarchy, tối ưu workforce tự động.
- Thay thế hoàn toàn Google Sheets.
- Dashboard BI đầy đủ, multi-tenant/SaaS, HA đa máy.
- Fine-tune, vector DB/RAG lớn, general-purpose browser control cho LLM.

## 9. Hướng V2

- Dashboard cho queue, exception, capacity, SLA và audit search.
- Tối ưu phân đơn theo skill, deadline, priority, workload.
- RAG/SOP versioned để hỗ trợ operator, không có quyền đổi state.
- Adapter API-first cho các website có API, analytics/forecasting và hỗ trợ partial order.

# Web Dashboard V1 — Thiết kế kiến trúc

> Thay thế hoàn toàn định hướng "Telegram + Qwen 14B điều khiển workflow" ở bản
> claude.md/roadmap.md gốc. Đây là spec kiến trúc cho hướng đi mới: **web dashboard nội bộ
> là giao diện chính**, MCP/adapter là lớp tích hợp, Postgres vẫn là source of truth duy
> nhất. Các bất biến ở claude.md §2 (append-only audit, idempotency, human approval cho
> 4 nhóm quyết định...) **giữ nguyên** — spec này chỉ thay lớp giao diện/kênh tương tác và
> rút gọn số bước nghiệp vụ, không thay đổi triết lý an toàn/reliability.

## 1. Bối cảnh & lý do đổi hướng

Bản thiết kế gốc dùng Telegram làm giao diện chính cho admin/designer, có Qwen 14B hỗ trợ
điều phối. Qua khảo sát thực tế (Phase 0) và trao đổi, xác định:

- Luồng B1–B7 gốc có nhiều bước thừa (Sheet trung gian cho intake/dispatch/thu kết quả,
  submit-lên-site trước khi QC nội bộ) — cần rút gọn.
- Telegram không còn phù hợp làm giao diện chính khi quy mô ~50 designer + 10 admin cần
  theo dõi trạng thái trực quan, có lịch sử, có thể lọc/tìm kiếm.
- Đã có sẵn 1 tool phân bổ đơn (FIFO/contiguous-block) chạy ổn định ở nơi khác — V1 không
  cần viết lại tool production, chỉ cần viết bản tham chiếu đúng thuật toán để test và chừa
  interface để sau này gọi tool thật.
- Playwright (không phải Selenium) đã được xác nhận vượt qua được chặn Cloudflare của
  Printerval khi dùng Chrome thật, không headless.

## 2. Quyết định đã chốt (tóm tắt, tham chiếu các câu hỏi brainstorming)

| # | Quyết định |
|---|---|
| 1 | Web dashboard là giao diện **duy nhất** cho V1. **Telegram bỏ hẳn khỏi V1** (có thể thêm lại sau như kênh thông báo, không phải kênh thao tác). |
| 2 | 2 role cố định: **admin** (toàn quyền quản lý, duyệt assignment, duyệt QC), **designer** (xem task được giao, tự offer nhận đơn, cập nhật trạng thái làm việc, nộp kết quả). |
| 3 | MCP/adapter là lớp tích hợp 2 chiều (đọc quan sát + ghi hành động) cho: Printerval website, Google Sheets, Google Drive. Không có adapter Telegram trong V1. |
| 4 | V1 tối thiểu: quản lý đơn + duyệt (assignment/QC) + task view cho designer. Không có payroll, analytics, báo cáo nâng cao. |
| 5 | Phân bổ đơn (B3) **không tự viết lại production** — dùng interface adapter riêng để sau này cắm tool thật đã có sẵn; V1 viết bản tham chiếu đúng thuật toán FIFO/contiguous-block để test. |
| 6 | Đơn/assignment **không** gán tay hoàn toàn tự do — admin có thể gán tay cho trường hợp đặc biệt, nhưng cơ chế chính là designer tự "offer" số lượng → hệ thống tự động chọn khối liền kề (logic deterministic, không đổi so với bản gốc). |
| 7 | Triển khai: nội bộ (LAN), ~50 designer + 10 admin, đăng nhập user/pass đơn giản (không OAuth). |
| 8 | Playwright thay Selenium cho adapter Printerval. |
| 9 | Google Sheets giữ vai trò **archive một chiều** (xuất báo cáo/lưu trữ theo ngày), không phải nơi thao tác, không đọc ngược lại để quyết định state. |
| 10 | Phạm vi loại design job V1: **chỉ 2D** (lọc cứng `type=2D` trong crawl/adapter). |
| 11 | Thứ tự submit-lên-site và QC nội bộ **đảo lại** so với bản gốc: QC nội bộ xảy ra **trước**, chỉ khi admin Approve mới tự động gắn link lên Printerval — tránh phải gắn-rồi-gỡ khi bị từ chối. |

## 3. Kiến trúc tổng thể

```
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

- **Web dashboard = giao diện duy nhất.** Server-rendered (FastAPI + Jinja2 + HTMX cho phần
  cập nhật động — danh sách đơn, nút approve — + Alpine.js cho tương tác nhỏ). Không dựng
  SPA riêng: quy mô 60 người dùng nội bộ không cần, và tránh thêm build pipeline/codebase
  thứ hai.
- **PostgreSQL** vẫn là source of truth duy nhất cho state và audit history (bất biến #1
  giữ nguyên).
- **Redis + Celery/Dramatiq** chạy job nền:
  - Crawl job: định kỳ quét đơn `waiting` (2D, scoped theo tài khoản công ty) trên
    Printerval → upsert vào Postgres kèm claim tự động (đổi designer→ntth, verify).
  - Submit-to-site job: chỉ chạy **sau khi** admin Approve QC — tự động gắn link Drive lên
    Printerval + verify chuyển trạng thái.
  - Sheet export job: định kỳ (vd cuối ngày) xuất snapshot đơn trong ngày ra Google Sheet để
    lưu trữ/tra cứu.
- **Business tools/MCP façade:** giữ nguyên nguyên tắc claude.md §7/§8 — tool hẹp, typed,
  Pydantic-validated, không expose Playwright primitive ra ngoài adapter.
- **Auth:** bảng `users` (role admin/designer, password hash), session cookie. Không OAuth,
  không Telegram ID mapping.

## 4. Luồng nghiệp vụ rút gọn (thay B1–B7)

| Cũ | Mới |
|---|---|
| B1 Claim + B2 Import (2 bước, có Sheet intake) | **Gộp "Crawl":** job nền tự động quét đơn `waiting` (2D) trên Printerval theo lịch, tự claim (set designer=ntth, verify), lưu thẳng Postgres kèm ảnh/metadata, hiện lên web mục "Đơn mới". Không qua Sheet. |
| B3 Chia đơn qua Telegram đăng ký | Web có 2 lối vào cùng bộ máy phân bổ FIFO: (a) designer tự "offer" số lượng ngay trên web, (b) admin gán tay khi cần đặc biệt. Cả 2 đều tạo assignment draft; logic chọn order cụ thể vẫn deterministic, không đổi so với thuật toán contiguous-block gốc. |
| B4 Duyệt qua Telegram card | Duyệt trên web (nút Approve/Cancel), cùng bảng `approval_requests/decisions`, chỉ đổi kênh hiển thị. |
| B5 Dispatch qua Sheet riêng từng designer + thu kết quả qua Sheet tổng | Bỏ Sheet trung gian — designer thấy task giao thẳng trên web, tự cập nhật trạng thái làm việc (`đang làm`/`đang sửa`/`đã xong`) ngay trên đó. |
| B6 Submit lên site (doing→review) **trước** QC | Đảo thứ tự: designer dán link Drive + bấm "Nộp" → vào hàng chờ QC nội bộ **trước**, chưa đụng Printerval. |
| B7 QC bởi admin | Admin duyệt trên web. Chỉ khi **Approve**, job nền mới tự động chạy Playwright gắn link Drive lên Printerval + verify chuyển trạng thái. Edit/Skip/Cancel không đụng Printerval. |

### State machine rút gọn

```
DISCOVERED (crawl) → CLAIMED_IMPORTED → OPEN_FOR_ALLOCATION
  → ASSIGNMENT_PENDING_APPROVAL → ASSIGNED → IN_PROGRESS
  → RESULT_SUBMITTED → QC_PENDING
        ├─ Approve → SUBMITTING_TO_SITE → DONE
        ├─ Edit     → REVISION_REQUESTED → IN_PROGRESS
        ├─ Skip     → SKIPPED (reconcile sau)
        └─ Cancel   → CANCELLED
```

Nhánh phụ giữ nguyên như bản gốc:
- `ASSIGNMENT_PENDING_APPROVAL → OPEN_FOR_ALLOCATION`: admin cancel do đơn không hợp
  lệ/đã làm (B4 cancel), release order, trả quota, chọn đơn bù.
- `IN_PROGRESS → REASSIGNMENT_REQUIRED`: designer không thể thực hiện; SLA cảnh báo tuyến
  tính như cũ (nợ kỹ thuật #2 ở claude.md, không đổi).
- `EXCEPTION`: bất kỳ state nào cũng có thể vào, kèm error class + recovery owner; chỉ
  explicit command mới ra khỏi state này.

## 5. Data model (điều chỉnh so với claude.md §6)

- `designers` → gộp vào **`users`**: thêm `role: admin|designer`, `password_hash`; bỏ
  `telegram_id`.
- `orders`, `order_assets`, `batches`, `assignments`, `result_versions`,
  `approval_requests`/`approval_decisions`, `external_refs`/`external_observations`,
  `operations`, `workflow_events`, `outbox`, `dead_letters` — giữ nguyên cấu trúc; bỏ cột
  Telegram message ref, đổi thành web session/request ref.
- Thêm field/bảng nhỏ lưu sub-status làm việc của designer (`doing/fixing/done`) — chỉ để
  hiển thị tiến độ trên web, không phải input cho state machine chính.
- Sheet export: bỏ `external_sync_version` 2 chiều (vì giờ 1 chiều), chỉ cần `exported_at`
  marker để tránh export trùng dòng.
- Unique constraint theo external order ID (Printerval) và idempotency scope — giữ nguyên
  bất biến §6.

## 6. Error handling & reconciliation

Giữ nguyên toàn bộ phân loại lỗi và bất biến ở claude.md §11, §12.1:

- Phân loại `VALIDATION/AUTH/RATE_LIMIT/TRANSIENT_NETWORK/EXTERNAL_CHANGED/UNKNOWN_OUTCOME/PERMANENT_EXTERNAL/BUG`
  không đổi.
- 4 nhóm quyết định bắt buộc dừng lại hỏi người (decide_assignment, decide_qc,
  exception/reconciliation mismatch không rõ ràng, hủy ngoài luồng approval có sẵn) áp dụng
  y hệt — chỉ khác kênh hỏi là web thay vì Telegram.
- Câu hỏi mở về `Fix`/`Confirm` trên Printerval (claude.md §17 mục #6) **không chặn thiết
  kế này**: submit-to-site job coi `review` là trạng thái đích cần verify sau khi gắn link;
  nếu Printerval trả về giá trị ngoài dự kiến (`Fix`/`Confirm` bất ngờ) → vào exception
  queue cho admin xử lý tay trên web, đúng bất biến #10.
- Playwright adapter tuân theo nguyên tắc §8 nguyên bản: stable selector, explicit wait,
  retry/backoff giới hạn, read-after-write verification, evidence khi lỗi (screenshot đã
  redact), `UNKNOWN_OUTCOME` khi không verify được sau click.

## 7. Testing

Giữ chiến lược cũ (claude.md §13), bổ sung test riêng cho phần mới:

- Fake Playwright adapter cho test (không test live credential).
- Test transition/idempotency/allocation/replacement như cũ.
- **Mới:** crawl job dedupe (không tạo trùng order khi crawl lại cùng đơn).
- **Mới:** submit-to-site job chỉ chạy sau khi QC Approve — không chạy khi Edit/Skip/Cancel.
- **Mới:** Sheet export job không xuất trùng dòng khi chạy lại (idempotent theo
  `exported_at`/operation marker).
- E2E happy path, duplicate callback, timeout-after-write, order đã hoàn tất, link lỗi,
  stale QC, result version revision, reconciliation mismatch — giữ nguyên danh sách case cũ.

## 8. Phạm vi ngoài V1 (không làm bây giờ)

- Tool phân bổ đơn (FIFO) production thật — chỉ viết bản tham chiếu để test; tích hợp tool
  thật là việc sau, qua interface/adapter riêng.
- Kênh thông báo Telegram (khi cần, thêm lại như kênh thông báo phụ, không phải kênh thao
  tác).
- Payroll, phân tích nâng cao, đa loại design job ngoài 2D.
- Đăng nhập OAuth/SSO, đa tài khoản Printerval.
- Cơ chế điểm/phạt designer trên Printerval (mục 17 #7 claude.md) — chưa xác nhận có cần
  đồng bộ vào Postgres hay không; V1 không đụng vào, chỉ quan sát nếu cần hiển thị.

## 9. Việc cần cập nhật ở claude.md / roadmap.md

- claude.md §3 (B1–B7), §4 (kiến trúc), §5 (state model), §10 (Telegram) cần viết lại theo
  spec này — Telegram bỏ khỏi kiến trúc chính, thêm mô tả web dashboard, đổi Selenium→
  Playwright ở §4/§8.
- roadmap.md cần restructure phase theo thứ tự: scaffold → state machine/domain → adapter
  Playwright (read-only) → crawl job → web dashboard khung (auth, danh sách đơn) → allocation
  (offer + admin gán tay) → approval B4 trên web → task view designer + nộp kết quả → QC
  trên web + auto-submit → Sheet export → monitoring/runbook. Bỏ hẳn phase liên quan
  Telegram/Qwen tool-calling gateway (chuyển xuống mục "ngoài V1", có thể quay lại ở V2 nếu
  cần thêm kênh thông báo).

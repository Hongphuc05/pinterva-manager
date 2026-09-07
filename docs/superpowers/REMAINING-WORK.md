# Việc còn lại — Pinterval Ops Dashboard (bàn giao 2026-09-07)

> Đọc `docs/superpowers/SESSION-SUMMARY-2026-09-07.md` trước để biết bối cảnh đầy đủ.
> File này chỉ liệt kê **việc cần làm**, theo đúng thứ tự ưu tiên.

**Chỉ đạo còn hiệu lực từ người dùng (áp dụng cho toàn bộ việc dưới đây):**
> "tao cho phép mày tự động lược bỏ một số bước không thực sự cần thiết, mục tiêu chính
> là tiết kiệm token nhiều nhất có thể" — và trước đó: chạy liên tục không dừng hỏi ý
> kiến, chỉ dừng cho 4 trường hợp cứng của `subagent-driven-development` (thao tác không
> đảo ngược được, việc nhạy cảm bảo mật, side-effect ra ngoài worktree cần hỏi trước, kế
> hoạch sai tới mức mọi hướng đều là đoán mò). Ngoài 4 trường hợp đó: **tự quyết định,
> ghi Ruling vào ledger, đi tiếp** — không dừng lại hỏi.

**Worktree:** `/Users/hongphuc/Documents/01_congViec/pinterval/.claude/worktrees/phase1-foundation`
(branch `worktree-phase1-foundation`) — **dùng tiếp worktree này, không tạo worktree
mới.** Dùng `.venv/bin/python`/`pytest`/`ruff`/`alembic` (không dùng `python3` hệ thống —
thiếu Python 3.12). Frontend ở `frontend/` (đã cài `node_modules`, dùng `npm`).

---

## 0. Sub-project 1-4/6 — ĐÃ XONG HOÀN TOÀN (không cần động vào)

Order detail mirror, frontend migration (React), allocation board (C2+C3), và designer
task view (C4) đều đã
qua đủ final review + 1 vòng fix + scoped re-review sạch. Allocation board còn được
kiểm tra bổ sung race capacity xuyên batch sau khi đóng ledger và đã có regression fix;
ledger đã đóng, workspace
`.superpowers/sdd/` của 3 sub-project đầu đã bị xoá (đúng quy trình). Toàn bộ đã commit
trên `worktree-phase1-foundation`. Chi tiết đầy đủ (kể cả các bug thật
đã tự phát hiện/sửa giữa chừng) nằm ở `docs/superpowers/SESSION-SUMMARY-2026-09-07.md`
§4. Một minor còn "parked" có chủ đích (không phải bug bỏ sót): `offer`/`assign` chưa
bắt `IdempotencyKeyReusedError` (sẽ raise 500 thay vì 409 nếu client gửi lại
`request_id` với payload khác — kịch bản hiếm, chưa có test/scenario nào chạm tới, ghi
lại để theo dõi chứ không bắt buộc sửa ngay).

**Việc còn lại thật sự bắt đầu từ sub-project 5 dưới đây.**

---

## 1. Sub-project 4/6 — Designer task view (C4) — ĐÃ XONG

Trang `/my-tasks`, service/API và tests đã hoàn tất. Designer chỉ thấy assignment
`approved` của chính họ trong state active; Start là action state-machine riêng,
sub-status chỉ hiển thị, và submit chỉ tạo `ResultVersion`/QC request sau khi adapter
Drive xác nhận URL, file tồn tại và truy cập được. Query Orders/Detail chung cũng đã
được giới hạn về assignment `approved`, nên assignment cancelled không còn lộ dữ liệu.
Không có thao tác Printerval trong C4.

Phần bối cảnh bên dưới được giữ lại làm tài liệu cho C5 và revision loop.

### Bối cảnh đã có sẵn (đọc trước khi thiết kế)

- `claude.md` §3 mục **C4**: designer thấy task giao thẳng trên web, tự cập nhật
  sub-status (`đang làm`/`đang sửa`/`đã xong` — **chỉ hiển thị, không phải input cho
  state machine chính**), dán link Drive + bấm "Nộp" → tạo `result_version` mới, vào
  hàng chờ QC nội bộ. **Chưa đụng Printerval ở bước này.**
- Bảng `result_versions` **đã có sẵn từ Phase 1** (assignment_id, drive_url,
  version_marker, validated, submitted_at) — chưa migration nào cần thêm cho phần lưu
  kết quả.
- `assignments.sub_status` **đã có cột sẵn** (`doing`/`fixing`/`done`) — chưa có
  application-layer function nào đọc/ghi cột này. Đây là việc chính của sub-project này.
- State machine: `ASSIGNED → IN_PROGRESS → RESULT_SUBMITTED` đã có transition sẵn trong
  `app/domain/state_machine.py` — designer nộp kết quả = transition
  `IN_PROGRESS → RESULT_SUBMITTED` (chỉ chạy khi có `result_version` hợp lệ, theo
  claude.md §5: "Mỗi transition phải kiểm tra... result version (nếu có)").
- `IN_PROGRESS → REASSIGNMENT_REQUIRED` cũng có sẵn (nợ kỹ thuật #2: SLA tuyến tính
  10 order ≈ 1h, chỉ cảnh báo không tự chuyển state — không bắt buộc làm ở sub-project
  này trừ khi thấy cần).
- Business tool đã định nghĩa sẵn trong claude.md §7: `record_result(order_id, drive_url,
  source_version, idempotency_key) -> ResultVersion`.

### Việc cần thiết kế (chưa có quyết định, tự ruling)

1. Trang "Task của tôi" cho designer: danh sách order đang `ASSIGNED`/`IN_PROGRESS` được
   giao cho chính họ (dùng lại `list_orders_for_user`'s designer-scoping đã có từ Phase 4
   — nhưng **lưu ý `ponytail:` comment trong `order_queries.py`**: join hiện tại lấy
   BẤT KỲ Assignment row nào, không chỉ cái đang active — có thể giờ đã tới lúc phải sửa
   vì C2/C3 giờ đã sinh nhiều Assignment row/order (draft/approved/cancelled) thật sự,
   không còn "vô hại" như ghi chú cũ nói).
2. Cập nhật sub_status: 1 endpoint nhỏ (`PATCH` hoặc `POST /api/assignments/{id}/sub-status`),
   chỉ designer sở hữu assignment đó mới sửa được, chỉ ghi cột hiển thị — không đụng
   `OrderState`.
3. Nộp kết quả: form dán link Drive → `record_result` (validate URL tối thiểu, claude.md
   §9 "Xác minh Drive URL, quyền truy cập, file tồn tại và version trước khi submit" —
   **quyết định mức xác minh cho V1**: full Drive API check hay chỉ validate format URL?
   Gợi ý: bắt đầu bằng validate format thôi (YAGNI), ghi rõ như 1 giới hạn có chủ đích
   nếu chọn vậy).
4. Sau khi nộp: transition `IN_PROGRESS → RESULT_SUBMITTED`, tạo `ApprovalRequest(kind="qc",
   target_id=..., target_version_id=result_version.id)` — **chuẩn bị sẵn cho C5**
   (sub-project 6), dù C5 chưa build UI duyệt.
5. **Vòng sửa (revision loop):** khi QC "Edit" (sub-project 6 sẽ làm phần quyết định),
   order quay `QC_PENDING → REVISION_REQUESTED → IN_PROGRESS` — designer thấy lại task
   kèm feedback cũ, nộp lại tạo `result_version` mới (version_marker tăng). Sub-project
   này nên xây sẵn UI hiển thị feedback cũ + lịch sử result_version, dù quyết định QC
   thật sự nằm ở sub-project 6.

---

## 2. Sub-project 5/6 — Kanban ops board

**Chưa brainstorm.** Theo dõi tiến độ toàn bộ đơn qua các state (không giới hạn ở
allocation như sub-project 3), cho admin xem toàn cảnh — đúng yêu cầu gốc của người dùng
("Kanban Board kéo-thả theo các cột trạng thái... Thẻ đơn hàng hiển thị trực quan:
Thumbnail mẫu, Tên đơn, Loại thiết kế, Avatar/Tên Designer, Countdown thời gian, Badge
cảnh báo lỗi").

### Việc cần thiết kế

1. Cột theo `OrderState` (hoặc nhóm state — 15 state hiện có, có thể cần gộp nhóm hiển
   thị: "Chờ duyệt gán", "Đang thiết kế", "Chờ QC", "Đang đẩy site", "Hoàn thành" như
   người dùng mô tả gốc, map ngược lại `OrderState` thật).
2. Đây là **view đọc là chính** — kéo-thả giữa cột state KHÔNG được tự ý đổi
   `OrderState` (vi phạm claude.md §4/§10: chỉ state machine qua application service mới
   đổi state). Nếu muốn cho kéo-thả, chỉ nên cho phép kéo trong phạm vi các state có
   transition hợp lệ VÀ đi qua đúng application-layer function tương ứng (không phải
   ghi thẳng); **nhiều khả năng nên làm read-only trước, kéo-thả sau nếu còn thời gian.**
3. Badge cảnh báo: dùng `dead_letters` (đơn có lỗi), `REASSIGNMENT_REQUIRED` (SLA cảnh
   báo theo tech debt #2), `EXCEPTION` (bao gồm cả đơn Cancel từ C3 giờ đã có, tech debt
   #10 mới).
4. Endpoint: có thể tái dùng `GET /api/orders` (đã có từ sub-project 1/2, hỗ trợ filter
   `status`) thay vì viết endpoint mới — cân nhắc trước khi viết thêm (YAGNI).

---

## 3. Sub-project 6/6 — QC inspection screen (C5)

**Chưa brainstorm.** Đây là sub-project cuối, phụ thuộc sub-project 4 (cần có
`result_version` thật để QC).

### Bối cảnh đã có sẵn

- `claude.md` §3 mục **C5**: Admin xem đơn ở hàng chờ QC kèm context/result link, chọn
  1 trong 4: **Approve** (job nền tự động Playwright gắn link Drive lên Printerval,
  verify chuyển trạng thái, chỉ sau khi verify thành công mới coi `DONE`), **Edit**
  (bắt buộc feedback, gửi designer sửa, **không đụng Printerval**), **Skip** (Printerval
  tự xử lý, lên lịch reconcile, không đụng Printerval), **Cancel + Reply** (huỷ có lý
  do, không đụng Printerval).
- **Bất biến quan trọng nhất của cả dự án nằm ở đây:** "Chỉ Approve QC mới bao giờ chạm
  tới Printerval" (claude.md §18, Definition of Done). Nếu sub-project này làm sai —
  ví dụ Edit/Skip/Cancel vô tình gọi Playwright — là vi phạm bất biến cốt lõi nhất.
- `ApprovalRequest(kind="qc")` đã được DB cho phép sẵn (check constraint đã có
  `kind IN ('assignment', 'qc')` từ Phase 1) — không cần migration.
- Business tool đã định nghĩa sẵn (claude.md §7): `create_qc_request`, `decide_qc`,
  `submit_approved_result_to_site`, `reconcile_order`.
- **Tech debt #6 (claude.md §17) CHƯA GIẢI QUYẾT — đọc kỹ trước khi làm Approve path:**
  cơ chế chính xác `review → done` trên Printerval chưa rõ; phát hiện Phase 2: tài khoản
  outsource dùng để claim/thao tác **KHÔNG tự set được `Confirm → Done`** qua control đó.
  Nghĩa là `submit_approved_result_to_site` có thể KHÔNG đưa được đơn tới `DONE` thật sự
  trên site — cần khảo sát thêm (đọc-only trước, giống cách sub-project 1 làm) hoặc chấp
  nhận đơn dừng ở `review`/`Confirm` chờ "web mẹ" xử lý tiếp, ghi rõ giới hạn này.
- Tech debt #1 (tiêu chí "đơn đã làm" cho Cancel) và tech debt #10 mới (Cancel → EXCEPTION,
  chưa có recovery UI) đều liên quan trực tiếp tới C5's Cancel+Reply — QUYẾT ĐỊNH: C5's
  Cancel có nên dùng lại đúng cơ chế EXCEPTION như C3, hay khác đi vì ngữ cảnh khác
  (đơn đã tới tận bước QC, không phải mới phân đơn)? Cân nhắc kỹ, đây là loại quyết định
  nên ruling rõ ràng trong spec, không chỉ copy máy móc từ C3.

### Việc cần thiết kế

1. Màn hình so sánh cạnh nhau (mẫu gốc `order_assets`/`thumbnail_url` vs kết quả
   `result_version.drive_url`) — người dùng gốc yêu cầu "Side-by-side comparison" +
   phím tắt `Approve (A)`, `Edit (E)`, `Skip (S)`, `Cancel (C)`.
2. `decide_qc` áp dụng lại đúng cho **mọi** result version mới — không tái dùng quyết
   định QC cũ khi designer đã nộp bản sửa (claude.md §12.1 nhóm 2, dù không có LLM ở V1
   nhưng logic "không suy luận bản sửa chắc là ổn" vẫn áp dụng cho chính admin thao tác
   tay: mỗi `result_version` mới phải có `ApprovalRequest` mới, không merge).
3. Approve path: job nền (Celery, đã có `crawl_tasks.py` làm mẫu) chạy Playwright gắn
   link + verify — **áp dụng đúng kỷ luật "không đoán DOM" đã học từ sub-project 1**:
   phải khảo sát live (đọc-only) DOM thật của khu vực gắn link/đổi trạng thái QC trên
   Printerval trước khi viết code, y hệt cách đã làm cho order-detail-mirror.
4. Multi-admin race cho `decide_qc` — áp dụng đúng bài học từ sub-project 3's final
   review: idempotency key phải thật sự chống double-click (không nhét `uuid.uuid4()`
   vào key), có guard `ApprovalRequest.status != "pending"` tường minh, map
   `OperationInProgressError` → 409 kèm tên+thời gian, không để lọt `HTTP 500`.

---

## 4. Sau khi cả 6 sub-project xong

1. Chạy lại **toàn bộ** `.venv/bin/pytest tests/ -q` + `ruff check app tests` +
   `cd frontend && npm run build && npm run test` một lần cuối trên `HEAD` của
   `worktree-phase1-foundation`.
2. Dùng skill `superpowers:finishing-a-development-branch` — nhưng lưu ý: phiên này
   **không thể chạy git trên main checkout** (sandbox chặn `cd`/`-C` ra khỏi worktree).
   Đưa **lệnh tay** cho người dùng chạy, đúng mẫu đã dùng suốt phiên trước:
   ```bash
   cd /Users/hongphuc/Documents/01_congViec/pinterval
   git checkout main
   git merge worktree-phase1-foundation   # xác nhận fast-forward trước khi đưa lệnh
   ```
   Luôn `git merge-base main worktree-phase1-foundation` và `git log --oneline
   main..worktree-phase1-foundation` để xác nhận fast-forward TRƯỚC khi đưa lệnh cho
   người dùng.
3. Báo cáo lại người dùng để họ test web thật (đúng chỉ đạo gốc: "sau khi hoàn thiện web
   thì báo lại tao để tao test web") — kèm danh sách các giới hạn/tech debt còn tồn (đặc
   biệt #6, #10 ở trên) để họ biết chỗ nào chưa hoàn thiện 100%.

---

## 5. Ghi chú quy trình (giữ nguyên phong cách đã dùng, đừng đổi giữa chừng)

- Mỗi sub-project: `brainstorming` (tự quyết) → spec (`docs/superpowers/specs/`, tự
  review) → `writing-plans` (plan, no-placeholder, code cụ thể) → `subagent-driven-
  development`: dispatch implementer/task (model rẻ cho việc cơ học/transcription rõ
  ràng, model chuẩn cho việc cần phán đoán/nhiều file), **tự review diff mỗi task thay
  reviewer riêng** (AGENT.md §8) → **final whole-branch review bắt buộc, model mạnh
  nhất, yêu cầu tự chạy verify/probe thật chứ không chỉ đọc code** → đúng 1 vòng fix duy
  nhất cho toàn bộ finding → scoped re-review → đóng ledger, xoá
  `.superpowers/sdd/<plan>/`.
- Khi tự review (controller) phát hiện bug thật giữa chừng 1 task — không đợi tới final
  review — dispatch ngay 1 fix nhỏ trước khi đi tiếp task sau (đã làm 2 lần ở
  sub-project 3, cả 2 đều là bug thật, đáng để tiếp tục làm vậy).
- Ghi mọi quyết định tự ý vào ledger dạng `Ruling: <quyết định> — <lý do> — <giá nếu
  sai>` — đây là thứ duy nhất người dùng đọc lại được để biết mình đã tự quyết gì thay
  họ.
- Batch chi tiết code cụ thể (không placeholder) trong plan — implementer chỉ đọc brief
  của đúng task đó (`scripts/task-brief`), không đọc cả plan.

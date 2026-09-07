# Tóm tắt phiên làm việc — 2026-09-07 (Pinterval Ops Dashboard)

> File này tóm tắt lại **toàn bộ cuộc hội thoại** dẫn tới trạng thái hiện tại của repo, để
> đọc lại/bàn giao. Danh sách việc còn phải làm nằm ở file riêng:
> `docs/superpowers/REMAINING-WORK.md`.

## 1. Bối cảnh xuất phát

Phiên trước đó (đã tóm tắt sẵn ở đầu conversation) đã xong Phase 1–4 theo `roadmap.md`
gốc: scaffold, state machine, Playwright adapter đọc/ghi cho Printerval, C1 crawl & claim,
và một web dashboard khung bằng **Jinja2 + HTMX + Alpine.js**. Toàn bộ chạy trên worktree
`phase1-foundation` (branch `worktree-phase1-foundation`), được chủ đích **tái sử dụng
xuyên suốt mọi phase** thay vì tạo worktree mới mỗi lần.

## 2. Thay đổi định hướng lớn (đầu phiên này)

Người dùng đưa ra 2 việc làm thay đổi kiến trúc:

1. **Xác nhận lại tầm nhìn hệ thống:** web nội bộ phải là **web trung gian** thay thế
   hoàn toàn việc thao tác trên Printerval — admin/designer làm mọi việc trên web mình,
   chỉ ghi ngược lên Printerval sau khi QC approve. → Kết luận: luồng C1–C5 trong
   `claude.md` đã đúng, chỉ thiếu **dữ liệu đơn đầy đủ** để designer làm việc mà không
   cần mở Printerval.
2. **Yêu cầu UI kéo-thả chuyên nghiệp** (Allocation Board, Kanban ops board, QC
   inspection screen) — dẫn tới quyết định **bỏ Jinja2/HTMX/Alpine, chuyển hẳn sang
   React + TypeScript + Vite + Tailwind CSS** (quyết định người dùng, không hỏi lại lần
   2, chấp nhận rewrite toàn bộ Phase 4).

Người dùng sau đó ra chỉ đạo cốt lõi cho phần còn lại của phiên:

> "đồng ý, nhưng hãy làm 1 mạch tới phase UI. sau khi hoàn thiện web thì báo lại tao để
> tao test web."

→ Nghĩa là: **không dừng lại hỏi ý kiến giữa chừng**, tự ra quyết định (ruling) khi có
mơ hồ, chỉ dừng lại cho 4 trường hợp cứng theo `subagent-driven-development`: thao tác
không thể đảo ngược/phá huỷ, việc nhạy cảm bảo mật, side-effect ra ngoài worktree cần hỏi
trước (merge/push), hoặc plan sai tới mức mọi hướng đi đều là đoán mò.

## 3. Chuỗi 6 sub-project đã lập ra

Toàn bộ phần còn lại của phiên là thực thi tuần tự 6 sub-project, mỗi cái đi đủ vòng
`brainstorming` (tự quyết, không hỏi) → viết spec → tự review spec → `writing-plans` →
tự review plan → `subagent-driven-development` (dispatch implementer từng task, tự
review diff thay vì tách reviewer riêng cho việc rủi ro thấp — theo AGENT.md §8) → final
whole-branch review (model mạnh, bắt buộc, không được bỏ) → 1 vòng fix duy nhất → scoped
re-review → đóng sub-project.

| # | Sub-project | Trạng thái cuối phiên |
|---|---|---|
| 1 | **Order detail mirror** — mở rộng `orders` với đầy đủ field thật từ Printerval (SKU, ảnh, category, variants, custom config, 3 mốc thời gian, note...), khảo sát DOM thật (không đoán) | ✅ **Xong hoàn toàn** — final review tìm 2 Critical + 3 Important (selector Playwright có thể raise và treo cả crawl cycle, sai lệch selector so với spec, thiếu test offline), đã sửa hết, re-review sạch. |
| 2 | **Frontend platform migration** — thay Jinja2/HTMX/Alpine bằng React+TS+Vite+Tailwind, JSON API mới, xoá UI cũ hoàn toàn | ✅ **Xong hoàn toàn** — final review tìm 0 Critical + 5 Important (thiếu nút logout, không xử lý lỗi fetch/401 ở đâu cả, filter thụt lùi 2/15 state + mất filter batch, file `public/` bị SPA catch-all che ở prod, code rủi ro nhất không có test), đã sửa hết + xác nhận độc lập bằng probe thật kể cả path-traversal. |
| 3 | **Allocation board (C2+C3)** — thuật toán FIFO contiguous-block, offer/gán tay, duyệt/huỷ assignment, UI kéo-thả `dnd-kit` | ✅ **Xong hoàn toàn** — final review tìm 2 Critical + 6 Important (xem §4), đã sửa hết, scoped re-review xác nhận độc lập cả 8 finding (chạy lại concurrency test 5 lần, không flaky). Sub-project review-intensive nhất (2 bug tự phát hiện giữa chừng + 1 vòng fix final review đầy đủ). |
| 4 | **Designer task view (C4)** | ✅ **Xong hoàn toàn** — task chỉ hiện cho owner của assignment `approved`; Start và submit đi qua state machine/idempotency, Drive được adapter xác minh trước khi tạo result/QC request; UI React `/my-tasks` có lịch sử bản nộp và feedback QC. |
| 5 | **Kanban ops board** | ⏳ Chưa bắt đầu. |
| 6 | **QC inspection screen (C5)** | ⏳ Chưa bắt đầu. |

## 4. Sub-project 3 (Allocation board) — chi tiết vì đang dang dở

### Đã làm được (6 task, đã commit trên `worktree-phase1-foundation`)
1. `AllocationTool` interface + `ReferenceAllocationTool` (FIFO/contiguous-block) +
   `CapacityExceededError` — `app/adapters/allocation/`.
2. `open_allocation`, `request_quantity`, `create_assignment_draft` — `app/application/allocation.py`.
3. `decide_assignment` (approve/cancel) — cùng file. **2 lần tự phát hiện và tự sửa bug
   thiết kế ngay trong lúc implement** (trước khi final review chạy):
   - `_remaining_order_ids` từng loại trừ **vĩnh viễn** đơn có Assignment đã cancel khỏi
     pool khả dụng — sửa: chỉ loại đơn có Assignment **đang hoạt động** (draft/approved).
   - Quan trọng hơn: thiết kế ban đầu cho Cancel đưa đơn về lại `OPEN_FOR_ALLOCATION`
     ngay — nghĩa là FIFO có thể cấp lại **chính đơn đó cho chính designer vừa bị huỷ**,
     vô hiệu hoá hoàn toàn ý nghĩa "Cancel = đơn đã làm/không hợp lệ". Đã sửa: Cancel
     đưa đơn vào `EXCEPTION` (state machine đã cho phép sẵn), khớp bất biến #10
     claude.md ("không chắc thì vào exception queue"). Đã cập nhật spec +
     `claude.md` §17 (tech debt #10 mới) — đơn ở EXCEPTION chưa có UI recovery, admin
     phải xử lý tay/qua DB cho tới khi có UI đó (phase sau).
4. JSON API `app/api/routes/allocation_api.py` (open-allocation, offer, assign, board,
   decide).
5–6. React `AllocationBoardPage.tsx` dùng `@dnd-kit/core`: kéo-thả gán đơn, nút offer
   cho designer tự nhận, Approve/Cancel cho admin, nav link trong `AppHeader.tsx`.

### Final whole-branch review (đã chạy, KHÔNG chỉ đọc code — probe thật trên DB test)
**Verdict: Request changes.** Tìm ra:

- **Critical C1:** `quantity` không được validate (>=1) ở cả API lẫn application layer —
  gửi `quantity: -1` khiến Python slice `[:-1]` lấy gần hết batch, bỏ qua kiểm tra
  capacity hoàn toàn. Đo thật: capacity=2 → cấp được 9 đơn.
- **Critical C2:** `offer`'s idempotency key có `uuid.uuid4()` bên trong → không chống
  được double-click/network-retry thật sự. Đo thật: bấm 2 lần xin 3 đơn → được cấp 6,
  cả 2 request đều trả 200 (không báo lỗi gì).
- **Important I1:** khoá `SELECT...FOR UPDATE` trong `_remaining_order_ids` bị nhả giữa
  chừng vì `apply_transition` tự `commit()` sau mỗi order trong vòng lặp — "tuần tự hoá"
  mà docstring khẳng định thực ra không có tác dụng (chỉ được cứu bởi optimistic locking
  `version_id_col` có sẵn từ Phase 1, tình cờ, không phải cơ chế được thiết kế).
- **Important I2:** endpoint board (chỉ đọc) lại chiếm khoá ghi (`FOR UPDATE`) trên mọi
  đơn chưa gán trong request time — ở prod (không timeout) sẽ chặn writer vô thời hạn.
- **Important I3:** `decide_assignment` chưa có bước kiểm tra tường minh
  `ApprovalRequest.status != "pending"` như spec yêu cầu — chỉ dựa vào cơ chế cache của
  idempotency key do route lắp ráp; nếu có caller dùng key khác cho cùng approval (bug
  tương lai), có thể huỷ ngầm 1 assignment đã approved.
- **Important I4:** race thật giữa 2 admin (không phải race tuần tự) → `HTTP 500` chưa
  bắt, đáng lẽ phải là 409 kèm thông báo rõ ràng theo claude.md §10.
- **Important I5:** response "đã bị xử lý trước" thiếu tên admin + thời gian (bắt buộc
  theo §10) dù dữ liệu đã có sẵn trong `result`, chỉ là route không trả ra.
- **Important I6:** `pending_approvals` trên board không lọc theo `batch_id` — đơn của
  batch khác lẫn vào board đang xem.
- 12 Minor khác (actor_id null ở open_allocation, UUID param nên trả 422 thay vì 500,
  `assign` cũng dùng idempotency key kiểu cũ, comment/tên test lỗi thời, v.v.)

**Điểm được khen:** hướng thiết kế EXCEPTION (mục tự sửa ở trên) được xác nhận là **đúng
và test tốt** — không phải finding mới, reviewer chủ động xác nhận lại.

### Kết quả vòng fix (đã xong, đã đóng sub-project)
1 subagent fix toàn diện (đúng luật "no second fix wave" của SDD) đã sửa C1, C2, I1,
I2, I3, I4, I5, I6 + minor m3/m5/m6/m9 — bao gồm sửa cả frontend
(`AllocationBoardPage.tsx` sinh `request_id` phía client cho offer/assign để
idempotency key có tác dụng thật, disable nút "Nhận" trong lúc gửi). Điểm đáng chú ý:
viết **1 test concurrency thật** (2 thread, 2 session Postgres riêng trỏ cùng
`engine`) chứng minh không double-grant khi 2 designer tranh cùng batch — không phải
mock. Scoped re-review chạy sau đó xác nhận độc lập cả 8 finding đều ADDRESSED (chạy
lại chính test concurrency 5 lần liên tiếp, ổn định), full suite 160/160, ruff/frontend
sạch, xác nhận `apply_transition`'s caller khác (`crawl.py`) không bị ảnh hưởng bởi
tham số `commit=False` mới (mặc định giữ nguyên hành vi cũ). 1 minor mới phát sinh từ
chính fix (chưa bắt `IdempotencyKeyReusedError` ở route) được park có chủ đích, không
mở thêm vòng fix. Ledger đã đóng, workspace đã xoá — **sub-project 3/6 xong hoàn toàn.**

Kiểm tra độc lập bổ sung sau khi đóng ledger đã tìm ra một race nằm ngoài ma trận review
ban đầu: cùng **một** designer có thể gửi hai offer đồng thời vào hai batch khác nhau,
và cả hai cùng đọc capacity trước khi tạo assignment. Đã tái hiện bằng hai transaction
Postgres thật (capacity 2 nhưng giữ 4 assignment), rồi sửa bằng `FOR UPDATE` trên hàng
designer trước khi đếm capacity; regression test hiện đảm bảo một request bị từ chối và
tổng assignment không vượt capacity. UI cũng hiển thị tên và thời điểm admin đầu tiên
xử lý một approval thay vì bỏ mất chi tiết đó khi refresh board.

## 5. Vấn đề/rủi ro cần biết khi tiếp tục

1. **`worktree-phase1-foundation` CHƯA merge vào `main`** kể từ đầu phiên này. Main
   checkout (`/Users/hongphuc/Documents/01_congViec/pinterval`) vẫn đứng ở `25a5040`
   (trước cả sub-project 1). Toàn bộ order-detail-mirror + frontend-migration +
   allocation-board (khi xong) đều mới chỉ nằm trên worktree branch. **Phiên hiện tại bị
   sandbox chặn không chạy được git trực tiếp trên main checkout** — mọi lần merge trước
   giờ đều phải đưa lệnh tay cho người dùng chạy (`cd
   /Users/hongphuc/Documents/01_congViec/pinterval && git checkout main && git merge
   worktree-phase1-foundation`), xác nhận fast-forward trước khi đưa lệnh.
2. **Idempotency key + retry semantics** là lớp mỏng nhất của toàn bộ 3 sub-project vừa
   làm — 2/2 final review nghiêm túc đều bắt được ít nhất 1 vấn đề thuộc lớp này
   (Playwright retry ở sub-project 1 khác dạng; ở sub-project 3 là idempotency key thật
   sự). Nên soi kỹ điểm này ở sub-project 4–6 nếu có action ghi (submit kết quả, QC
   decide) tương tự.
3. **`EXCEPTION` chưa có recovery UI** (tech debt #10 mới, claude.md §17) — nếu sub-
   project 4–6 cần test end-to-end xuyên C2→C3→C4→C5, một đơn lỡ vào EXCEPTION (do test
   Cancel) sẽ kẹt, phải sửa tay qua DB trong lúc test.
4. **Không có 1 test live-site nào chạy trong 3 sub-project này** — order-detail-mirror
   có 1 lần khảo sát DOM thật (đọc-only, kết quả lưu vào spec, không lặp lại), còn lại
   toàn bộ test đều chạy trên fake adapter/DB test, không chạm Printerval thật. Nếu cần
   pilot thật, đó vẫn là việc chưa làm.

## 6. Quy ước làm việc đã thiết lập trong phiên (giữ nguyên cho phần còn lại)

- Mỗi sub-project: brainstorming (tự quyết, ghi Ruling vào ledger) → spec (tự review) →
  plan (tự review, no-placeholder) → SDD (dispatch implementer/task, model rẻ cho việc
  cơ học, model chuẩn cho việc có phán đoán) → **tự review diff mỗi task thay vì tách
  reviewer riêng** (theo AGENT.md §8) → **final whole-branch review bắt buộc, model
  mạnh nhất** → đúng 1 vòng fix cho toàn bộ finding cùng lúc → scoped re-review → đóng
  ledger, xoá workspace `.superpowers/sdd/<plan>/`.
- Khi tự review phát hiện bug thật giữa chừng task (không phải lúc final review), sửa
  ngay bằng 1 dispatch fix nhỏ trước khi đi tiếp, không đợi tới final review — đã làm 2
  lần ở sub-project 3.
- Không dừng lại hỏi người dùng trừ 4 trường hợp cứng của SDD.
- Ghi mọi quyết định tự ý (Ruling) vào ledger của sub-project đó; khi sub-project xong,
  chép các dòng `Ruling:` sang file chain-rulings (session-only, không commit) để tổng
  kết cuối cùng.

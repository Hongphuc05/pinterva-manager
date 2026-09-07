# AGENT.md — Quy trình làm việc cho agent trên repo này

Tài liệu này mô tả **cách một agent (Claude Code hoặc tương đương) phải làm việc**
trên repo này, độc lập với `claude.md` (mô tả *cái gì* cần build). File này mô tả
*quy trình* — đúng như cách đã áp dụng cho Phase 1 và Phase 2.

## 1. Vòng đời chuẩn: Brainstorm → Spec → Plan → Execute

Không code trực tiếp khi task có quy mô từ "một subsystem mới" trở lên. Đi qua đủ
4 bước:

1. **Brainstorm** (skill `superpowers:brainstorming`) — phân loại task trước:
   - *Spike*: câu hỏi khả thi, không giữ code, chỉ cần 1 câu trả lời.
   - *Bounded*: sửa nhỏ trên flow đã có sẵn trong repo — hỏi vài câu, chốt thiết
     kế ngắn trong chat, KHÔNG cần file spec/plan riêng.
   - *Architectural*: subsystem mới hoặc thay đổi kiến trúc/interface dùng chung —
     đi full quy trình bên dưới.
   - Luôn dừng lại xin duyệt thiết kế trước khi viết bất kỳ dòng code nào, kể cả
     task "đơn giản". Không tự nâng cấp độ phức tạp giữa chừng mà không báo.

2. **Spec** — với task architectural: viết design doc ra
   `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`, tự review (placeholder,
   mâu thuẫn nội bộ, phạm vi, mơ hồ), rồi đưa user duyệt bản viết trước khi sang
   plan.

3. **Plan** (skill `superpowers:writing-plans`) — viết
   `docs/superpowers/plans/YYYY-MM-DD-<feature>-plan.md`: task nhỏ (2-5 phút mỗi
   step), có code thật (không placeholder/TODO), có Global Constraints lấy
   nguyên văn từ spec, có phần Interfaces (Consumes/Produces) cho mỗi task để
   subagent sau không cần đọc lại toàn bộ plan.

4. **Execute** — mặc định dùng `superpowers:subagent-driven-development` (SDD)
   khi các task tương đối độc lập và làm trong cùng session; dùng
   `executing-plans` nếu cần chuyển sang session/worktree khác.

## 2. Cách ly workspace

- Mỗi luồng công việc lớn (một phase) chạy trong **một git worktree riêng**
  (`superpowers:using-git-worktrees`), branch riêng từ `main`.
- **Không tạo worktree mới cho mỗi phase nhỏ nếu user đã bảo dùng chung** — bám
  theo chỉ dẫn tường minh của user về phạm vi worktree, không tự ý tách thêm.
- Không bao giờ implement thẳng trên `main`/`master` khi chưa được user đồng ý
  rõ ràng.

## 3. Phương thức subagent-driven-development (SDD)

**Nguyên tắc cốt lõi:** 1 task = 1 subagent implementer mới (context sạch) + 1
subagent review riêng (spec compliance + code quality) → sửa nếu cần → sang task
tiếp theo → review tổng toàn nhánh ở cuối.

- **Ledger bắt buộc:** `.superpowers/sdd/<plan-basename>/progress.md` — ghi lại
  mọi dispatch, report, review, ruling, commit SHA. Đây là bộ nhớ sống sót qua
  compaction: khi context bị nén hoặc mất, đọc ledger + `git log` để biết chính
  xác đã làm tới đâu, KHÔNG dựa vào trí nhớ hội thoại.
- **Task brief riêng file:** trích nguyên văn yêu cầu 1 task ra
  `.superpowers/sdd/<plan>/task-N-brief.md`, đưa subagent đọc file đó thay vì
  dán lại toàn bộ plan vào prompt (tiết kiệm context, tránh nhiễu).
- **Report riêng file:** subagent viết báo cáo đầy đủ vào
  `.superpowers/sdd/<plan>/task-N-report.md`, chỉ trả lại status ngắn
  (DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED) + commit list + 1 dòng
  tóm tắt test.
- **Review package riêng file:** trước khi review, tạo file diff
  (`git log --oneline` + `git diff --stat` + `git diff -U10` từ BASE thật —
  không bao giờ dùng `HEAD~1` vì có thể bỏ sót commit của task nhiều commit).
- **Model theo độ khó việc:** việc cơ học (transcribe code có sẵn trong plan) →
  model rẻ nhất; việc cần phối hợp nhiều file/debug → model chuẩn; kiến trúc/
  review cuối cùng → model mạnh nhất. Luôn chỉ định model tường minh khi dispatch,
  không để kế thừa model của session hiện tại.
- **Vòng sửa lỗi (fix loop), tối đa 5 vòng:** vòng 1-3 resume đúng implementer cũ
  cùng model; vòng 4-5 dispatch subagent mới + model mạnh hơn ít nhất 1 bậc. Hết
  5 vòng mà vẫn còn finding → agent điều phối tự phán quyết (ruling), ghi lý do
  vào ledger, không bị kẹt chờ người dùng trừ 4 trường hợp ở mục 4.
- **Không để implementer tự spawn subagent khác** (kể cả reviewer) — review luôn
  do agent điều phối dispatch sau khi nhận report.
- **Không dừng lại hỏi "có nên tiếp tục không?" giữa các task** — chạy hết plan.
  Chỉ dừng khi gặp 1 trong 4 trường hợp ở mục 4, hoặc xong toàn bộ.

## 4. Bốn trường hợp bắt buộc dừng lại hỏi người dùng

Chỉ dừng khi gặp đúng 1 trong 4 điều sau (ngoài ra agent tự ra quyết định, ghi
ruling vào ledger, rồi tiếp tục):

1. Thao tác không thể đảo ngược hoặc mang tính phá hủy.
2. Thao tác nhạy cảm về bảo mật.
3. Side effect ra ngoài worktree mà theo thông lệ cần hỏi trước (merge, push lên
   branch chung, publish).
4. Plan bị lỗi nghiêm trọng tới mức mọi hướng đi tiếp theo đều là đoán mò.

## 5. Checkpoint — làm tới đâu lưu tới đó

Đây là quy tắc sống còn khi context có thể bị nén/mất bất kỳ lúc nào:

- Sau **mỗi task** hoàn tất (review sạch hoặc đã park finding có ruling): ghi
  ngay một dòng vào ledger `progress.md` dạng `Task N: complete — commit <sha>`.
  Không gộp nhiều task rồi mới ghi một lần.
- Khi có **sự cố thật** (ví dụ: một thao tác ghi lên hệ thống ngoài — website
  Printerval, Google Sheets thật — có kết quả bất ngờ), dừng ngay lập tức, ghi
  toàn bộ diễn biến + cách xử lý/khôi phục vào ledger **trước khi làm tiếp**, kể
  cả khi việc khôi phục đã xong.
- Khi context sắp hết (user báo, hoặc agent tự nhận thấy) và còn nhiều việc: viết
  một mục **CHECKPOINT** rõ ràng vào cuối ledger — tóm tắt đã xong gì, còn gì,
  cách resume — rồi **dừng lại thật**, không cố nhồi thêm 1 task nữa "cho nhanh
  xong". Nếu chỉ còn rất ít việc, làm nốt rồi mới báo cáo.
- Không bao giờ re-dispatch lại một task đã có dòng `complete` trong ledger dựa
  trên trí nhớ hội thoại — luôn tin ledger + `git log` hơn trí nhớ của agent.

## 6. Review cuối nhánh và merge

- Sau khi mọi task trong plan xong: dispatch **một review tổng thể toàn bộ diff
  của nhánh** bằng model mạnh nhất hiện có — không chỉ review từng task riêng lẻ.
- Nếu có finding: sửa 1 vòng, review lại phạm vi hẹp (chỉ phần đã sửa), rồi phán
  quyết các finding còn tồn (nếu có) — không lặp vô hạn.
- Review sạch → xóa workspace SDD của plan đó
  (`.superpowers/sdd/<plan-basename>/`).
- Dùng skill `superpowers:finishing-a-development-branch`: chạy test suite đầy
  đủ → xác định môi trường (worktree/repo thường) → đưa đúng menu lựa chọn
  (merge local / push+PR / giữ nguyên) → **luôn chờ người dùng chọn**, không tự
  quyết merge/push. Không bao giờ tự ý xóa worktree/branch khi user chọn "giữ
  nguyên", và không bao giờ discard việc đã làm trừ khi user gõ đúng từ xác nhận.

## 7. Quy tắc an toàn khi thao tác lên hệ thống thật bên ngoài

Áp dụng cho mọi Playwright/API write lên hệ thống production thật (Printerval,
Google Sheets/Drive) — kể cả trong lúc phát triển/test, không chỉ lúc chạy thật:

- **snapshot → act → verify → restore → verify-restore**, đủ 5 bước, không được
  bỏ bước nào.
- Verify và verify-restore phải là **đọc độc lập, session/request mới** — không
  tin state phía client ngay sau khi bấm nút (bug thật đã từng xảy ra: đọc lại
  DOM/textarea trên cùng page ngay sau click Save, trong khi request lưu thật sự
  chưa kịp hoàn tất → tưởng đã restore nhưng thực ra chưa).
- Ưu tiên test trên dữ liệu ít rủi ro nhất có sẵn (ví dụ đơn đã ở trạng thái
  cuối/Done) thay vì đơn đang hoạt động, khi việc đó không ảnh hưởng tới mục
  đích test.
- Gặp lỗi thật giữa chừng: dừng thao tác tiếp theo ngay lập tức, không thử thêm
  biến thể khác trên cùng dữ liệu thật để "xem thử" — ghi lại, khôi phục, rồi
  mới quyết bước tiếp theo.
- Test tự động (pytest/CI) không bao giờ chạm hệ thống thật — luôn chạy trên fake
  adapter cùng interface (`typing.Protocol`) với adapter thật, đảm bảo bằng
  contract test.

## 8. Tham chiếu

- `claude.md` — spec sản phẩm (V1 Web Dashboard Vận Hành): bất biến nghiệp vụ,
  state machine, data model, business tool contract.
- `roadmap.md` — trình tự các phase.
- `docs/superpowers/specs/` — design doc từng phase.
- `docs/superpowers/plans/` — implementation plan từng phase.
- `.superpowers/sdd/<plan-basename>/progress.md` — ledger tiến độ, nguồn sự thật
  khi resume sau khi mất context.

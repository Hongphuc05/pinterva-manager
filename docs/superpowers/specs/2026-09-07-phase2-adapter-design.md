# Phase 2 — Adapter tích hợp xác định — Thiết kế

> Triển khai Phase 2 của `roadmap.md` §5: adapter Playwright cho website Printerval,
> adapter Google Sheets/Drive, và "Playwright reliability package" dùng chung. Đây là
> lớp adapter thuần — chưa wiring vào job nền/worker (đó là Phase 3+); Phase 2 chỉ xây
> và xác minh từng adapter method hoạt động đúng, độc lập.

## 1. Bối cảnh & quyết định đã chốt qua brainstorming

- **Ranh giới test với site thật (đã chốt):** Playwright được phép thực hiện **mọi
  thao tác** trên Printerval thật kể cả lúc code (đọc lẫn ghi — claim, đổi status, gắn
  link), với điều kiện bắt buộc: mọi thao tác ghi phải theo chu trình
  **snapshot trạng thái gốc → thực hiện → verify → phục hồi (restore) → verify đã phục
  hồi đúng**. Nếu có lỗi giữa chừng, vẫn phải cố gắng restore trong `finally`, và log rõ
  ràng nếu restore thất bại (không được im lặng bỏ qua).
- **Chọn đơn để test ghi:** ưu tiên đơn đã `Done` khi cần 1 đơn cụ thể để test (rủi ro
  thấp nhất nếu restore thất bại), nhưng không bắt buộc — method nào cần trạng thái
  khác (vd `set_designer`/claim chỉ áp dụng được cho đơn `waiting`) thì dùng đơn đúng
  trạng thái đó.
- **Google Sheets/Drive: có credential thật.** Service account đã tạo
  (`pinterval-sheets-adapter@gen-lang-client-0481902654.iam.gserviceaccount.com`), lưu
  tại `credentials/google-service-account.json` (gitignored). Phase 2 build luôn
  implementation thật qua Google Sheets API + Drive API (không chỉ interface+fake).
- **CI/test tự động không bao giờ đụng site thật hay Google API thật** — theo claude.md
  §13 "Không test live customer data/credential mặc định; test phải deterministic."
  Việc xác minh code thật hoạt động đúng nằm ở script chạy tay có giám sát, tách biệt
  hoàn toàn khỏi `pytest`/CI.

## 2. Kiến trúc & thành phần

```
app/adapters/
  playwright_support.py     # Chrome profile persistent, retry+backoff, evidence capture
  printerval/
    interface.py            # Protocol: discover_orders, get_order_detail, set_designer,
                             #           set_status, attach_result_link, download_asset
    errors.py                # ErrorClass enum (VALIDATION/AUTH/RATE_LIMIT/TRANSIENT_NETWORK/
                             #                   EXTERNAL_CHANGED/UNKNOWN_OUTCOME/PERMANENT_EXTERNAL/BUG)
    playwright_adapter.py    # implement thật bằng Playwright
    fake_adapter.py           # implement giả lập trong RAM, dùng cho pytest
  google/
    sheets_interface.py      # Protocol: export_snapshot(rows, sheet_id) -> ExportResult
    drive_interface.py       # Protocol: verify_url(drive_url) -> DriveVerifyResult
    sheets_adapter.py        # implement thật qua Google Sheets API (service account)
    drive_adapter.py         # implement thật qua Google Drive API
    fake_sheets_adapter.py, fake_drive_adapter.py
scripts/
  printerval_smoke_test.py   # chạy tay/subagent giám sát — test đọc lẫn ghi lên site thật,
                             # bắt buộc snapshot→act→verify→restore→verify-restore
```

- `pytest` (chạy trong CI mỗi lần push) **chỉ dùng fake adapter** cho cả Printerval lẫn
  Google — không phụ thuộc mạng/site thật/quota API thật.
- `scripts/printerval_smoke_test.py` là nơi duy nhất chạm site thật, chạy có giám sát
  (không nằm trong CI), theo đúng chu trình snapshot-restore đã chốt ở mục 1.
- Google Sheets/Drive thật **có thể** test tự động trong CI ở mức giới hạn (đọc/verify,
  không ghi dữ liệu thật) nếu có 1 Sheet test riêng — nhưng mặc định Phase 2 vẫn dùng
  fake trong CI, giữ nhất quán nguyên tắc "CI không phụ thuộc dịch vụ ngoài"; verify
  implementation thật cũng qua smoke test thủ công.

## 3. Contract của từng adapter method

Tất cả trả về Pydantic model có tối thiểu: `success: bool`, `evidence: dict`,
`error_class: ErrorClass | None`, `retryable: bool`. Method riêng có thêm field phù hợp.

### Printerval (`printerval/interface.py`)

```python
class PrintervalAdapter(Protocol):
    def discover_orders(
        self, status: str, job_type: str = "2D", limit: int = 40, cursor: str | None = None
    ) -> DiscoverResult: ...

    def get_order_detail(self, external_order_id: str) -> OrderDetailResult: ...

    def set_designer(self, external_order_id: str, designer_option: str) -> WriteResult: ...

    def set_status(self, external_order_id: str, target_status: str) -> WriteResult: ...

    def attach_result_link(self, external_order_id: str, drive_url: str) -> WriteResult: ...

    def download_asset(self, external_order_id: str) -> AssetResult: ...
```

- `discover_orders`: lọc `status` + `job_type=2D` (cứng theo claude.md §16), trả danh
  sách order thô (mã đơn, tên sản phẩm, ảnh thumbnail, designer hiện tại, status) +
  cursor phân trang.
- `get_order_detail`: trả toàn bộ field thô của 1 đơn (không diễn giải nghiệp vụ) —
  designer, status, note outsource, order note, 3 mốc thời gian, có/không có file thiết
  kế đã upload. Việc "đơn đã làm hay chưa" là phán đoán nghiệp vụ ở lớp application
  (Phase 5), **không** phải việc của adapter.
- `set_designer` / `set_status` / `attach_result_link`: mỗi method làm **đúng 1 hành
  động ghi**, đọc lại (read-after-write) để verify trước khi trả `success=True`; nếu
  verify không khớp sau khi click → `error_class=UNKNOWN_OUTCOME`, không tự retry.
- `download_asset`: tải ảnh mẫu về local disk (claude.md §17 #3 — local disk cho V1,
  qua interface riêng để đổi backend sau).

### Playwright reliability package (`playwright_support.py`)

- `PlaywrightSession`: context manager mở Chrome với profile persistent
  (`chrome-profile/`, gitignored — đã có sẵn), `channel="chrome"`,
  `--disable-blink-features=AutomationControlled` (đã xác nhận cần thiết ở Phase 0),
  không headless mặc định. Tự phát hiện nếu session hết hạn (form login xuất hiện) và
  đăng nhập lại bằng credential trong `.env`.
- `with_retry(fn, max_attempts=3)`: chỉ retry khi `error_class` thuộc nhóm retryable
  (`TRANSIENT_NETWORK`, `RATE_LIMIT`), exponential backoff + jitter.
- `capture_evidence(page, label)`: chụp screenshot + dump HTML + timestamp vào thư mục
  evidence cục bộ (đổi tên `selenium-evidence/` cũ trong `.gitignore` thành
  `playwright-evidence/` cho đúng tên công cụ), trả về dict đường dẫn để gắn vào
  `evidence` field của kết quả adapter.

### Google Sheets/Drive (`google/*_interface.py`)

```python
class SheetsAdapter(Protocol):
    def export_snapshot(
        self, rows: list[dict], sheet_id: str, exported_at: datetime
    ) -> ExportResult: ...

class DriveAdapter(Protocol):
    def verify_url(self, drive_url: str) -> DriveVerifyResult: ...
```

- `export_snapshot`: ghi thêm (append) `rows` vào sheet, đánh dấu `exported_at` để job
  gọi lại không ghi trùng (idempotent — dùng ở Phase 8, Phase 2 chỉ cần method hoạt
  động đúng độc lập).
- `verify_url`: kiểm tra URL Drive hợp lệ, file tồn tại, có quyền truy cập — dùng trước
  khi submit kết quả lên Printerval (Phase 6/7).

## 4. Error handling

Theo claude.md §11 nguyên bản, áp dụng cho mọi adapter method:

`VALIDATION | AUTH | RATE_LIMIT | TRANSIENT_NETWORK | EXTERNAL_CHANGED | UNKNOWN_OUTCOME | PERMANENT_EXTERNAL | BUG`

- Explicit wait: Playwright auto-wait + `wait_for_selector` với timeout tường minh cho
  từng selector quan trọng.
- Không dùng click toạ độ, không JS injection tuỳ tiện.
- Evidence bắt buộc khi lỗi (screenshot + HTML, đã redact nếu cần) — không log
  cookie/password.

## 5. Testing

- **Unit (fake adapter):** mọi method, mọi nhánh lỗi (success/UNKNOWN_OUTCOME/từng
  error_class) — chạy trong CI, hoàn toàn deterministic, không cần Playwright/network.
- **Contract test:** `fake_adapter` và `playwright_adapter` cùng implement 1 Protocol —
  test tối thiểu đảm bảo cả 2 trả đúng kiểu dữ liệu (Pydantic model, field bắt buộc).
- **Smoke test thủ công** (`scripts/printerval_smoke_test.py`): chạy có giám sát mỗi khi
  1 method thật viết xong, theo đúng chu trình snapshot→act→verify→restore→verify-restore
  đã chốt ở mục 1. Không nằm trong `pytest`/CI.
- Google Sheets/Drive thật: verify thủ công tương tự (ghi thử vào 1 Sheet test do người
  dùng share cho service account, xoá/dọn sau khi verify xong).

## 6. Ngoài phạm vi Phase 2

- Wiring adapter vào job nền/Celery worker (Phase 3: crawl job).
- Xử lý concurrency nhiều session Playwright song song (claude.md §17 #4 — mặc định 1
  session/site cho tới khi có số liệu; Phase 2 chưa cần lock vì chưa có worker chạy
  song song).
- Đồng bộ export Sheet theo lịch, xử lý trùng lặp dài hạn (Phase 8).

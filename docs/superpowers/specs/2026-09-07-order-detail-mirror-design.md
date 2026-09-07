# Order Detail Mirror — Design

**Sub-project 1 của 6** trong loạt "web trung gian thay thế Printerval" (xem
`claude.md` §15 bước 5b). Độc lập với lựa chọn frontend (Jinja2 hay React) — đây thuần là
data model + adapter, ship trước để không làm lại.

## 1. Vấn đề

`orders` hiện chỉ lưu `external_order_id`, `batch_id`, `state`, `version`,
`external_observation` (JSONB, chưa từng được ghi). Designer/admin muốn làm việc hoàn
toàn trên web nội bộ (không mở Printerval) nhưng web hiện không hiển thị được thumbnail,
SKU, mẫu, custom config, deadline — những thứ cần để *biết phải làm gì* với 1 đơn.

`PlaywrightPrintervalAdapter.get_order_detail` đã đọc được một phần (`note_outsource`,
`designer`, `status`) nhưng chưa từng được gọi trong pipeline crawl (`import_claimed_orders`
chỉ gọi `download_asset`). Phần lớn field còn lại (SKU, category/size/type/style, template
tag, checkbox multiple/double-sided, priority tag, 3 mốc thời gian, `order_note`, custom
config, link design-tool) **chưa từng được xác nhận DOM thật** — chỉ có tên field trong
`docs/phase0-field-map.md`, không có selector.

## 2. Phạm vi (đã chốt qua brainstorming)

**Lấy:** product info đầy đủ (đủ để làm việc — không lấy điểm/tiền phạt designer, đó là
cơ chế riêng Printerval, tech debt #7 giữ nguyên "chưa tích hợp"). **Thời điểm lấy:** lúc
import (C1), ngay sau `download_asset` thành công, trước khi chuyển `CLAIMED_IMPORTED`.

## 3. Data model — migration mới trên `orders`

Cột mới, tất cả `nullable=True` (đơn ở state `DISCOVERED` chưa có, chỉ được điền sau khi
import xong):

| Cột | Kiểu SQLAlchemy | Nguồn field-map §5 |
|---|---|---|
| `product_name` | `String(512)` | Product info |
| `thumbnail_url` | `String(1024)` | Product info |
| `sku` | `String(128)` | Mã sản phẩm |
| `product_category` | `String(128)` | Product info |
| `product_size` | `String(64)` | Product info |
| `product_type` | `String(128)` | Product info |
| `product_style` | `String(128)` | Product info |
| `job_type` | `String(32)` | Loại design job |
| `template_tag` | `String(32)` | "Đã/Chưa có template" |
| `multiple_design` | `Boolean, default=False` | checkbox |
| `double_sided` | `Boolean, default=False` | checkbox |
| `priority_label` | `String(64)` | tag "Ưu tiên" — lưu text+màu thô, KHÔNG diễn giải ý nghĩa (field-map câu hỏi #7 chưa chốt) |
| `created_at_ext` | `DateTime(timezone=True)` | "Created at" |
| `order_created_at_ext` | `DateTime(timezone=True)` | "Order created at" |
| `deadline_at_ext` | `DateTime(timezone=True)` | "Deadline at" |
| `note_outsource` | `Text, default=""` | đã đọc được, chưa từng lưu |
| `order_note` | `Text, default=""` | field-map có, adapter hiện chưa set |
| `custom_config` | `JSONB, nullable=True` | chỉ đơn cá nhân hoá; cấu trúc list `{field, value, translated_value}` — biến đổi giữa các đơn, JSONB hợp lý ở đây (khác việc dùng JSONB né cột có kiểu cho field cố định) |
| `design_tool_url` | `String(1024)` | link "Gen design custom" |

Không đổi cột nào hiện có. Đây là additive migration (Alembic `op.add_column` x17,
`nullable=True`/`server_default` cho cột có default).

## 4. Adapter — bắt buộc khảo sát DOM thật trước khi viết extraction code

**Nguyên tắc bất di bất dịch của dự án này (rút ra từ 3 sự cố thật ở Phase 3):** không
đoán selector/text từ tài liệu — field-map ghi tên field, không ghi DOM structure/class
thật. Trước khi sửa `get_order_detail`, phải có 1 script chẩn đoán read-only (giống
`diagnose_designer_options.py` đã dùng) chạy trên **≥2 đơn thật** (1 đơn thường + 1 đơn cá
nhân hoá để thấy `custom_config` thật, không đoán cấu trúc) và log ra: SKU selector,
category/size/type/style selector, template tag selector + 2 giá trị text thật, checkbox
selector, priority tag selector + màu/text quan sát được, 3 timestamp selector + format
thật, `order_note` selector, custom config DOM structure, `design_tool_url` href pattern.
Kết quả khảo sát phải được ghi vào `docs/phase0-field-map.md` (nối thêm, không sửa đè)
trước khi task viết `get_order_detail` bắt đầu.

`get_order_detail` (đã tồn tại) mở rộng để trả về toàn bộ field ở bảng trên trong
`OrderDetailResult` (model mới cần thêm field tương ứng). Field nào không tìm thấy trên
DOM của 1 đơn cụ thể (ví dụ đơn không cá nhân hoá thì không có `custom_config`) trả về
`None`/rỗng — không raise lỗi, không coi là adapter failure.

`import_claimed_orders` (C1, `app/application/crawl.py`) gọi `adapter.get_order_detail`
ngay sau `download_asset` thành công (trong cùng `_do()` của idempotent operation), ghi
toàn bộ field vào `Order` trước `apply_transition(..., CLAIMED_IMPORTED, ...)`. Nếu
`get_order_detail` fail (adapter trả `success=False`): dead-letter và **không** chuyển
`CLAIMED_IMPORTED` — asset đã tải rồi nhưng thiếu thông tin hiển thị nghĩa là chưa sẵn
sàng cho designer làm việc, coi như import chưa xong (nhất quán với nguyên tắc hiện có:
không chuyển state khi asset/data chưa xác minh đầy đủ).

`FakePrintervalAdapter.get_order_detail`/`_FakeOrder` (test double) mở rộng tương ứng để
test C1 có thể seed field giả và assert chúng được lưu đúng cột.

## 5. UI (Jinja2 hiện tại — sẽ được port sang React ở sub-project 2, không làm lại UI ở đây)

`orders_table.html`: thêm cột thumbnail (ảnh nhỏ) + SKU + deadline.
`order_detail.html`: hiện đầy đủ product info, ảnh, custom config (nếu có, dạng list),
note outsource, order note, deadline, priority label.

## 6. Testing

- Migration: chạy `alembic upgrade head` trong test harness hiện có (đã có từ Phase 1).
- `tests/test_crawl.py`: test mới — sau `import_claimed_orders` thành công, `Order` row có
  đủ field từ fake adapter; test `get_order_detail` fail → order ở lại `DISCOVERED`,
  dead-letter được ghi.
- `tests/test_web_orders.py`: template render test — order có `thumbnail_url`/`sku` thì
  `orders_table.html`/`order_detail.html` chứa các giá trị đó trong response body.
- Không test live site trong CI — script chẩn đoán DOM chạy tay 1 lần (giống các script
  trong `scratchpad/` trước đây), không commit vào repo, không phải part of test suite.

## 7. Non-goal

- Không đồng bộ điểm/tiền phạt designer (tech debt #7 giữ nguyên).
- Không diễn giải ý nghĩa màu priority — lưu nguyên text/màu quan sát được.
- Không build UI React ở đây (sub-project 2).

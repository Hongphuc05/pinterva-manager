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

**Đã khảo sát DOM thật (2026-09-07, đọc HTML thô của 3 đơn thật `DJ3967568`,
`DJ3967572`, `DJ3967595` qua Playwright read-only, dump lưu ở scratchpad, không commit)
— các điểm dưới đây khác so với suy đoán ban đầu từ field-map, đã sửa theo thực tế:**

- **Không có** `product_size`/`product_type`/`product_style` cố định. Thực tế mỗi SKU có
  danh sách "variant" tên khác nhau tuỳ sản phẩm (`Size`+`Type`, hoặc `Size`+`Hole`, v.v.
  — không phải schema cố định) → dùng `product_variants: JSONB` (list `{name, value}`).
- `template_tag` đổi thành **`has_template: Boolean`** — DOM thật chỉ render
  `<span class="label label-success">Đã có template</span>` khi có; trường hợp chưa có
  **không render tag đỏ nào cả** (khác giả định field-map §5) — suy ra từ việc tag vắng
  mặt, không tìm span nào khác.
- `job_type` **bỏ khỏi phạm vi task này** — khảo sát xác nhận loại design job không xuất
  hiện ở bất kỳ đâu trong row DOM (chỉ là tiêu chí filter, không phải field hiển thị per
  order). Giữ cột placeholder `nullable=True`, không populate ở migration này — nợ kỹ
  thuật mới, ghi vào claude.md §17 nếu cần sau.
- `custom_config` cấu trúc thật: `{"original": [{"key": str, "value": str}, ...],
  "translated_vn": [{"key": str, "value": str}, ...]}` — lấy từ `.djcfg-card` (bản gốc)
  và `.djcfg-card.djcfg-vn` (bản dịch), mỗi row `.djcfg-row` có `.djcfg-key`/`.djcfg-val-text`.
- 3 mốc thời gian có **2 format khác nhau** trên cùng 1 trang (xác nhận thật, không đoán):
  `Created at`/`Order created at` dùng `"HH:MM' DD/MM/YYYY"` (vd `"03:46' 07/09/2026"`);
  `Deadline at` dùng `"YYYY-MM-DD HH:MM:SS"` (vd `"2026-09-08 03:38:52"`).
- `order_note` DOM thật có thể chứa text rác lặp lại (`"Order note: \nOrder note:"` sau
  URL nguồn) — đây là artifact có sẵn trên site, lưu nguyên văn, không parse/làm sạch.
- `design_tool_url` chỉ có khi `item.is_custom_design` — selector
  `a[href*="design-tool.printerval.com"]`, lấy thẳng `href`.

Cột mới, tất cả `nullable=True` (đơn ở state `DISCOVERED` chưa có, chỉ được điền sau khi
import xong):

| Cột | Kiểu SQLAlchemy | Nguồn |
|---|---|---|
| `product_name` | `String(512)` | `h5` trong ô sản phẩm |
| `thumbnail_url` | `String(1024)` | `img` trong `.sb-design-thumbnail` |
| `sku` | `String(128)` | `[ng-bind="productSku.product_sku"]`, lấy SKU đầu tiên nếu có nhiều |
| `product_category` | `String(128)` | div có `item.product.category_name`, tách bỏ prefix "Category: " |
| `product_variants` | `JSONB, nullable=True` | list `{name, value}` từ `ng-repeat="variant in productSku.variants..."` |
| `job_type` | `String(32), nullable=True` | **chưa populate** — xem ghi chú trên |
| `has_template` | `Boolean, default=False` | `.label.label-success` có mặt hay không |
| `multiple_design` | `Boolean, default=False` | `#multiple-design` checkbox `.is_checked()` |
| `double_sided` | `Boolean, default=False` | `#double-sided` checkbox `.is_checked()` |
| `priority_label` | `String(128), nullable=True` | `class` attribute của `span.label` trong block "Độ ưu tiên" khi có mặt — lưu thô, KHÔNG diễn giải ý nghĩa (field-map câu hỏi #7 chưa chốt) |
| `created_at_ext` | `DateTime(timezone=True)` | "Created at", format `HH:MM' DD/MM/YYYY` |
| `order_created_at_ext` | `DateTime(timezone=True)` | "Order created at" (có thể vắng mặt), cùng format |
| `deadline_at_ext` | `DateTime(timezone=True)` | "Deadline at", format `YYYY-MM-DD HH:MM:SS` |
| `note_outsource` | `Text, default=""` | đã đọc được (existing), chưa từng lưu vào DB |
| `order_note` | `Text, default=""` | div có `item.order_note`, lưu nguyên văn |
| `custom_config` | `JSONB, nullable=True` | cấu trúc `{"original": [...], "translated_vn": [...]}` — xem trên |
| `design_tool_url` | `String(1024), nullable=True` | `a[href*="design-tool.printerval.com"]` |

Không đổi cột nào hiện có. Đây là additive migration (Alembic `op.add_column` x16,
`nullable=True`/`server_default` cho cột có default).

## 4. Adapter — selector đã xác nhận thật (2026-09-07), không đoán

`get_order_detail` (đã tồn tại) mở rộng để trả về toàn bộ field ở bảng trên trong
`OrderDetailResult` (model mới cần thêm field tương ứng), dùng đúng selector đã khảo sát
ở §3. Field nào không tìm thấy trên DOM của 1 đơn cụ thể (ví dụ đơn không cá nhân hoá thì
không có `custom_config`/`design_tool_url`; `Order created at` có thể vắng mặt) trả về
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

# Phase 0.2/0.4 — Từ điển status & bản đồ trường dữ liệu website khách

> Nguồn: khảo sát read-only `https://printerval.com/central/outsource/pod/design-job/admin`
> (2026-09-02). Không có thao tác ghi nào được thực hiện khi khảo sát — chỉ đăng nhập, lọc/xem,
> đọc DOM. Ví dụ trong tài liệu này đã được ẩn danh (không giữ tên khách/link đơn thật).

## 1. Status thật trên website (khác giả định ban đầu)

Giả định cũ trong claude.md/roadmap: `waiting → doing → review → done` (4 trạng thái).

**Thực tế có 6 trạng thái** (option trong dropdown Status của từng dòng đơn):

`Waiting → Doing → Review → Fix / Confirm → Done`

- `Waiting` — chưa có designer (mặc định `Choose Designer` / `Chưa chia cho ai`).
- `Doing` — đã claim/đang làm.
- `Review` — đã nộp, chờ xét duyệt.
- `Fix` — **trạng thái mới, chưa có trong doc cũ.** Theo banner hướng dẫn trên trang: mỗi lần job bị chuyển sang `Fix` thì designer bị **trừ 5 điểm**, điểm thấp = bị chia job sau người khác trong các lượt tới. Có vẻ đây chính là bước QC nội bộ (B7) — set qua cùng dropdown Status này.
- `Confirm` — **trạng thái mới, chưa rõ nghĩa.** Chưa xác định ai/khi nào set, và khác `Done` ở điểm gì. Cần hỏi (xem câu hỏi bên dưới).
- `Done` — hoàn tất.

Filter status có sẵn trên trang: `All status`, `Waiting + Doing + Fix` (mặc định), `Waiting`, `Doing`, `Review`, `Fix`, `Confirm`, `Done`.

## 2. Cơ chế điểm/phạt đã có sẵn trên website (không phải do mình xây)

- Đếm "Need fix jobs" hiển thị đầu trang (hiện tại: 22).
- Mỗi lần đơn chuyển sang `Fix`: designer bị trừ 5 điểm (tự động theo banner, cần xác nhận có thật tự động không hay do người set điểm tay).
- Điểm thấp → bị ưu tiên chia job sau người khác ở các lượt phân đơn tiếp theo (cơ chế **ngay trên website**, không phải hệ thống mình xây).
- Mỗi đơn còn có ô **"Tiền phạt"** (nhập tay + nút Lưu riêng) — phạt tiền độc lập với điểm.
- **Câu hỏi mở:** hệ thống nội bộ (Postgres/allocation B3) có cần đọc/đồng bộ điểm này để quyết định ai được chia job trước không, hay đây là cơ chế của riêng website, mình chỉ quan sát không cần tích hợp?

## 3. Dropdown Designer — xác nhận giả thuyết "ntth"

Dropdown Designer trên mỗi dòng đơn hiện chỉ có 2 lựa chọn ngoài "Chưa chia cho ai":
`Nguyễn Thị Thuý Hường - 2D Prin`, `Nguyễn Thị Thuý Hường - Support`.

→ Xác nhận: **"ntth" = Nguyễn Thị Thuý Hường**, tức tài khoản chủ team (chính là tài khoản đang đăng nhập). Các designer thật (Lâm, Hoa...) **không có tài khoản riêng trên website này** — khớp với thiết kế B1–B3 hiện tại trong claude.md: website luôn chỉ hiển thị "ntth" (để claim/phân biệt đơn), còn việc chia cụ thể cho Lâm/Hoa nằm ở Google Sheet + Telegram, không phản ánh ngược lại dropdown Designer của website. **Không cần sửa gì ở B1–B3.**

Có một khu vực quản lý tài khoản khác trong DOM (`Email / Mật khẩu / Quyền`) — có thể là màn quản lý sub-account designer, nhưng **chưa xác định được cách mở nó** (không nằm trong luồng cuộn bình thường, có thể là tab/modal ẩn) và **chưa click thử** vì đây là khu vực hiển thị mật khẩu dạng plaintext — cần hỏi ý kiến trước khi khám phá thêm.

## 4. Bộ lọc (filter bar)

| Filter | Giá trị |
|---|---|
| Search | theo tên product (text) |
| Status | All / Waiting+Doing+Fix / Waiting / Doing / Review / Fix / Confirm / Done |
| Designer | Tất cả / Chưa chia cho ai / (2 account ntth ở trên) |
| Loại design job | Tất cả 2D & 3D / 2D / 3D / ART / WOOD / CALENDAR / EMBROIDERY / AI |
| Trạng thái tìm design | Đang tìm / Đã tìm xong (sub-workflow riêng: tìm nguồn ảnh/mẫu tham khảo, tách biệt với việc thiết kế) |
| Ngày | theo Ngày tạo / Ngày hoàn thành / Ngày tạo đơn hàng / Ngày hết hạn, kèm Date from/to |

→ **Đã xác nhận (2026-09-07):** ngoài loại "2D" (thiết kế đồ hoạ) còn có WOOD (khắc gỗ),
EMBROIDERY (thêu), CALENDAR, AI, ART — nhưng loại job chỉ là nhãn phân loại từ khách,
không phải rào cản xử lý. V1 crawl mặc định **tất cả loại** ("Tất cả 2D & 3D" — lưu ý
có dấu cách quanh dấu `&`, đã từng ghi sai không dấu cách ở bản đầu và gây crawl im
lặng trả về 0 đơn), không lọc cứng `type=2D` như dự định ban đầu.

## 5. Cấu trúc 1 dòng đơn (job)

| Field | Mô tả |
|---|---|
| Mã đơn | `DJ#######` (Design Job code) — định danh ổn định, dùng làm external ID |
| Mã sản phẩm (SKU) | `P###########-<size/variant code>` |
| Flag quốc gia | cờ thị trường đích |
| Tag template | `Đã có template` (xanh) / `Chưa có template` (đỏ) |
| Multiple design / Double sided | checkbox thuộc tính đơn |
| Độ ưu tiên | tag "Ưu tiên" — **màu thay đổi** (xám / cam quan sát được) → có vẻ có nhiều mức ưu tiên, chưa rõ hết thang màu/ý nghĩa |
| 3 mốc thời gian | `Created at`, `Order created at`, `Deadline at` — 3 timestamp khác nhau, cần làm rõ ý nghĩa từng cái (nhất là cái nào dùng để tính SLA/trễ hạn) |
| Product info | ảnh thumbnail, Category, Size, Type, Style |
| Design | vùng upload file thiết kế (`+`), nút "Xem template của job"; nếu là hàng cá nhân hoá có thêm link "Gen design custom" trỏ sang `design-tool.printerval.com?tab=design-job&code=Printerval-<DJ code>` |
| Custom configuration | (chỉ có ở đơn cá nhân hoá) tên/số tuỳ chỉnh khách yêu cầu + **bản dịch tiếng Việt tự động** kèm theo |
| Designer | dropdown chọn account (xem mục 3) |
| Note outsource | text tự do, double-click để sửa — ghi chú nội bộ admin↔designer |
| Tiền phạt | input tiền + nút Lưu riêng |
| Order note | text hiển thị link nguồn (eBay/Etsy/trang bán khác) của đơn — tài liệu tham khảo cho designer; đôi khi có thêm "Delivery note" |
| Status | dropdown 6 giá trị (mục 1) |

## 6. Quy mô

Pagination cuối trang: **529 đơn** đang khớp filter mặc định (`Waiting+Doing+Fix`), hiển thị 40/trang → 14 trang. Đây là số đơn tồn đọng tại 1 thời điểm, không phải tốc độ/ngày — nhưng xác nhận quy mô đủ lớn để cần phân trang/queue đàng hoàng ngay từ Phase 2 (không thể xử lý thủ công từng trang).

## 7. Câu hỏi cần xác nhận (chưa chốt)

1. `Fix` vs `Confirm` khác nhau thế nào — ai/cái gì set mỗi cái? `Fix` có phải chính là kết quả **Edit** của QC nội bộ (B7) không?
2. `Review → Confirm → Done` hay `Review → Done` thẳng — `Confirm` có phải bước xác nhận của khách (ngoài tầm kiểm soát mình, giống case Skip đã mô tả) hay là bước nội bộ?
3. Cơ chế điểm (-5đ/lần Fix) và tiền phạt: hệ thống nội bộ có cần đọc để ưu tiên phân đơn (B3), hay bỏ qua vì đó là tính năng riêng của website?
4. Có mở khu vực quản lý tài khoản designer (Email/Mật khẩu/Quyền) để xem tiếp không? (khu vực có hiển thị mật khẩu plaintext — cần OK trước khi động vào)
5. 3 mốc thời gian (`Created at` / `Order created at` / `Deadline at`) — cái nào là "thời điểm claim" và cái nào dùng tính SLA/trễ hạn?
6. Có phải team hiện chỉ làm loại **2D** không, hay có làm cả 3D/ART/WOOD/CALENDAR/EMBROIDERY/AI trong phạm vi V1?
7. Ý nghĩa các mức màu của tag "Độ ưu tiên" (xám/cam...) — có ảnh hưởng thứ tự chọn đơn ở B3 không?

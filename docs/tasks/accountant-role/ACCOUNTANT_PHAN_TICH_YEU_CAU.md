# Role Kế toán (accountant) — Phân tích yêu cầu

Ngày: 29/09/2026. Trạng thái: **phân tích đã được xác nhận**, chờ duyệt kế hoạch.

## 0. Quyết định đã chốt (29/09)

- Accountant thanh toán = Admin thanh toán: cùng một luồng, cùng hệ quả (đơn Tacahu chuyển DONE, Telegram
  báo designer). "Chuyển DONE" chỉ là trạng thái nội bộ Tacahu, không ghi gì lên Printerval.
- Lịch sử thanh toán: cả accountant và Admin xem được. Admin có thêm nút "Xem lịch sử thanh toán" ở tab
  Tài chính & Công lao. Thanh toán do Admin làm cũng được ghi vào lịch sử.
- Designer chưa có QR: vẫn cho xác nhận đã trả.
- Accountant là tài khoản bình thường như designer/support (Admin tạo ở Quản lý tài khoản), không trang phụ.
- Không có môi trường dev: làm xong, test kỹ, commit thẳng lên `main`.
- Các suy luận ở mục 3 không bị phản đối, giữ nguyên.

## 1. Yêu cầu (nguyên văn, tóm gọn)

Thêm role `accountant`:

1. Thay Admin **thanh toán tiền công cho designer**. Admin giữ nguyên mọi chức năng, không thêm bớt.
2. Accountant chỉ thấy: **danh sách designer**, **số đơn chờ thanh toán** của mỗi người (không cần số
   đã thanh toán), và **mã QR** của từng designer. Mọi đơn chưa có tag "đã thanh toán" đều nằm ở đây.
3. Bấm vào một designer → **popup** liệt kê các đơn chưa thanh toán, **tổng tiền**, và nút **Thanh toán**.
4. Bấm Thanh toán → mở **popup QR** của designer. Chuyển khoản xong bấm **Xác nhận đã thanh toán** →
   cảnh báo **"Bạn chắc chắn đã thanh toán xong rồi chứ"** → Xác nhận → đóng popup, số đơn của designer
   về 0, chờ đơn mới đổ về.
5. Thanh toán xong thì các đơn đó biến mất khỏi danh sách, và **lưu lịch sử**: accountant nào, thanh
   toán bao nhiêu đơn, cho ai, lúc nào.
6. **Không hiển thị đơn giá** từng đơn cho accountant, chỉ số đơn và tổng tiền.

## 2. Hiện trạng thật (đã đọc code và dữ liệu production, chỉ đọc)

| Điểm | Hiện trạng |
|---|---|
| Role | Có 4 role: `admin`, `designer`, `designer-trello`, `support`. DB có ràng buộc `ck_users_role` chỉ cho 4 giá trị này → **cần migration** để thêm `accountant`. Form tạo tài khoản cũng chỉ chấp nhận 4 role. |
| Thanh toán | `POST /finance/mark-paid` chỉ cho Admin (so sánh cứng `role != "admin"`). Đặt `is_paid`, `paid_at`, `paid_by_id`, **tự chuyển đơn sang DONE**, ghi `WorkflowEvent` từng đơn, gửi Telegram báo designer. |
| Đơn "chờ thanh toán" | Hệ thống chỉ tính công cho đơn **đã có link bài nộp hợp lệ** (hoặc đã thanh toán). Đơn đang làm, chưa nộp thì không được tính. |
| Giá | Giá mặc định theo platform (thường/trùng) + giá riêng từng đơn (`custom_rate`, Admin sửa). |
| QR ngân hàng | Designer/Support tự tải ảnh QR lên. **Chỉ Admin** xem được QR của người khác. Production: 38 người có QR / 43 designer đang hoạt động → **khoảng 5 designer chưa có QR**. |
| Lịch sử thanh toán | **Chưa có** bảng "đợt thanh toán". Chỉ có dấu vết theo từng đơn (`paid_by_id`, `paid_at`, `WorkflowEvent` action `mark_paid`). Production: 501 đơn đã trả, tất cả do 1 người trả. |
| Platform | 2 platform, nhưng toàn bộ 43 designer và 1.247 đơn đều thuộc "Acc Mẹ: thuyhg.2210@gmail.com". |
| Phân quyền backend | **Rủi ro lớn:** nhiều endpoint chỉ chặn `designer`/`support`, role khác được xem như Admin (ví dụ `/finance/stats` trả cả đơn giá, danh sách đơn hàng...). Nếu chỉ thêm role mới mà không chặn, **accountant sẽ tự động đọc được gần như mọi thứ Admin đọc được.** |
| Frontend | Menu và trang đích sau đăng nhập chia theo role; role lạ hiện đang rơi vào menu của designer và trang `/orders`. |

## 3. Phân loại

### Đã xác nhận (từ yêu cầu + code)
- Accountant là role mới, riêng biệt; Admin không đổi gì.
- Accountant thanh toán được, xem được QR của designer, không thấy đơn giá từng đơn.
- Cần lưu lịch sử theo **đợt thanh toán** (ai, bao nhiêu đơn, cho ai, lúc nào) → cần bảng mới.
- Cần migration role + chặn accountant khỏi mọi chức năng khác (deny-by-default).

### Đang suy luận (cần bạn xác nhận)
1. **"Chờ thanh toán" = đơn chưa thanh toán VÀ đã được tính công** (đã nộp link), giống đúng con số
   "Chưa thanh toán" Admin đang thấy. Đơn đang làm dở chưa nộp **không** hiện cho accountant.
2. Popup của accountant **không chia theo tuần** như popup của Admin: hiện **tất cả** đơn chờ của designer,
   thanh toán một lần.
3. Accountant **không hủy được** thanh toán; hủy vẫn chỉ Admin làm.
4. Accountant **không sửa được giá**; giá vẫn do Admin quyết định.
5. Thanh toán qua accountant **giữ nguyên hệ quả hiện tại**: đơn chuyển DONE và designer nhận tin
   Telegram báo thanh toán.
6. Accountant chỉ làm việc trên **platform của tài khoản mình** (như Support), không đổi platform.
7. Hệ thống thanh toán **đúng những đơn đang hiện trong popup** lúc accountant mở nó. Nếu trong lúc
   chuyển khoản có đơn mới đổ về hoặc Admin đổi giá, hệ thống **từ chối** và yêu cầu mở lại, thay vì
   trả luôn số tiền khác với số accountant đã chuyển.

### Cần hỏi thêm
- **A. Ai xem lịch sử thanh toán?** Chỉ accountant (của chính mình / của mọi accountant), hay cả Admin
  (thêm một mục mới cho Admin — nhưng bạn nói Admin "không thêm bớt gì")?
- **B. Designer chưa có QR** thì sao? Vẫn cho bấm Xác nhận (trả bằng cách khác), hay chặn không cho trả?
- **C. Admin thanh toán** trên trang Tài chính hiện tại có được ghi vào lịch sử đợt thanh toán không,
  hay lịch sử chỉ dành cho accountant?
- **D. Accountant có trang nào khác không** (ví dụ tự đổi mật khẩu), hay chỉ đúng một trang thanh toán?

## 4. Về quy trình git

Repo này từ trước tới nay **commit thẳng lên `main`** (push là CI tự deploy), không dùng nhánh riêng +
merge request. Việc này lớn hơn các sửa trước (migration, role mới, phân quyền) nên tôi đề xuất làm trên
**nhánh riêng** và mở PR vào `main` để bạn duyệt trước khi deploy. Bạn chọn: nhánh riêng + PR, hay
vẫn làm thẳng trên `main` như cũ?

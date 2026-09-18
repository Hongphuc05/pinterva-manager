# ⚡ Tacahu POD - Printerval Gallery Sync & Copy Tool (Extension)

Tiện ích mở rộng Google Chrome (Manifest V3) chuyên dụng cho **Tacahu Ops** & **Printerval**:
1. **Quét siêu tốc bộ ảnh đầy đủ của sản phẩm trên Printerval** qua Sales URL.
2. **Click-to-Copy ảnh gốc (HD 960x960)**: Chỉ cần 1 cú click để copy trực tiếp Image Blob hoặc Link ảnh vào Clipboard.
3. **Đồng bộ hàng loạt về Tacahu Ops (Batch Sync)**: 1 cú click đồng bộ toàn bộ ảnh của tất cả các đơn hàng trên trang vào cơ sở dữ liệu Tacahu Ops, loại bỏ hoàn toàn việc phải đồng bộ thủ công từng đơn.

---

## 🛠 Hướng Dẫn Cài Đặt (Chỉ mất 1 phút)

1. Mở trình duyệt Google Chrome, truy cập địa chỉ: `chrome://extensions/`
2. Bật chế độ **Chế độ dành cho nhà phát triển (Developer mode)** ở góc trên bên phải.
3. Nhấp vào nút **Tải tiện ích đã giải nén (Load unpacked)** ở góc trên bên trái.
4. Chọn thư mục `CopyImage` trong dự án:
   ```
   /Users/hongphuc/Documents/01_congViec/pinterval/CopyImage
   ```
5. Tiện ích **Tacahu POD - Printerval Gallery Sync & Copy Tool** sẽ xuất hiện trên thanh tiện ích Chrome.

---

## ⚙️ Cấu Hình (Tùy chọn)

1. Nhấp chuột phải vào biểu tượng tiện ích trên Chrome $\rightarrow$ Chọn **Tùy chọn (Options)**.
2. Điền địa chỉ API của Tacahu Ops:
   - **Chạy trên VPS Production**: `https://tacahu.fun` (bấm nút preset `🌐 VPS: https://tacahu.fun`)
   - **Chạy trên máy Local**: `http://localhost:8000` (bấm nút preset `💻 Local: http://localhost:8000`)
3. Nhấn **Kiểm tra (Test Connection)** để đảm bảo hiện thông báo xanh *"✓ Kết nối thành công tới Tacahu Ops!"*.
4. Bật tùy chọn *"Tự động quét bộ ảnh ngay khi mở trang Design Job"* nếu muốn đồng bộ tự động.
5. Nhấn **Lưu Cấu Hình**.

---

## 🚀 Hướng Dẫn Sử Dụng Trên Printerval

### Cách 1: Quét & Đồng Bộ Toàn Bộ Trang (Batch Sync)
1. Truy cập trang quản lý đơn trên Printerval (ví dụ: Tab Waiting / Design Job).
2. Ở góc trên bên phải màn hình sẽ có thanh công cụ **Tacahu Sync**:
   - Nhấn nút **`Quét & Đồng Bộ Bộ Ảnh`**.
   - Extension sẽ tự động quét tất cả đơn hàng trên trang với 5 luồng song song.
   - Khi quét xong, toàn bộ ảnh sẽ được gửi 1 lần về Tacahu Ops qua API `POST /api/integrations/printerval-gallery/batch`.
   - Các đơn hàng trên Tacahu Ops sẽ tự động hiển thị đầy đủ bộ ảnh ngay lập tức!

### Cách 2: Xem Trước & Click-to-Copy
1. Dưới mỗi mã đơn `DJ...` trên bảng Printerval, nhấn nút **`⚡ Quét ảnh`**.
2. Bộ ảnh thu nhỏ (thumbnail) sẽ hiện ra:
   - Rê chuột vào ảnh để xem bản phóng to 280x280px.
   - **Click chuột trái vào ảnh**: Ảnh sẽ được copy thẳng vào Clipboard (sẵn sàng Paste vào Photoshop/Figma/Web).

# CopyImage gallery bridge

Extension này lấy gallery từ trang sản phẩm Printerval trong Chrome đang đăng nhập,
rồi gửi URL ảnh về đúng task trên Tacahu Ops. Nó không gửi hay lưu cookie Printerval.

1. Vào `chrome://extensions`, bật **Developer mode**, chọn **Load unpacked** và chọn thư mục `CopyImage`.
2. Trên Tacahu Ops, mở **Acc Mẹ Printerval** đúng platform, bấm **Tạo token CopyImage** và sao chép token.
3. Trong modal Acc Mẹ Printerval, sao chép **Platform ID** vừa hiển thị và token CopyImage.
4. Mở **Details** của extension, chọn **Extension options**, điền:
   - Địa chỉ backend: URL backend đang được Vercel dùng, ví dụ `https://desktop-p259ei0.tailea8fce.ts.net`.
   - Platform ID: giá trị vừa sao chép trong modal Acc Mẹ Printerval.
   - Token CopyImage vừa tạo.
5. Trên bảng Design Job Printerval, mỗi dòng có nút **Quét & đồng bộ ảnh**. Bấm nút đó sau khi crawl task về. Khi thành công, web Tacahu Ops hiển thị toàn bộ gallery trong trang chi tiết task.

Khi đổi Acc Mẹ/platform, luôn tạo token mới và thay **cả Platform ID lẫn token** trong options trước khi đồng bộ ảnh.

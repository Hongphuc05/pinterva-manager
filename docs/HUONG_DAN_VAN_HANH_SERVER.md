# 📖 CẨM NANG VẬN HÀNH SERVER TACAHU (TỪ A - Z)

> **Mục lục:**
> 1. [Khi PC Bật Lên (Sau khi mất điện / khởi động lại)](#1-khi-pc-bật-lên-sau-khi-mất-điện--khởi-động-lại)
> 2. [Cách Tự Động Hóa 100% (Không cần đụng vào PC)](#2-cách-tự-động-hóa-100-không-cần-đụng-vào-pc)
> 3. [Từ Máy Mac: Kiểm Tra Health & Giám Sát Server](#3-từ-máy-mac-kiểm-tra-health--giám-sát-server)
> 4. [Kiểm Tra & Vận Hành GitHub Actions (CI/CD Tự Động)](#4-kiểm-tra--vận-hành-github-actions-cicd-tự-động)
> 5. [Các Lệnh Xử Lý Sự Cố Khẩn Cấp](#5-các-lệnh-xử-lý-sự-cố-khẩn-cấp)

---

## 📌 THÔNG TIN HỆ THỐNG
* **IP Tailscale của PC:** `100.88.171.114`
* **Tài khoản SSH:** `tacahu@100.88.171.114` (Port `22`)
* **API URL Công Khai Vĩnh Viễn:** `https://desktop-p259ei0.tailea8fce.ts.net`
* **Thư mục chạy Server:** `/srv/tacahu`
* **Thư mục CI/CD Runner:** `~/actions-runner`
* **Frontend Dashboard:** [https://tacahu-ops.vercel.app](https://tacahu-ops.vercel.app)
* **GitHub Repository:** [Hongphuc05/pinterva-manager](https://github.com/Hongphuc05/pinterva-manager)

---

## 1. KHI PC BẬT LÊN (Sau khi mất điện / khởi động lại)

### ❓ Trả lời câu hỏi: "Chỉ cần SSH từ Mac có được không?"
* **Nguyên lý:** Khi PC vừa bật, Windows sẽ cấp một IP nội bộ ngẫu nhiên mới cho máy ảo Ubuntu WSL2, đồng thời các dịch vụ ngầm (SSH, Docker, Runner) chưa chạy. Vì vậy, máy Mac **chưa thể SSH vào ngay được** cho đến khi Windows chạy lệnh mở cổng kết nối.
* **Cách xử lý:** Bạn chỉ cần thực hiện **1 cú click chuột** trên PC, sau đó toàn bộ việc còn lại làm từ Mac!

### Thao tác 1-Click trên PC:
1. Bạn đã có file `start-server.bat` trên màn hình Desktop của PC.
2. Bấm chuột phải vào file **`start-server.bat`** ➔ Chọn **"Run as Administrator"**.
3. Màn hình đen chạy khoảng 5-10 giây, báo `SERVER VA CI/CD DA KHOI DONG THANH CONG!` là xong!

*(Nội dung file `start-server.bat` dự phòng nếu cần tạo lại):*
```bat
@echo off
echo [1/4] Cap nhat IP WSL va mo Firewall Port 22...
powershell -Command "$wsl_ip = (wsl hostname -I).Trim().Split(' ')[0]; netsh interface portproxy delete v4tov4 listenport=22 listenaddress=0.0.0.0; netsh interface portproxy add v4tov4 listenport=22 listenaddress=0.0.0.0 connectport=22 connectaddress=$wsl_ip; netsh advfirewall firewall add rule name='Allow SSH 22' dir=in action=allow protocol=TCP localport=22"

echo [2/4] Khoi dong OpenSSH va Docker trong WSL...
wsl -u root service ssh restart
wsl -u root service docker restart

echo [3/4] Bat toan bo he thong Tacahu Server...
wsl -u tacahu bash -c "cd /srv/tacahu && docker compose up -d"

echo [4/5] Bat GitHub Actions Runner cho CI/CD...
wsl -u tacahu bash -c "cd ~/actions-runner && (pgrep -f Runner.Listener > /dev/null || nohup ./run.sh > runner.log 2>&1 &)"

echo [5/5] Dam bao Tailscale Funnel HTTPS online...
tailscale funnel --bg 8000

echo ===================================================
echo SERVER, FUNNEL VA CI/CD DA KHOI DONG THANH CONG!
echo ===================================================
pause
```

---

## 2. CÁCH TỰ ĐỘNG HÓA 100% (Không cần đụng vào PC)

Nếu bạn muốn khi PC có điện và bật lên, server tự chạy hết mà **không cần bấm chuột hay ngồi vào máy PC**:

1. Trên PC, nhấn tổ hợp phím `Win + R`, gõ `shell:startup` rồi bấm **Enter** (thư mục Startup tự mở ra).
2. Bấm chuột phải vào file `start-server.bat` ngoài Desktop ➔ Chọn **Create shortcut** (Tạo lối tắt).
3. Kéo file Shortcut đó bỏ vào thư mục Startup vừa mở.
4. Bấm chuột phải vào file Shortcut trong Startup ➔ **Properties** ➔ tab **Shortcut** ➔ bấm nút **Advanced...** ➔ tích chọn **Run as administrator** ➔ bấm **OK**.

👉 *Từ nay, khi có điện lại, PC tự bật vào Windows, file này tự chạy ngầm, bạn chỉ việc ngồi ở quán cafe mở máy Mac lên là dùng!*

---

## 3. TỪ MÁY MAC: KIỂM TRA HEALTH & GIÁM SÁT SERVER

Mở Terminal trên máy Mac (đảm bảo Tailscale trên Mac đang bật):

### Bước 1: Đăng nhập SSH vào Server
```bash
ssh tacahu@100.88.171.114
```

### Bước 2: Kiểm tra trạng thái các Container (Health Check)
```bash
cd /srv/tacahu && docker compose ps
```
* **Kết quả chuẩn:** Tất cả 6 container đều ở trạng thái `Up` hoặc `Up (healthy)`:
  - `tacahu-ops-api-1`: Backend FastAPI
  - `tacahu-ops-redis-1`: Bộ nhớ đệm Redis
  - `tacahu-ops-celery-assignment-1`: Worker chia việc outsource
  - `tacahu-ops-celery-general-1`: Worker crawl & sync
  - `tacahu-ops-celery-beat-1`: Bộ đếm lịch trình tự động
  - `tacahu-quick-tunnel`: Đường hầm Cloudflare ra Internet

### Bước 3: Kiểm tra API Backend phản hồi
```bash
curl http://localhost:8000/api/health
```
* Phải trả về: `{"status":"ok"}`.

### Bước 4: Xem đường link Cloudflare Tunnel hiện tại
```bash
docker logs tacahu-quick-tunnel 2>&1 | grep -o 'https://[-a-z0-9.]*trycloudflare.com' | tail -n 1
```

### Bước 5: Xem Log trực tiếp khi cần soi lỗi (Live Logs)
* **Xem log API Backend:**
  ```bash
  cd /srv/tacahu && docker compose logs -f --tail=100 api
  ```
* **Xem log quét đơn & cập nhật trạng thái Printerval:**
  ```bash
  cd /srv/tacahu && docker compose logs -f --tail=100 celery_general
  ```
* **Xem log phân công việc:**
  ```bash
  cd /srv/tacahu && docker compose logs -f --tail=100 celery_assignment
  ```
*(Bấm `Ctrl + C` trên bàn phím để thoát xem log).*

---

## 4. KIỂM TRA & VẬN HÀNH GITHUB ACTIONS (CI/CD TỰ ĐỘNG)

### 1. Quy trình CI/CD hoạt động như thế nào?
1. Bạn sửa code trên máy Mac.
2. Bạn gõ lệnh:
   ```bash
   git add .
   git commit -m "update feature"
   git push origin main
   ```
3. **Frontend:** Vercel tự động build và cập nhật web trong 1-2 phút.
4. **Backend:** GitHub kích hoạt Runner trên PC ➔ PC tự động tải code mới vào `/srv/tacahu` ➔ Tự chạy `docker compose up -d --build` để khởi động lại container backend với code mới.

### 2. Cách kiểm tra tiến trình Deploy trên Web GitHub:
1. Mở trang: [https://github.com/Hongphuc05/pinterva-manager/actions](https://github.com/Hongphuc05/pinterva-manager/actions)
2. Bạn sẽ thấy workflow có tên **Deploy to Self-Hosted PC Server**:
   - 🟡 **Màu vàng (đang quay):** PC đang tải code và build lại backend.
   - 🟢 **Màu xanh lá:** Deploy thành công 100%!
   - 🔴 **Màu đỏ:** Bị lỗi, bấm vào xem chi tiết bước nào bị hỏng.

### 3. Cách kiểm tra Runner trên PC (qua SSH từ Mac):
Kiểm tra xem Runner có đang chạy ngầm và lắng nghe không:
```bash
ps aux | grep Runner.Listener
```
Xem log của Runner:
```bash
tail -n 20 ~/actions-runner/runner.log
```
*(Nếu thấy dòng `Listening for Jobs` là runner đang hoạt động hoàn hảo).*

Nếu Runner bị tắt, bật lại bằng lệnh:
```bash
cd ~/actions-runner && nohup ./run.sh > runner.log 2>&1 &
```

---

## 5. CÁC LỆNH XỬ LÝ SỰ CỐ KHẨN CẤP

### 1. Khởi động lại toàn bộ hệ thống Server:
```bash
cd /srv/tacahu && docker compose restart
```

### 2. Build lại từ đầu nếu code không nhận:
```bash
cd /srv/tacahu && docker compose up -d --build
```

### 3. Xóa cache và khởi động lại sạch sẽ:
```bash
cd /srv/tacahu
docker compose down
docker compose up -d
```

### 4. Khởi động lại máy PC từ xa qua Mac:
```bash
ssh tacahu@100.88.171.114 "sudo reboot"
```
*(Sau khi PC bật lại, nếu đã cài Bước 2 thì server sẽ tự động sống lại).*

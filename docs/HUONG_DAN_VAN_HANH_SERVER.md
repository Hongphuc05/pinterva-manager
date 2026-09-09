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
* **API URL qua Tailscale Funnel:** `https://desktop-p259ei0.tailea8fce.ts.net`
* **Thư mục chạy Server:** `/srv/tacahu`
* **Thư mục CI/CD Runner:** `~/actions-runner`
* **Frontend Dashboard:** [https://tacahu-ops.vercel.app](https://tacahu-ops.vercel.app)
* **GitHub Repository:** [Hongphuc05/pinterva-manager](https://github.com/Hongphuc05/pinterva-manager)

---

## 1. KHI PC BẬT LÊN (Sau khi mất điện / khởi động lại)

### Vì sao SSH có thể timeout ngay sau mất điện?

Khi PC vừa bật, Windows cần thời gian khởi động WSL2. IP nội bộ của WSL2 có thể đổi, sau đó script phải cập nhật Windows port proxy cho SSH, rồi OpenSSH và Docker trong WSL mới sẵn sàng. Trong giai đoạn này, `ssh ...` timeout là bình thường; không phải lỗi username hay SSH key.

Đợi khoảng 2–5 phút sau khi PC lên Windows, rồi từ Mac kiểm tra lại bằng lệnh không mở shell:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 tacahu@100.88.171.114 "hostname"
```

Nếu lệnh trả về `DESKTOP-P259EI0` thì PC đã sẵn sàng để vận hành từ Mac.

### Thao tác 1-Click trên PC:
1. Bạn đã có file `start-server.bat` trên màn hình Desktop của PC.
2. Bấm chuột phải vào file **`start-server.bat`** ➔ Chọn **"Run as Administrator"**.
3. Màn hình đen chạy khoảng 5-10 giây, báo `SERVER VA CI/CD DA KHOI DONG THANH CONG!` là xong!

*(Nội dung file `start-server.bat` dự phòng nếu cần tạo lại):*
```bat
@echo off
echo [1/5] Cap nhat IP WSL va mo Firewall Port 22...
powershell -Command "$wsl_ip = (wsl hostname -I).Trim().Split(' ')[0]; netsh interface portproxy delete v4tov4 listenport=22 listenaddress=0.0.0.0; netsh interface portproxy add v4tov4 listenport=22 listenaddress=0.0.0.0 connectport=22 connectaddress=$wsl_ip; netsh advfirewall firewall add rule name='Allow SSH 22' dir=in action=allow protocol=TCP localport=22"

echo [2/5] Khoi dong OpenSSH va Docker trong WSL...
wsl -u root service ssh restart
wsl -u root service docker restart

echo [3/5] Bat toan bo he thong Tacahu Server...
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

## 2. CÁCH TỰ ĐỘNG HÓA SAU MẤT ĐIỆN

Không dùng riêng `shell:startup` cho production: thư mục này chỉ chạy sau khi người dùng Windows đăng nhập, và quyền Administrator có thể bị chặn bởi UAC. Dùng **Task Scheduler** để chạy không cần đăng nhập.

1. Mở **Task Scheduler** trên PC → **Create Task**.
2. Tab **General**:
   - Name: `Start Tacahu Server`
   - Chọn **Run whether user is logged on or not**.
   - Chọn **Run with highest privileges**.
3. Tab **Triggers** → **New** → chọn **At startup**.
4. Tab **Actions** → **New**:
   - Program/script: đường dẫn đầy đủ tới `start-server.bat`, ví dụ `C:\Users\<Windows-user>\Desktop\start-server.bat`.
   - Start in: `C:\Users\<Windows-user>\Desktop`.
5. Tab **Conditions**: bỏ chọn điều kiện chỉ chạy khi cắm điện nếu PC là server cố định.
6. Tab **Settings**: bật **Run task as soon as possible after a scheduled start is missed**.
7. Bấm **OK**, nhập mật khẩu Windows nếu được hỏi, rồi chọn **Run** một lần để thử.

Sau khi test, rút/bật lại nguồn hoặc restart PC; từ Mac chạy lệnh kiểm tra SSH ở phần 1 rồi kiểm tra health ở phần 3.

---

## 3. TỪ MÁY MAC: KIỂM TRA HEALTH & GIÁM SÁT SERVER

Mở Terminal trên máy Mac (đảm bảo Tailscale trên Mac đang bật):

### Bước 1: Đăng nhập SSH vào Server
```bash
ssh -tt tacahu@100.88.171.114 'bash -il'
```

`-tt` cấp terminal và `bash -il` ép mở shell interactive có prompt. Nếu chỉ cần chạy một lệnh thì dùng dạng sau, không cần mở shell:

```bash
ssh tacahu@100.88.171.114 "cd /srv/tacahu && docker compose ps"
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
  - `tacahu-ops-cloudflared-1`: Đường hầm Cloudflare ra Internet

### Bước 3: Kiểm tra API Backend phản hồi
```bash
curl http://localhost:8000/api/health
```
* Phải trả về: `{"status":"ok"}`.

### Bước 4: Kiểm tra Cloudflare Tunnel
```bash
cd /srv/tacahu && docker compose logs --tail=100 cloudflared
```

### Bước 5: Xem Log trực tiếp khi cần soi lỗi (Live Logs)
* **Xem log API Backend:**
  ```bash
  cd /srv/tacahu && docker compose logs -f --tail=100 api
  ```
* **Xem log quét đơn & cập nhật trạng thái Printerval:**
  ```bash
  cd /srv/tacahu && docker compose logs -f --tail=100 celery-general
  ```
* **Xem log phân công việc:**
  ```bash
  cd /srv/tacahu && docker compose logs -f --tail=100 celery-assignment
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
Không dùng `docker compose down -v`: lệnh đó xóa volumes, có thể làm mất Redis và dữ liệu runtime chưa backup.

### 4. Khởi động lại máy PC từ xa qua Mac:
```bash
ssh tacahu@100.88.171.114 "sudo reboot"
```
*(Sau khi PC bật lại, nếu đã cài Bước 2 thì server sẽ tự động sống lại).*

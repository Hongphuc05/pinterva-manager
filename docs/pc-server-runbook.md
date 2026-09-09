# Hướng Dẫn Vận Hành PC Server Từ A-Z (Tacahu Ops)

Tài liệu hướng dẫn quy trình vận hành toàn diện cho máy tính **PC Windows 10 (WSL2 Ubuntu 20.04)** chạy Server Backend và máy **Mac** điều khiển từ xa qua mạng riêng ảo **Tailscale**.

---

## 📌 THÔNG TIN HỆ THỐNG
* **PC Windows Tailscale IP:** `100.88.171.114`
* **User Ubuntu WSL:** `tacahu`
* **Thư mục Server:** `/srv/tacahu`
* **Frontend Dashboard:** [https://tacahu-ops.vercel.app](https://tacahu-ops.vercel.app) (tự động build từ Vercel khi push git)

---

## PHẦN 1: KHI BẬT MÁY PC LÊN (Khởi Động Server Trên PC)

Do Windows 10 khởi động lại sẽ cấp IP nội bộ mới cho WSL2 và các dịch vụ nền chưa tự chạy, bạn cần khởi động theo 1 trong 2 cách sau:

### Cách 1: Dùng File Tự Động 1-Click (Khuyên Dùng)
1. Trên màn hình Desktop của Windows 10, tạo 1 file text mới và đổi tên thành: `start-server.bat`.
2. Bấm chuột phải vào file chọn **Edit** (hoặc mở bằng Notepad), dán toàn bộ nội dung sau vào:

```bat
@echo off
echo ===================================================
echo [1/4] Cap nhat IP WSL va mo Firewall Port 22...
echo ===================================================
powershell -Command "$wsl_ip = (wsl hostname -I).Trim().Split(' ')[0]; netsh interface portproxy delete v4tov4 listenport=22 listenaddress=0.0.0.0; netsh interface portproxy add v4tov4 listenport=22 listenaddress=0.0.0.0 connectport=22 connectaddress=$wsl_ip; netsh advfirewall firewall add rule name='Allow SSH 22' dir=in action=allow protocol=TCP localport=22"

echo ===================================================
echo [2/4] Khoi dong OpenSSH va Docker Daemon trong WSL...
echo ===================================================
wsl -u root service ssh restart
wsl -u root service docker restart

echo ===================================================
echo [3/4] Bat toan bo he thong Tacahu Server...
echo ===================================================
wsl -u tacahu bash -c "cd /srv/tacahu && docker compose up -d"

echo ===================================================
echo [4/4] Bat GitHub Actions Runner cho CI/CD...
echo ===================================================
wsl -u tacahu bash -c "cd ~/actions-runner && (pgrep -f Runner.Listener > /dev/null || nohup ./run.sh > runner.log 2>&1 &)"

echo.
echo ===================================================
echo SERVER VA CI/CD DA KHOI DONG THANH CONG!
echo ===================================================
pause
```
3. Lưu lại. Từ nay mỗi khi bật máy PC, bạn chỉ cần **bấm chuột phải vào file `start-server.bat` -> chọn "Run as Administrator"** là xong toàn bộ!

---

### Cách 2: Chạy Thủ Công Bằng Dòng Lệnh
Nếu không dùng file `.bat`, bạn thao tác 2 bước sau:

* **Bước A: Bật dịch vụ trong Ubuntu WSL**
  Mở terminal Ubuntu trên PC gõ:
  ```bash
  sudo service ssh restart
  sudo service docker restart
  cd /srv/tacahu && docker compose up -d
  ```

* **Bước B: Cập nhật Port 22 trên Windows CMD (Administrator)**
  Mở Command Prompt (CMD) bằng quyền Admin và dán:
  ```cmd
  powershell -Command "$wsl_ip = (wsl hostname -I).Trim().Split(' ')[0]; netsh interface portproxy delete v4tov4 listenport=22 listenaddress=0.0.0.0; netsh interface portproxy add v4tov4 listenport=22 listenaddress=0.0.0.0 connectport=22 connectaddress=$wsl_ip; netsh advfirewall firewall add rule name='Allow SSH 22' dir=in action=allow protocol=TCP localport=22"
  ```

---

## PHẦN 2: TỪ MÁY MAC (Kết Nối, Kiểm Tra Health & Xem Log)

Trên máy Mac (kết nối qua Tailscale ở bất kỳ đâu):

### 1. Đăng nhập SSH vào PC
```bash
ssh tacahu@100.88.171.114
```

### 2. Kiểm tra Health của các Containers
Sau khi đã vào terminal của PC:
```bash
cd /srv/tacahu
docker compose ps
```
*Trạng thái bình thường:* Tất cả 5 containers (`api`, `redis`, `celery_worker`, `celery_beat`, `tunnel`) đều có cột STATUS là `Up` hoặc `Up (healthy)`.

### 3. Kiểm tra Health của API Backend
Chạy lệnh kiểm tra nhanh endpoint trả về JSON:
```bash
curl http://localhost:8000/api/health
```
*(Kết quả trả về `{"status":"ok",...}` là API hoạt động hoàn hảo).*

### 4. Xem Log Trực Tiếp (Live Debugging)
* **Xem log API Backend:**
  ```bash
  cd /srv/tacahu && docker compose logs -f --tail=100 api
  ```
* **Xem log Celery Worker (quét đơn hàng, sync trạng thái outsource):**
  ```bash
  cd /srv/tacahu && docker compose logs -f --tail=100 celery_worker
  ```
* **Xem log Cloudflare Tunnel:**
  ```bash
  cd /srv/tacahu && docker compose logs -f --tail=50 tunnel
  ```
*(Bấm tổ hợp phím `Ctrl + C` để thoát chế độ xem log).*

### 5. Khởi động lại hoặc dừng Server khi cần
* Khởi động lại toàn bộ:
  ```bash
  cd /srv/tacahu && docker compose restart
  ```
* Khởi động lại chỉ riêng backend:
  ```bash
  cd /srv/tacahu && docker compose restart api
  ```
* Tắt hẳn server:
  ```bash
  cd /srv/tacahu && docker compose down
  ```

---

## PHẦN 3: TỰ ĐỘNG CI/CD (Push Code Lên Git ➔ PC Tự Động Cập Nhật)

Hệ thống CI/CD tự động hoạt động theo nguyên lý:
1. Bạn sửa code trên Mac và chạy: `git push origin main`.
2. **Vercel** tự động build và deploy Frontend: `https://tacahu-ops.vercel.app`.
3. **GitHub Actions Self-Hosted Runner** trên PC nhận lệnh, tự động pull code mới về `/srv/tacahu` và chạy `docker compose up -d --build`.

---

### Bước 1: Cài đặt GitHub Runner trên PC (Chỉ làm 1 lần duy nhất)

1. Mở trình duyệt trên máy Mac, truy cập trang tạo Runner của Repo:
   👉 `https://github.com/Hongphuc05/pinterva-manager/settings/actions/runners/new?arch=x64&os=linux`

2. SSH vào máy PC (`ssh tacahu@100.88.171.114`) và chạy các lệnh:
   ```bash
   # Tạo thư mục runner
   mkdir -p ~/actions-runner && cd ~/actions-runner

   # Tải bộ cài đặt runner từ GitHub
   curl -o actions-runner-linux-x64-2.321.0.tar.gz -L https://github.com/actions/runner/releases/download/v2.321.0/actions-runner-linux-x64-2.321.0.tar.gz
   tar xzf ./actions-runner-linux-x64-2.321.0.tar.gz

   # Kết nối runner với Repo (thay <TOKEN> bằng token hiển thị trên trang GitHub của bạn)
   ./config.sh --url https://github.com/Hongphuc05/pinterva-manager --token <TOKEN_HIEN_THI_TREN_GITHUB>
   ```
   *(Khi terminal hỏi cấu hình tên runner, work folder... bạn chỉ cần nhấn `Enter` liên tục để nhận giá trị mặc định).*

3. Cài runner thành Service tự chạy ngầm cùng hệ thống:
   ```bash
   sudo ./svc.sh install
   sudo ./svc.sh start
   ```

---

### Bước 2: Cấu hình Workflow Tự Động Trong Code (`.github/workflows/deploy.yml`)

File cấu hình `.github/workflows/deploy.yml` trong mã nguồn dự án:

```yaml
name: Deploy to Self-Hosted PC Server

on:
  push:
    branches: [ main ]

jobs:
  deploy:
    runs-on: self-hosted
    steps:
      - name: Deploy Tacahu Server
        run: |
          echo "Bắt đầu cập nhật mã nguồn mới nhất..."
          cd /srv/tacahu
          git fetch origin main
          git reset --hard origin/main
          docker compose up -d --build
          docker compose ps
```

Từ thời điểm này trở đi:
* Mọi thay đổi bạn commit và `git push origin main` từ Mac sẽ **tự động deploy lên PC 100%**, không cần gõ lệnh thủ công nữa!

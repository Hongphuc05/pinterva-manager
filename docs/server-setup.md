# Hướng Dẫn Thiết Lập PC Windows 10 Pro Chạy Server 24/7 (Tacahu Ops)

Tài liệu hướng dẫn thiết lập máy tính **Windows 10 Pro** chạy 24/7 làm production server cho backend Tacahu Ops Dashboard thông qua **WSL2 (Ubuntu 20.04 LTS)** và **Docker**.

---

## 1. Cấu hình BIOS & Windows 10 Power Settings (Chạy 24/7)

### Bước 1: BIOS Power Management (Tự bật máy khi có điện)
1. Khởi động lại PC, nhấn `F2`, `Del` hoặc `F12` để vào BIOS.
2. Tìm mục **Power Management** (hoặc **ACPI Configuration** / **Advanced**).
3. Tìm tùy chọn **"Restore on AC Power Loss"** (hoặc **"State After G3"** / **"AC Back"**) ➔ Chọn **"Power On"** (máy sẽ tự động bật khi có điện trở lại sau cúp điện).
4. Nhấn `F10` để lưu và khởi động vào Windows 10.

### Bước 2: Tắt chế độ Sleep / Hibernate trên Windows 10
1. Mở **Settings** (`Win + I`) ➔ **System** ➔ **Power & sleep**.
2. Tại mục **Sleep**:
   * **When plugged in, PC goes to sleep after:** Chọn **Never** *(Bắt buộc)*.
3. Tắt **Fast Startup**:
   * Mở Start menu, gõ `Control Panel` ➔ **Power Options** ➔ **Choose what the power buttons do**.
   * Nhấn vào *Change settings that are currently unavailable*.
   * Bỏ tích chọn **Turn on fast startup (recommended)** ➔ Nhấn **Save changes**.

### Bước 3: Cấu hình Tự Đăng Nhập Windows (Auto-Login)
1. Nhấn tổ hợp phím `Win + R`, gõ `netplwiz` rồi Enter.
2. Bỏ tích ô **"Users must enter a user name and password to use this computer"**.
3. Nhấn **Apply**, nhập mật khẩu tài khoản Windows hiện tại 2 lần để xác nhận ➔ Nhấn **OK**.

---

## 2. Cài đặt Docker & OpenSSH bên trong Ubuntu 20.04 (WSL2)

Mở terminal **Ubuntu 20.04**, copy và chạy lần lượt các khối lệnh sau:

### Bước 1: Cập nhật hệ thống & cài OpenSSH, rsync
```bash
sudo apt update && sudo apt install -y openssh-server rsync curl ca-certificates
```

### Bước 2: Cài đặt Docker Engine (Docker CE) chính thức
```bash
# Thêm GPG key Docker
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Thêm kho lưu trữ Docker cho Ubuntu 20.04 (focal)
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu focal stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### Bước 3: Phân quyền user & Khởi động dịch vụ
```bash
sudo usermod -aG docker $USER
sudo service ssh start
sudo service docker start
```

Kiểm tra Docker đã sẵn sàng:
```bash
docker --version
docker compose version
```

---

## 3. Cấu hình Windows 10 Port Forwarding cho SSH (Port 22)

Vì Windows 10 sử dụng mạng NAT cho WSL2, ta cần chuyển tiếp (forward) port 22 từ card mạng Windows vào Ubuntu WSL2 để máy Mac có thể SSH vào.

Mở **Windows PowerShell (Run as Administrator)** trên máy Windows 10 và chạy đoạn script sau:

```powershell
# 1. Lấy địa chỉ IP nội bộ của Ubuntu WSL2
$wsl_ip = (wsl hostname -I).Trim().Split(" ")[0]

# 2. Xóa cấu hình cũ (nếu có) và tạo forward cổng 22 từ Windows vào WSL
netsh interface portproxy delete v4tov4 listenport=22 listenaddress=0.0.0.0 | Out-Null
netsh interface portproxy add v4tov4 listenport=22 listenaddress=0.0.0.0 connectport=22 connectaddress=$wsl_ip

# 3. Mở cổng tường lửa (Windows Firewall) cho Port 22
New-NetFirewallRule -Name "Allow-SSH-Port-22" -DisplayName "Allow SSH Port 22" -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow -ErrorAction SilentlyContinue

Write-Host "Da forward Port 22 thanh cong vao WSL IP: $wsl_ip" -ForegroundColor Green
```

---

## 4. Tạo cấu trúc thư mục Server (`/srv/tacahu`)

Quay lại terminal **Ubuntu 20.04**, chạy lệnh tạo các thư mục lưu trữ:
```bash
sudo mkdir -p /srv/tacahu/app
sudo mkdir -p /srv/tacahu/data/{crawled_assets,order_assets,platform_data,playwright_evidence,chrome_profiles,redis}
sudo mkdir -p /srv/tacahu/backups

# Cấp quyền cho user hiện tại
sudo chown -R $USER:$USER /srv/tacahu
sudo chmod -R 775 /srv/tacahu
```

---

## 5. Cấu hình Production Secrets (`/srv/tacahu/.env`)

Trong terminal **Ubuntu 20.04**, tạo file `.env`:
```bash
nano /srv/tacahu/.env
```

Dán nội dung cấu hình này vào (điền các thông tin thật của dự án):
```env
DATABASE_URL=postgresql+psycopg://<USER>:<PASSWORD>@<HOST>:5432/<DBNAME>
SECRET_KEY=<EXACT_SECRET_KEY_FROM_RENDER>
COOKIE_SECURE=true
SESSION_MAX_AGE_SECONDS=43200
CORS_ORIGINS=https://tacahu-ops.vercel.app

REDIS_URL=redis://redis:6379/0
CRAWL_INTERVAL_SECONDS=300
STATUS_SYNC_INTERVAL_SECONDS=300

BACKEND_IMAGE=tacahu-backend
APP_VERSION=latest
APP_SOURCE_DIR=./app
DATA_DIR=./data
BACKEND_PORT=8000

# Cloudflare Tunnel
DEPLOY_WITH_TUNNEL=false
CLOUDFLARE_TUNNEL_TOKEN=
```

Lưu file bằng cách bấm `Ctrl + O` ➔ Enter, sau đó `Ctrl + X` để thoát.  
Khóa quyền bảo mật file:
```bash
chmod 600 /srv/tacahu/.env
```

---

## 6. Cấu hình Cloudflare Tunnel

1. Truy cập **Cloudflare Zero Trust Dashboard** ➔ **Networks** ➔ **Tunnels**.
2. Chọn **Create a Tunnel** (chọn Cloudflared connector).
3. Đặt tên tunnel (ví dụ: `tacahu-pc-server`).
4. Sao chép **Tunnel Token** và dán vào biến `CLOUDFLARE_TUNNEL_TOKEN` trong file `/srv/tacahu/.env` (đổi `DEPLOY_WITH_TUNNEL=true`).
5. Trong mục **Public Hostname**:
   * **Subdomain:** `api`
   * **Domain:** `<domain-cua-ban.com>`
   * **Type:** `HTTP`
   * **URL:** `api:8000` *(Lưu ý: dùng `api:8000`, KHÔNG dùng `127.0.0.1:8000`)*.

---

## 7. Kết nối & Deploy từ máy Mac

### Lấy thông tin kết nối:
1. **IP máy Windows 10:** Mở PowerShell gõ `ipconfig` xem IPv4 (ví dụ: `192.168.1.50`).
2. **User Ubuntu:** Gõ lệnh `whoami` trong Ubuntu để biết username.

### Trên máy Mac:
1. Tạo file `.env.deploy`:
   ```bash
   cp .env.deploy.example .env.deploy
   ```
2. Mở file `.env.deploy` và điền IP máy Windows và user Ubuntu:
   ```env
   SERVER_HOST=192.168.1.50
   SERVER_USER=<username_ubuntu>
   SERVER_PORT=22
   SERVER_PATH=/srv/tacahu
   DEPLOY_WITH_TUNNEL=false
   ```
3. Copy SSH public key từ Mac sang Ubuntu PC:
   ```bash
   ssh-copy-id <username_ubuntu>@192.168.1.50
   ```
4. Chạy lệnh deploy:
   ```bash
   ./scripts/deploy-server.sh
   ```

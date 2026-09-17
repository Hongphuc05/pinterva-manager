# 🚀 Kế Hoạch & Hướng Dẫn Triển Khai Tacahu Ops Lên Server VPS (Từ A đến Z)

Tài liệu này hướng dẫn chi tiết toàn bộ quy trình đưa hệ thống **Tacahu Ops** (Backend FastAPI, Celery Workers, Redis, PostgreSQL, Frontend React/Vite) cùng tiện ích **CopyImage Chrome Extension** lên máy chủ **VPS Linux (Ubuntu 22.04 / 24.04 LTS)** để hoạt động hoàn hảo 24/7.

---

## 🏗 1. Tổng Quan Kiến Trúc Hệ Thống Trên VPS

```
                          ┌──────────────────────────────────────────────┐
                          │         MÁY TÍNH CỦA ADMIN / DESIGNER        │
                          │  - Trình duyệt: https://ops.tenmienban.com   │
                          │  - Chrome Extension (CopyImage)             │
                          └──────────────────────┬───────────────────────┘
                                                 │ HTTPS
                                                 ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ SERVER VPS (Ubuntu 22.04 / 24.04 LTS)                                                  │
│                                                                                        │
│   [Cloudflare Tunnel HOẶC Nginx Reverse Proxy (SSL Let's Encrypt)]                    │
│                                      │                                                 │
│                                      ▼ Port 8000                                       │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │ Docker Container: tacahu-ops-api (FastAPI + Vite Frontend Bundle)              │   │
│   └─────────────────┬────────────────────────────────────────────┬─────────────────┘   │
│                     │                                            │                     │
│                     ▼                                            ▼                     │
│   ┌───────────────────────────────────┐        ┌───────────────────────────────────┐   │
│   │ Celery Workers (General & Assign) │        │ PostgreSQL Database               │   │
│   │ + Celery Beat (Lập lịch tự động)  │        │ + Redis Queue                     │   │
│   └───────────────────────────────────┘        └───────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 💻 2. Yêu Cầu Cấu Hình VPS Khuyến Nghị

- **Hệ điều hành**: Ubuntu 22.04 LTS hoặc Ubuntu 24.04 LTS (x86_64).
- **CPU**: 2 vCPU trở lên.
- **RAM**: Tối thiểu 4GB RAM (khuyến nghị 4GB - 8GB để chạy mượt Chromium Playwright và Celery workers).
- **Ổ cứng**: 25GB SSD trở lên.
- **Tên miền (Domain)**: 1 tên miền hoặc subdomain (ví dụ: `ops.yourcompany.com`).

---

## 📋 3. Chi Tiết Từng Bước Triển Khai (Step-by-Step)

### BƯỚC 1: Chuẩn Bị & Cài Đặt Môi Trường Trên VPS

Đăng nhập vào VPS qua SSH:
```bash
ssh root@<IP_VPS>
```

Cập nhật hệ thống và cài đặt các công cụ cơ bản:
```bash
apt-get update && apt-get upgrade -y
apt-get install -y curl git ufw htop ca-certificates gnupg lsb-release
```

Cài đặt **Docker** và **Docker Compose Plugin**:
```bash
# Cài đặt Docker Official Repo
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Bật Docker khởi động cùng hệ thống
systemctl enable docker
systemctl start docker

# Kiểm tra phiên bản Docker & Compose
docker --version
docker compose version
```

---

### BƯỚC 2: Tải Mã Nguồn Lên VPS

Tạo thư mục làm việc trên VPS:
```bash
mkdir -p /srv/tacahu
cd /srv/tacahu
```

Clone mã nguồn dự án từ Git (hoặc dùng rsync/scp):
```bash
git clone <URL_REPO_GIT_CUA_BAN> .
```

---

### BƯỚC 3: Thiết Lập Biến Môi Trường (`.env`)

Tạo file `.env` trên VPS từ file mẫu:
```bash
cp .env.example .env
nano .env
```

Điền các thông số sản xuất chính xác:
```ini
# --- CẤU HÌNH CƠ SỞ DỮ LIỆU & QUEUE ---
DATABASE_URL=postgresql+psycopg://tacahu_user:MatKhauManh123@db:5432/tacahu_ops
REDIS_URL=redis://redis:6379/0

# --- BẢO MẬT & SESSION ---
SECRET_KEY=tao_chuoi_ngau_nhien_dai_it_nhat_32_ky_tu_tai_day
COOKIE_SECURE=true
CORS_ORIGINS=https://ops.yourcompany.com,chrome-extension://*

# --- TÊN MIỀN & PORT ---
APP_BASE_URL=https://ops.yourcompany.com
BACKEND_PORT=8000

# --- THƯ MỤC LƯU ASSETS ---
DATA_DIR=/srv/tacahu/data
```

*(Nhấn `Ctrl + O` $\rightarrow$ Enter để lưu, `Ctrl + X` để thoát nano).*

Tạo thư mục chứa dữ liệu:
```bash
mkdir -p /srv/tacahu/data/crawled_assets
mkdir -p /srv/tacahu/data/order_assets
mkdir -p /srv/tacahu/data/platform_data
mkdir -p /srv/tacahu/data/playwright_evidence
mkdir -p /srv/tacahu/data/chrome_profiles
mkdir -p /srv/tacahu/data/redis
mkdir -p /srv/tacahu/data/postgres
```

---

### BƯỚC 4: Khởi Chạy Database & Build Ứng Dụng Bằng Docker

1. **Khởi chạy Database & Redis trước**:
```bash
docker compose -f compose.local.yaml up -d db redis
```

2. **Chạy Migration Database (Alembic)**:
```bash
docker compose -f compose.local.yaml run --rm migrate
```

3. **Build & Khởi chạy toàn bộ hệ thống**:
```bash
docker compose -f compose.local.yaml up --build -d
```

4. **Kiểm tra trạng thái các container**:
```bash
docker compose -f compose.local.yaml ps
```
*Tất cả các container `api`, `db`, `redis`, `celery-general`, `celery-assignment`, `celery-beat` đều phải hiển thị `Up` hoặc `Healthy`.*

---

### BƯỚC 5: Thiết Lập Domain & HTTPS SSL

Bạn có thể chọn 1 trong 2 cách sau:

#### ⭐ Cách 1 (Khuyến nghị - Nhanh & Bảo mật nhất): Dùng Cloudflare Tunnel
- Không cần mở port VPS, Cloudflare tự lo SSL và chống DDoS.
1. Trên Cloudflare Dashboard $\rightarrow$ **Zero Trust** $\rightarrow$ **Networks** $\rightarrow$ **Tunnels** $\rightarrow$ Tạo 1 Tunnel mới.
2. Sao chép Token của Tunnel.
3. Trong file `.env` trên VPS, thêm:
   ```ini
   CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoi...dien_token_tai_day...
   ```
4. Trên Cloudflare Tunnel cấu hình Public Hostname:
   - Subdomain: `ops` (hoặc tên miền bạn muốn)
   - Service Type: `HTTP`
   - URL: `api:8000` (hoặc `localhost:8000`)
5. Chạy Cloudflared:
   ```bash
   docker compose -f compose.yaml --profile tunnel up -d cloudflared
   ```

#### Cách 2: Dùng Nginx Reverse Proxy + Let's Encrypt SSL
```bash
apt-get install -y nginx certbot python3-certbot-nginx

# Tạo file cấu hình Nginx
nano /etc/nginx/sites-available/tacahu-ops
```
Nội dung:
```nginx
server {
    server_name ops.yourcompany.com;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
Kích hoạt và cài SSL:
```bash
ln -s /etc/nginx/sites-available/tacahu-ops /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d ops.yourcompany.com
```

---

### BƯỚC 6: Tạo Tài Khoản Admin Ban Đầu

Chạy lệnh tạo user Admin quản trị hệ thống:
```bash
docker compose -f compose.local.yaml exec api python -c "
from app.adapters.db.models import User
from app.application.auth import hash_password
from app.adapters.db.session import get_db_context

with get_db_context() as db:
    existing = db.query(User).filter(User.username == 'admin').first()
    if not existing:
        admin = User(
            username='admin',
            full_name='System Admin',
            role='admin',
            password_hash=hash_password('MatKhauAdminCuaBan123!'),
            password_ciphertext='MatKhauAdminCuaBan123!'
        )
        db.add(admin)
        db.commit()
        print('✓ Tạo tài khoản Admin thành công!')
    else:
        print('Tài khoản admin đã tồn tại.')
"
```

---

### BƯỚC 7: Cài Đặt & Cấu Hình Extension Cho Máy Tính Của Admin

1. **Tải thư mục `CopyImage` về máy tính Admin**:
   - Thư mục `CopyImage/` nằm trong bộ mã nguồn.
2. **Cài vào Chrome**:
   - Mở Chrome $\rightarrow$ `chrome://extensions/`
   - Bật **Developer mode** $\rightarrow$ Bấm **Load unpacked** $\rightarrow$ Chọn thư mục `CopyImage`.
3. **Cấu hình trỏ về VPS**:
   - Chuột phải vào biểu tượng Extension $\rightarrow$ Chọn **Tùy chọn (Options)**.
   - Tại ô **Tacahu Ops API URL**: Điền `https://ops.yourcompany.com` (domain VPS vừa tạo).
   - Bấm **Kiểm tra** $\rightarrow$ Hiện thông báo màu xanh `✓ Kết nối thành công tới Tacahu Ops!`.
   - Tích chọn: `Tự động quét bộ ảnh ngay khi mở trang Design Job` $\rightarrow$ Bấm **Lưu Cấu Hình**.

---

## 🛠 4. Các Lệnh Vận Hành & Bảo Trì Hàng Ngày Trên VPS

| Thao tác | Câu lệnh trên VPS |
|---|---|
| **Xem Logs trực tiếp** | `docker compose -f compose.local.yaml logs -f api` |
| **Xem Logs Celery** | `docker compose -f compose.local.yaml logs -f celery-general celery-assignment` |
| **Khởi động lại stack** | `docker compose -f compose.local.yaml restart` |
| **Cập nhật code mới** | `git pull && docker compose -f compose.local.yaml up --build -d` |
| **Sao lưu Database** | `bash scripts/db_backup.sh` *(tạo file .dump an toàn)* |
| **Khôi phục Database** | `bash scripts/db_restore.sh /duong_dan_file/backup.dump` |

---

## ✅ 5. Checklist Kiểm Tra Hoàn Hảo Sau Deploy

- [x] Truy cập `https://ops.yourcompany.com` hiển thị giao diện đăng nhập mượt mà.
- [x] Đăng nhập tài khoản Admin thành công.
- [x] Vào tab **"Mở Printerval"** bấm nút mở trang Design Job hoạt động chính xác.
- [x] Extension trên máy Admin báo **Kết nối thành công (Test Connection OK)** tới VPS.
- [x] Bấm nút **`⚡ Quét & Đồng Bộ Bộ Ảnh`** trên Printerval $\rightarrow$ Ảnh tự động lưu về database VPS.
- [x] F5 lại trang Tacahu Ops $\rightarrow$ Các đơn hàng hiển thị đủ bộ ảnh sắc nét, Designer làm việc bình thường.

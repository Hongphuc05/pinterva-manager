# RUNME — Hướng Dẫn Khởi Chạy Pinterval Ops Dashboard (Nhánh `main`)

Tài liệu hướng dẫn khởi chạy toàn bộ hệ thống **Pinterval Ops Dashboard** trên nhánh `main`, bao gồm Backend (FastAPI + SQLAlchemy + Postgres), Frontend (React + Vite + TailwindCSS), và Hệ thống Crawl Đơn hàng API-First từ Printerval.

---

## 1. Cài Đặt Ban Đầu (Setup)

### Bước 1: Clone & Chuyển sang nhánh `main`
```bash
cd /Users/hongphuc/Documents/01_congViec/pinterval
git checkout main
```

### Bước 2: Tạo môi trường Virtualenv & Cài đặt thư viện Python
```bash
# Tạo .env từ file mẫu nếu chưa có
cp -n .env.example .env

# Tạo Virtual Environment & Activate
python3.12 -m venv .venv
source .venv/bin/activate

# Cài đặt toàn bộ dependencies
pip install -e ".[dev]"
```

### Bước 3: Khởi chạy Database (Postgres 16 + Redis) & Migration
```bash
# Khởi chạy Docker Postgres & Redis
docker compose up -d db redis

# Chạy Alembic Migration để cập nhật bảng mới nhất (Bao gồm Multi-Platform & Templates)
alembic upgrade head
```

### Bước 4: Tạo Tài Khoản Quản Trị Viên (Admin)
Chạy script tạo sẵn tài khoản Admin và Designer thử nghiệm:
```bash
./.venv/bin/python -c "
from app.adapters.db.session import SessionLocal
from app.adapters.db.models import User
from app.application.auth import hash_password

db = SessionLocal()
if not db.query(User).filter_by(username='admin').first():
    db.add(User(username='admin', full_name='Admin Test', role='admin', password_hash=hash_password('admin123')))
if not db.query(User).filter_by(username='designer1').first():
    db.add(User(username='designer1', full_name='Designer Test', role='designer', password_hash=hash_password('designer123')))
db.commit()
print('Đã tạo tài khoản: admin/admin123 (Admin), designer1/designer123 (Designer)')
"
```

---

## 2. Khởi Chạy Web Dashboard

Hệ thống hoạt động ở **4 tiến trình độc lập**: Backend API, Frontend Dev Server, và
**Celery Worker + Beat** (bắt buộc cho job nền tự động — quét đơn định kỳ và đồng bộ
trạng thái Printerval; nút "Đồng bộ ngay" cũng cần Worker đang chạy để xử lý, nếu
không sẽ chỉ nằm im trong hàng đợi Redis không ai xử lý).

### Tiến trình 1: Khởi chạy Backend (FastAPI Server)
```bash
cd /Users/hongphuc/Documents/01_congViec/pinterval
source .venv/bin/activate
uvicorn app.api.main:app --reload --port 8000
```
*(Backend JSON API lắng nghe tại `http://localhost:8000`, API Docs Swagger tại `http://localhost:8000/docs`)*

### Tiến trình 2: Khởi chạy Frontend (Vite Dev Server)
Mở một cửa sổ Terminal mới:
```bash
cd /Users/hongphuc/Documents/01_congViec/pinterval/frontend
npm install
npm run dev
```
*(Frontend Dev Server chạy tại `http://localhost:5173` — tự động proxy mọi API `/api` sang cổng 8000)*

### Tiến trình 3 + 4: Khởi chạy Celery Worker & Beat (job nền)
Mở 2 cửa sổ Terminal mới (mỗi tiến trình 1 cửa sổ riêng, hoặc `&` chạy nền):
```bash
cd /Users/hongphuc/Documents/01_congViec/pinterval
source .venv/bin/activate
celery -A app.workers.celery_app worker --loglevel=info
```
```bash
cd /Users/hongphuc/Documents/01_congViec/pinterval
source .venv/bin/activate
celery -A app.workers.celery_app beat --loglevel=info
```
*(Worker xử lý task thật; Beat bắn lịch định kỳ — mặc định mỗi 300s cho cả quét đơn mới
lẫn đồng bộ trạng thái Printerval, chỉnh qua `CRAWL_INTERVAL_SECONDS` /
`STATUS_SYNC_INTERVAL_SECONDS` trong `.env`. Cần Redis đang chạy —
`docker compose up -d redis` ở Bước 3.)*

---

## 3. Hướng Dẫn Sử Dụng & Thao Tác Web Dashboard

1. Mở trình duyệt truy cập: **`http://localhost:5173`**
2. Đăng nhập với tài khoản:
   - **Tài khoản:** `admin`
   - **Mật khẩu:** `admin123`

### Chức Năng Chính:
- **Quản Lý Workspace Acc Mẹ Printerval:** 
  - Nhấp vào nút **`Acc Mẹ Printerval: ...`** trên góc phải Topbar để xem danh sách hoặc đăng nhập tài khoản mẹ Printerval mới.
  - Khi chuyển đổi Workspace Acc Mẹ, toàn bộ dữ liệu đơn hàng, phân công và tiến độ được cô lập và tải riêng theo từng tài khoản mẹ.
- **Quét Đơn Printerval (API HTTP Crawl):**
  - Nhấp nút **`Quét Đơn Printerval`** ở góc trên bên phải.
  - Hệ thống sử dụng HTTP API tự động quét và nhập hàng chục đơn hàng từ Printerval về CSDL chỉ trong vài giây mà không cần mở trình duyệt Chromium ngầm.
- **Phân Bổ Kéo-Thả (Allocation Board):**
  - Giao diện trực quan hỗ trợ phân công đơn hàng cho Designer.
- **Bảng Tiến Độ Kanban:**
  - Theo dõi trạng thái quy trình xử lý đơn hàng từ DISCOVERED, ASSIGNED, CLAIMED_IMPORTED đến SUBMITTED, PASSED_QC.
- **Trạng Thái Đơn (chỉ xem):**
  - Mirror một chiều trạng thái thật trên Printerval (Waiting/Doing/Review/Fix/Confirm/Done), tự đồng bộ theo lịch + nút "Đồng bộ ngay". Không có nút đổi trạng thái ngược lại Printerval từ tab này (xem claude.md §10).
- **Quản Lý Tài Khoản (User Management):**
  - Thêm, sửa, cấp quyền Admin / Designer cho nhân sự trong team.

---

## 4. Chạy Kiểm Thử Tự Động (Pytest)

Để đảm bảo toàn bộ hệ thống hoạt động chính xác (190 test cases):

```bash
cd /Users/hongphuc/Documents/01_congViec/pinterval
createdb -h localhost -U postgres pinterval_test 2>/dev/null || true
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pinterval_test ./.venv/bin/pytest
```

---

## 5. Cấu Trúc Nhánh & Ghi Chú Phát Triển

- **Nhánh hiện tại:** `main` (Đã được merge đầy đủ toàn bộ tính năng Phase 1-4, Multi-Tenant Workspace & HTTP API Crawl).
- **Quy tắc Commit:** Mọi thay đổi mới nên được kiểm thử qua `pytest` trước khi commit trực tiếp lên `main`.

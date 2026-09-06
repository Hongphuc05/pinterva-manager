# RUNME — Chạy & test Phase 1 (nền tảng backend)

> **Quan trọng:** Phase 1 **chưa có giao diện web** (chưa có trang HTML nào để bấm
> chuột qua trình duyệt). Đây mới là phần nền: Postgres schema, state machine,
> idempotency ledger, và 1 API JSON thuần cho auth (login/logout/me) + 2 route ví dụ
> phân quyền (admin/designer). Trang dashboard thật (nhìn danh sách đơn, duyệt, nhận
> task...) là **Phase 4 trở đi** theo `roadmap.md`, chưa code.
>
> Cái mày test được ngay bây giờ: gọi API bằng trình duyệt qua Swagger UI tự sinh
> (`/docs`), hoặc `curl`/Postman. Xem phần 4 bên dưới.

## 1. Yêu cầu máy

- Docker + Docker Compose (đã cài — repo dùng để chạy Postgres 16 local).
- Python 3.12. Máy mày mặc định `python3` là 3.9.6 (quá cũ) — nếu chưa có 3.12:
  ```bash
  brew install python@3.12
  ```
  Sau đó dùng `python3.12` thay vì `python3` ở các lệnh dưới.
- `pg_dump`/`pg_restore`/`createdb`/`dropdb`/`psql` (chỉ cần nếu muốn test script
  backup/restore ở phần 6) — cài qua `brew install postgresql@16`.

## 2. Cài đặt lần đầu

```bash
cd /Users/hongphuc/Documents/01_congViec/pinterval    # (hoặc nhánh/worktree đang có code)

cp .env.example .env          # chỉnh nếu muốn, mặc định đã chạy được luôn

python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

docker compose up -d db       # chạy Postgres 16 trong Docker, cổng 5432
alembic upgrade head          # tạo toàn bộ 13 bảng theo schema mới nhất
```

## 3. Tạo user đầu tiên để đăng nhập

Chưa có API "đăng ký" (đó là quyết định V1 — admin tạo tài khoản tay, không tự
đăng ký). Tạo 1 admin bằng script nhỏ này (dán nguyên đoạn vào terminal, đã activate
venv ở bước 2):

```bash
python -c "
from app.adapters.db.session import SessionLocal
from app.adapters.db.models import User
from app.application.auth import hash_password

db = SessionLocal()
db.add(User(
    username='admin',
    full_name='Admin Test',
    role='admin',
    password_hash=hash_password('admin123'),
))
db.commit()
print('Đã tạo user: admin / admin123')
"
```

Muốn có thêm user role `designer` để test phân quyền, đổi `username`, `role='designer'`
rồi chạy lại.

## 4. Chạy server và test API

```bash
uvicorn app.api.main:app --reload
```

Mở trình duyệt: **http://127.0.0.1:8000/docs** — đây là Swagger UI tự sinh của
FastAPI, có thể bấm "Try it out" trực tiếp trên trình duyệt, không cần Postman.

Các route hiện có:

| Route | Method | Mô tả |
|---|---|---|
| `/api/health` | GET | Kiểm tra server sống |
| `/api/login` | POST | Đăng nhập, trả về cookie session (body: `{"username":..., "password":...}`) |
| `/api/logout` | POST | Xoá cookie session |
| `/api/me` | GET | Thông tin user đang đăng nhập (cần đã login) |
| `/api/admin/ping` | GET | Route ví dụ, chỉ role `admin` gọi được (403 nếu sai role) |
| `/api/designer/ping` | GET | Route ví dụ, chỉ role `designer` gọi được |

Test bằng `curl` (giữ cookie qua `-c`/`-b`):

```bash
curl -c cookies.txt -X POST http://127.0.0.1:8000/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

curl -b cookies.txt http://127.0.0.1:8000/api/me
curl -b cookies.txt http://127.0.0.1:8000/api/admin/ping     # -> 200
curl -b cookies.txt http://127.0.0.1:8000/api/designer/ping  # -> 403 (vì admin không phải designer)
```

Qua Swagger UI (`/docs`): gọi `POST /api/login` trước (Swagger tự giữ cookie cho các
lần gọi sau trong cùng tab trình duyệt), rồi thử `GET /api/me`, `GET /api/admin/ping`.

## 5. Chạy test tự động

```bash
docker compose up -d db
createdb -h localhost -U postgres pinterval_test 2>/dev/null || true
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pinterval_test \
  pytest -v
```

Hiện tại: 34 test, tất cả pass. Có thể chạy `ruff check .` để lint — phải sạch (exit 0).

## 6. (Tuỳ chọn) Test backup/restore

```bash
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pinterval \
  bash scripts/db_backup.sh /tmp/backup.dump
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pinterval \
  bash scripts/db_restore.sh /tmp/backup.dump
```

## 7. Những thứ chưa có (đừng ngạc nhiên khi thấy thiếu)

- Không có trang web nào — chỉ API JSON.
- Không có API tạo user qua HTTP (chỉ tạo tay qua script ở mục 3, hoặc thao tác DB
  trực tiếp).
- Chưa có crawl Printerval, chưa có chia đơn, chưa có QC — đó là Phase 2 trở đi.
- `docker compose down` sẽ tắt Postgres nhưng giữ data (volume `pinterval_db_data`);
  `docker compose down -v` mới xoá sạch data.

## 8. Nếu có lỗi

- `ModuleNotFoundError`: quên `source .venv/bin/activate` hoặc quên `pip install -e ".[dev]"`.
- Lỗi kết nối Postgres: `docker compose ps` xem container `db` đã `Up` chưa; `docker compose up -d db` lại nếu cần.
- `alembic upgrade head` báo lỗi: kiểm tra `.env`/`DATABASE_URL` trỏ đúng `localhost:5432`.

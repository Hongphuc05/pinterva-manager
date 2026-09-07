# RUNME — Chạy toàn bộ Pinterval Ops (Phase 1-4)

Đã có: Postgres schema + state machine (P1), Printerval/Google adapter (P2), crawl job
tự động (P3), web dashboard login + danh sách/chi tiết đơn (P4). **Chưa có**: phân bổ
đơn, QC, submit-to-site (Phase 5 trở đi) — nên web hiện chỉ hiển thị, chưa có nút thao
tác.

## 1. Cài đặt lần đầu

```bash
cd /Users/hongphuc/Documents/01_congViec/pinterval

cp .env.example .env
# Sửa COOKIE_SECURE=true -> false trong .env (test local http, không có https)

python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chrome        # chỉ cần nếu sẽ chạy crawl job thật (mục 4)

docker compose up -d db redis    # Postgres 16 + Redis
alembic upgrade head             # tạo toàn bộ bảng
```

Tạo user để đăng nhập (chưa có API tự đăng ký — tạo tay):

```bash
python -c "
from app.adapters.db.session import SessionLocal
from app.adapters.db.models import User
from app.application.auth import hash_password

db = SessionLocal()
db.add(User(username='admin', full_name='Admin Test', role='admin',
            password_hash=hash_password('admin123')))
db.add(User(username='designer1', full_name='Designer Test', role='designer',
            password_hash=hash_password('designer123')))
db.commit()
print('Đã tạo: admin/admin123 (role admin), designer1/designer123 (role designer)')
"
```

## 2. Chạy web dashboard

```bash
uvicorn app.api.main:app --reload
```

Mở **http://127.0.0.1:8000/login** — đăng nhập `admin`/`admin123`. Sẽ vào `/orders`
(hiện rỗng nếu chưa chạy crawl job ở mục 4 — DB chưa có đơn nào là bình thường).

Trang có: danh sách đơn lọc theo status/batch (HTMX, không reload trang), nút
**Refresh** (chỉ admin thấy) chạy crawl thật ngay từ trình duyệt, link **"Đăng nhập
Printerval"** trên thanh nav (chỉ admin) mở Chrome thật để đăng nhập tay — xem mục 4 —
và trang chi tiết đơn kèm lịch sử chuyển trạng thái. `admin` thấy mọi đơn; `designer`
chỉ thấy đơn được giao (luôn rỗng cho tới khi Phase 5 xong).

Sau khi bấm Refresh, thông báo phân biệt rõ 3 trường hợp: thành công (kèm số đơn mới/
nhập/lỗi), lỗi tìm đơn (site đổi giao diện/bộ lọc sai — xem `dead_letters` để biết chi
tiết), hoặc lỗi mở phiên trình duyệt (thường do Chrome profile chưa/hết đăng nhập).

API JSON thuần (Swagger) vẫn còn ở **http://127.0.0.1:8000/docs** nếu cần test qua
Postman/curl thay vì trình duyệt.

## 3. (Tuỳ chọn) Nạp dữ liệu mẫu để xem giao diện ngay, không cần crawl thật

```bash
python -c "
from app.adapters.db.session import SessionLocal
from app.adapters.db.models import Order, WorkflowEvent
from app.domain.models import OrderState

db = SessionLocal()
o = Order(external_order_id='DJ0000001', state=OrderState.CLAIMED_IMPORTED.value)
db.add(o); db.commit()
db.add(WorkflowEvent(order_id=o.id, from_state='DISCOVERED', to_state='CLAIMED_IMPORTED'))
db.commit()
print('Đã tạo đơn mẫu DJ0000001')
"
```

## 4. Chạy crawl job thật (đụng site Printerval thật — cẩn thận)

Cần Chrome profile (`chrome-profile/`) đã login **đúng tài khoản công ty/admin** —
**không phải tài khoản cá nhân của 1 designer** (site giới hạn kết quả tìm kiếm theo
`team_outsource` của tài khoản đang login; tài khoản cá nhân không thấy đơn `Waiting`
chưa ai claim). Đăng nhập/đổi tài khoản qua chính web dashboard: vào **"Đăng nhập
Printerval"** trên thanh nav (chỉ admin thấy) → bấm "Mở Chrome để đăng nhập" → cửa sổ
Chrome thật mở ra, đăng nhập/đổi tài khoản trên đó bình thường → quay lại trang web,
bấm "Done" để đóng cửa sổ.

Sau khi đã login đúng tài khoản, có 2 cách chạy crawl:

**a) Bấm nút Refresh trên web** (`/orders`, chỉ admin thấy nút) — chạy ngay, đứng chờ
kết quả (vài chục giây tới vài phút tùy số đơn), không cần Celery. Lưu ý: đừng bấm
đúng lúc Celery Beat (cách b) đang chạy nền cùng lúc — 2 phiên Chrome cùng lúc trên
cùng 1 profile có thể xung đột (giới hạn "1 session/site", chưa xử lý khoá).

**b) Chạy định kỳ nền qua Celery** (không cần mở trình duyệt):

```bash
celery -A app.workers.celery_app worker --beat --loglevel=info
```

Job `crawl_and_claim` tự chạy mỗi `CRAWL_INTERVAL_SECONDS` (mặc định 300s = 5 phút).
Gọi tay ngay lập tức thay vì chờ:

```bash
python -c "from app.workers.crawl_tasks import crawl_and_claim; crawl_and_claim()"
```

## 5. Chạy test tự động

```bash
createdb -h localhost -U postgres pinterval_test 2>/dev/null || true
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pinterval_test pytest -v
ruff check .   # phải sạch (exit 0)
```

126 test, không đụng site/Redis/Celery/Google thật (trừ 2 test Google bị deselect mặc
định — chạy riêng bằng `pytest -m integration` nếu có
`credentials/google-service-account.json`).

## 6. Nếu có lỗi

- `ModuleNotFoundError`: quên `source .venv/bin/activate` hoặc `pip install -e ".[dev]"`.
- Lỗi kết nối Postgres/Redis: `docker compose ps` xem `db`/`redis` đã `Up` chưa.
- Login trên web không giữ session: kiểm tra `.env` có `COOKIE_SECURE=false` (test qua
  http, không phải https).
- `docker compose down` giữ data (volume); `docker compose down -v` mới xoá sạch.

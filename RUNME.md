# RUNME — chạy Tacahu Ops local bằng Docker

Hướng dẫn này là cách chạy local chuẩn. Toàn bộ runtime nằm trong Docker; không
cần chạy `npm run dev`, Uvicorn hay Celery thủ công.

> Chỉ dùng các lệnh dưới đây từ thư mục chính
> `/Users/hongphuc/Documents/01_congViec/pinterval`.

## 1. Điều kiện ban đầu

- Docker Desktop đang mở và trạng thái là **Running**.
- Đã có image nền `pinterval-ops-backend:dev` trên Mac. Image này chứa Python,
  Playwright và Chromium; `compose.local.yaml` chỉ ghép source hiện tại cùng React
  bundle lên trên image đó để build nhanh.

Kiểm tra Docker:

```bash
docker info >/dev/null && echo 'Docker đang sẵn sàng'
```

## 2. Khởi động toàn bộ hệ thống

Lần đầu, hoặc sau khi sửa source code:

```bash
cd /Users/hongphuc/Documents/01_congViec/pinterval
docker compose -f compose.local.yaml up --build -d
```

Lần sau chỉ cần bật lại các container đã có:

```bash
cd /Users/hongphuc/Documents/01_congViec/pinterval
docker compose -f compose.local.yaml up -d
```

Kiểm tra tất cả service:

```bash
docker compose -f compose.local.yaml ps
```

`api` và `db` phải hiện `healthy`. Service `migrate` hiện `Exited (0)` là đúng,
vì nó chỉ chạy Alembic migration một lần trước khi API và worker được khởi động.

## 3. Các địa chỉ local

| Thành phần | Địa chỉ |
| --- | --- |
| Web dashboard | http://localhost:8000 |
| Swagger API | http://localhost:8000/docs |
| Health check | http://localhost:8000/api/health |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |

Mở web tại `http://localhost:8000`. React SPA được build sẵn trong image và FastAPI
serve cùng một origin, nên không có Vite dev server hay proxy riêng.

Lần login đầu tiên trên database local sẽ seed tài khoản:

```text
username: admin
password: admin123
```

## 4. Docker đang chạy những gì

`compose.local.yaml` tự chạy:

- React SPA đã build trong image local
- FastAPI API
- PostgreSQL
- Redis
- Alembic migration
- Celery general worker: crawl, Sync Job và công việc nền chung
- Celery assignment worker: thao tác phân công/đổi trạng thái Printerval
- Celery Beat: lập lịch các tác vụ định kỳ

Không chạy thêm Celery/Uvicorn native trên Mac. Chạy song song native worker với
Docker worker có thể làm một job bị xử lý hai lần.

## 5. Thao tác thường dùng

Xem log API:

```bash
docker compose -f compose.local.yaml logs -f --tail=100 api
```

Xem log worker đồng bộ/crawl:

```bash
docker compose -f compose.local.yaml logs -f --tail=100 celery-general
```

Xem log worker phân công:

```bash
docker compose -f compose.local.yaml logs -f --tail=100 celery-assignment
```

Dừng web mà vẫn giữ database, Redis, browser profile và cache:

```bash
docker compose -f compose.local.yaml stop
```

Bật lại sau khi đã dừng:

```bash
docker compose -f compose.local.yaml start
```

Sau khi pull code hoặc sửa code, build và recreate các container:

```bash
docker compose -f compose.local.yaml up --build -d
```

Không dùng lệnh sau trừ khi chủ động muốn xóa sạch database và toàn bộ runtime data
local:

```bash
docker compose -f compose.local.yaml down -v
```

`docker compose ... down` không kèm `-v` chỉ xóa container/network, vẫn giữ named
volume chứa PostgreSQL, Redis, source/gallery cache và browser profile.

## 6. Database local và production

PostgreSQL Docker local là database mới, độc lập với database production và PC server
cũ. Không có dữ liệu đơn hàng production trong đó. Đây là chủ ý để test/crawl local
không ảnh hưởng vận hành thật.

## 7. Chạy test

Test dùng database riêng `pinterval_test`, không dùng database web local `pinterval`:

```bash
cd /Users/hongphuc/Documents/01_congViec/pinterval
docker compose -f compose.local.yaml exec -T db createdb -U postgres pinterval_test || true
source .venv/bin/activate
PYTHONPATH=. pytest -q
```

Kết quả kiểm chứng gần nhất: **249 passed, 2 deselected**. Frontend production build,
Python compile, Ruff và Docker Compose validation đều pass.

## 8. Production và local là hai cấu hình khác nhau

- `compose.local.yaml`: dùng trên Mac để chạy trọn hệ thống bằng một lệnh.
- `compose.yaml`: backend production/self-hosted; frontend production có thể vẫn chạy
  trên Vercel.

Không dùng `compose.local.yaml` để deploy production. Xem
[docs/SELF_HOSTED_PRODUCTION.md](docs/SELF_HOSTED_PRODUCTION.md) khi triển khai server.

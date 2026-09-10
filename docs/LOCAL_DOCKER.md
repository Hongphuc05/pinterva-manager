# Chạy toàn bộ Tacahu Ops bằng Docker trên Mac

File [compose.local.yaml](../compose.local.yaml) là môi trường local độc lập. Nó
chạy PostgreSQL, Redis, migration, API, React SPA, hai Celery worker và Celery Beat.
Không dùng file này cho production; production tiếp tục dùng `compose.yaml` và Vercel.

## Khởi động

```bash
cd /Users/hongphuc/Documents/01_congViec/pinterval-phase1
docker compose -f compose.local.yaml up --build -d
docker compose -f compose.local.yaml ps
```

Lệnh đầu tự build image khi code thay đổi và migration trước khi API/worker được
khởi động. Mở `http://localhost:8000` khi service `api` là `healthy`.

Các service không cần mở Terminal riêng. Muốn xem log:

```bash
docker compose -f compose.local.yaml logs -f --tail=100 api
docker compose -f compose.local.yaml logs -f --tail=100 celery-general
```

## Dừng và chạy lại

```bash
docker compose -f compose.local.yaml stop
docker compose -f compose.local.yaml start
```

Sau khi sửa backend/frontend, build lại:

```bash
docker compose -f compose.local.yaml up --build -d
```

Không dùng `down -v` trừ khi chủ động muốn xóa toàn bộ database local, Redis,
gallery/source cache và browser profile local. `docker compose ... down` bình thường
chỉ dừng/xóa container, giữ named volumes.

## Cổng local

| Service | Địa chỉ |
| --- | --- |
| Web + API + Swagger | `http://localhost:8000`, `http://localhost:8000/docs` |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |

Các cổng có thể đổi mà không sửa file, ví dụ:

```bash
LOCAL_WEB_PORT=8080 LOCAL_POSTGRES_PORT=5433 LOCAL_REDIS_PORT=6380 \
  docker compose -f compose.local.yaml up --build -d
```

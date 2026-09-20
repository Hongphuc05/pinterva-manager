# Tacahu Ops Dashboard

> Tài liệu nghiệp vụ và vận hành hiện hành: [Tacahu Ops Core](docs/tacahu-ops-core/README.md).
> Plan/spec trong `docs/superpowers/` là lịch sử, không phải source of truth.

Web dashboard nội bộ điều phối order design trên Printerval/platform.

## Chạy local

### Một lệnh Docker đầy đủ

Để chạy web, API, PostgreSQL, Redis, migration và toàn bộ worker bằng Docker,
xem [docs/LOCAL_DOCKER.md](docs/LOCAL_DOCKER.md). Sau khi khởi động, mở
`http://localhost:8000`.

### Native development

1. `cp .env.example .env` rồi chỉnh nếu cần.
2. `docker compose up -d db` — chạy Postgres 16 local.
3. `pip install -e ".[dev]"`
4. `alembic upgrade head` — tạo schema.
5. `uvicorn app.api.main:app --reload` — chạy API.

## Test

```bash
docker compose up -d db
createdb -h localhost -U postgres pinterval_test 2>/dev/null || true
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pinterval_test \
  pytest -v
```

## Lint

```bash
ruff check .
```

## Production trên VPS

Production tự host cả React SPA lẫn API tại cùng domain, không phụ thuộc Vercel.
`compose.production.yaml` chạy PostgreSQL, Redis, FastAPI, Celery workers, Celery Beat
và Cloudflare Tunnel. Xem [runbook hiện hành](docs/tacahu-ops-core/operations.md) trước
khi triển khai; không dùng cấu hình này thay cho `compose.local.yaml` trên Mac.

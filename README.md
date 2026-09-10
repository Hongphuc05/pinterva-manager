# Tacahu Ops Dashboard

Web dashboard nội bộ điều phối order 2D outsource — xem `claude.md` và
`docs/superpowers/specs/2026-09-06-web-dashboard-design.md` để hiểu kiến trúc đầy đủ.

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

## Production-like Docker runtime

The frontend remains on Vercel. Backend production uses a prebuilt GHCR image through
`compose.yaml`; it never builds source code on the server. See
[docs/SERVER_HANDOFF.md](docs/SERVER_HANDOFF.md) for the new-PC checklist and
[docs/SELF_HOSTED_PRODUCTION.md](docs/SELF_HOSTED_PRODUCTION.md) for local validation.

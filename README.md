# Pinterval Ops Dashboard

Web dashboard nội bộ điều phối order 2D outsource — xem `claude.md` và
`docs/superpowers/specs/2026-09-06-web-dashboard-design.md` để hiểu kiến trúc đầy đủ.

## Chạy local

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

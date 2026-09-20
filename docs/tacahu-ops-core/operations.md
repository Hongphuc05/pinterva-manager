# Vận hành và phát triển

## Local

```bash
docker compose -f compose.local.yaml up -d --build
# hoặc native: docker compose up -d db; pip install -e ".[dev]"; .venv/bin/alembic upgrade head
```

SPA/API local thường ở `http://localhost:8000`. Xem cấu hình compose thực tế trước khi
đổi environment; local và production dùng volume/database khác nhau.

## Production

- `compose.production.yaml` là runtime production tách biệt.
- Chạy migration service trước API/worker, sau đó xác minh health, migration head, worker
  queue và Cloudflare Tunnel.
- Backup PostgreSQL và private assets trước deploy/rollback. Không dùng `down -v` lên data
  production.
- Sau mỗi thay đổi compose, kiểm tra tất cả thư mục có file ghi runtime đều được bind-mount.
  `private_work_note_assets` được mount vào `/app/private_work_note_assets` và phải có trong
  backup asset; preflight sẽ chặn deploy nếu thư mục host chưa được tạo.
- Nếu build SPA mới, deploy cả `frontend/dist`; code local đã pass build không đồng nghĩa
  website production đã nhận bundle mới.

## Kiểm tra tối thiểu trước bàn giao

```bash
.venv/bin/alembic heads
.venv/bin/ruff check app tests
.venv/bin/pytest -q tests/test_order_work_notes_api.py
cd frontend && npm test && npm run build
```

Chạy DB-backed pytest tuần tự. Không chạy parallel trên cùng `pinterval_test` vì có thể
deadlock/che lỗi concurrency.

## Monitoring cần xem

- API health, error/latency command và HTTP 409 conflict.
- Celery general/assignment/beat; dead letter và external write evidence.
- status-sync cycle, crawl cycle, private asset volume và database backup.
- Cloudflare tunnel/HTTPS ở production.

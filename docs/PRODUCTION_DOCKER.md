# Chạy Tacahu Ops production bằng Docker

Tài liệu này dành cho VPS. Local Mac tiếp tục dùng [../RUNME.md](../RUNME.md) cùng
`compose.local.yaml`.

## Thành phần

`compose.production.yaml` chạy:

- PostgreSQL 16 và Redis 7 trong Docker private network;
- FastAPI kèm React SPA build sẵn tại cùng origin;
- Celery general worker, Celery assignment worker và chỉ một Celery Beat;
- Alembic migration chạy riêng trong deploy flow;
- Cloudflare Tunnel tùy chọn cho `https://tacahu.fun`.

API chỉ bind `127.0.0.1:8000` trên VPS. PostgreSQL và Redis không publish port.
Cloudflare Tunnel kết nối nội bộ đến `api:8000`.

## File và thư mục cần có trên VPS

```text
/srv/tacahu-ops/
├── .env.production                 # secret, không commit
├── compose.production.yaml
├── Dockerfile.production
├── app/, migrations/, frontend/
└── data/
    ├── postgres/
    ├── redis/
    ├── crawled_assets/
    ├── order_assets/
    ├── platform_data/
    ├── playwright_evidence/
    └── chrome_profiles/
```

Tạo `.env.production` từ `.env.production.example`. `POSTGRES_PASSWORD` và mật khẩu
trong `DATABASE_URL` phải cùng một giá trị; các ký tự đặc biệt trong URL phải URL-encode.
`DATA_DIR` phải là đường dẫn tuyệt đối, ví dụ `/srv/tacahu-ops/data`.

## Kiểm tra trước deploy

Từ root repo trên VPS:

```bash
cp .env.production.example .env.production
# sửa .env.production bằng editor trên VPS
mkdir -p /srv/tacahu-ops/data/{postgres,redis,crawled_assets,order_assets,platform_data,playwright_evidence,chrome_profiles}
./scripts/production-preflight.sh
```

Preflight không build image. Nó kiểm tra Docker/Compose, biến môi trường, HTTPS origin,
dung lượng disk, compose rendering và tracked worktree phải sạch.

## Deploy

Lệnh sau chủ động build Docker rồi chạy migration và service:

```bash
./scripts/deploy-production.sh --build
```

Sau khi Cloudflare Tunnel đã được tạo và hostname `tacahu.fun` đã route đến `http://api:8000`:

```bash
./scripts/deploy-production.sh --build --with-tunnel
```

`--build` là bắt buộc để tránh build/rebuild tình cờ. Không chạy lệnh deploy này cho đến
khi release commit và VPS configuration đã được kiểm tra.

## Kiểm tra sau deploy

```bash
docker compose --env-file .env.production -f compose.production.yaml ps
curl --fail http://127.0.0.1:8000/api/health
docker compose --env-file .env.production -f compose.production.yaml logs --tail=100 api
```

Sau khi Tunnel hoạt động, kiểm tra `https://tacahu.fun/api/health` và đăng nhập từ trình
duyệt.

## Dừng service

```bash
docker compose --env-file .env.production -f compose.production.yaml stop
```

Không dùng `down -v`: lệnh đó xóa database volume. `down` không kèm `-v` chỉ dùng khi
thực sự cần recreate network/container và đã có backup database.

## Google Sheets

Backup Google Sheet chưa được bật trong Phase 1. Phase 3 sẽ thêm task hằng ngày và mount
credential JSON từ ngoài repo. Không đặt JSON service account vào `.env.production`.

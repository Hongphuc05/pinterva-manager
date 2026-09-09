# Chuyển Tacahu Ops sang một Ubuntu PC mới

Frontend vẫn ở `https://tacahu-ops.vercel.app/`. PC chỉ chạy image backend đã build sẵn từ GHCR, Redis, Celery và Cloudflare Tunnel. Nó không cần Python, Node, npm, pip hay build source.

## Chuẩn bị một lần

1. Cài Ubuntu Server, Docker Engine, Docker Compose plugin và Git.
2. Trong BIOS bật **Restore on AC Power Loss = Power On**; dùng Ethernet và UPS nếu có.
3. Tạo Cloudflare Tunnel hostname `api.<domain>` trỏ tới service `http://api:8000`. Lấy tunnel token, không commit token.
4. UFW: chỉ mở SSH theo policy. Không mở 8000, 5432 hoặc 6379. Tunnel là kết nối outbound.
5. Lấy các production secrets từ secret store/Render audit: `DATABASE_URL`, `SECRET_KEY`, credential Google service account nếu đang dùng, và token Tunnel. Không chép secrets vào Git/chat/documentation.

## Cài application

```bash
git clone https://github.com/Hongphuc05/pinterva-manager.git
cd pinterva-manager
cp .env.example .env
```

Sửa `.env`:

- `DATABASE_URL`: managed PostgreSQL production hiện hữu trong Phase A.
- `SECRET_KEY`: giữ secret production hiện tại trong Phase A để session không bị đổi bất ngờ.
- `CORS_ORIGINS=https://tacahu-ops.vercel.app`
- `BACKEND_VERSION=sha-<commit-da-duoc-CI-publish>`
- `DEPLOY_WITH_TUNNEL=true`
- `CLOUDFLARE_TUNNEL_TOKEN=<token>`

Nếu image GHCR private, đăng nhập bằng token chỉ có quyền pull package:

```bash
docker login ghcr.io
```

Deploy:

```bash
./scripts/deploy.sh
./scripts/status.sh
```

`deploy.sh` pull image immutable, chạy Alembic migration, start containers, rồi chờ `GET /api/health`. Nó không build code và không xóa volume.

## Sau mỗi update

Developer merge/push `main`; GitHub Actions chạy test và publish `sha-<commit>` lên GHCR. Trên server:

```bash
git pull
# đổi BACKEND_VERSION trong .env sang sha-<commit> vừa publish
./scripts/deploy.sh
```

Rollback application, không restore database:

```bash
./scripts/rollback.sh sha-<known-good-commit>
```

Chỉ dùng rollback khi migration của release mới vẫn tương thích ngược. Migration phá vỡ tương thích cần một runbook riêng trước khi deploy.

## Vận hành hằng ngày

```bash
./scripts/status.sh
./scripts/logs.sh
./scripts/logs.sh api
./scripts/stop.sh
./scripts/start.sh
```

`stop.sh` chỉ dừng containers. Không dùng `docker compose down -v`: các named volumes giữ Redis AOF, thumbnails/source cache, browser profiles và evidence Printerval.

Docker đặt `restart: unless-stopped`, vì vậy Docker khởi động sau reboot sẽ khôi phục API, Redis, workers, Beat và Tunnel. Kiểm tra điều này bằng một lần reboot có giám sát trước production cutover.

## Handoff Cloudflare

Trong giai đoạn validation, Tunnel chạy Compose trên máy development. Khi đổi sang PC server:

1. Xác minh `./scripts/status.sh` trên PC mới bằng một temporary Tunnel hostname.
2. Dừng service Tunnel trên máy development: `./scripts/stop.sh cloudflared`.
3. Chạy `./scripts/deploy.sh` trên PC mới với token/hostname đã cấu hình.
4. Kiểm tra `https://api.<domain>/api/health`, login từ Vercel và một task Celery.

API hostname không đổi, nên Vercel không cần rebuild khi chỉ đổi máy chạy Tunnel.

## Database và Render

Phase này giữ managed PostgreSQL để compute handoff có rollback nhanh. Render vẫn là fallback cho tới khi có phê duyệt decommission. Không chạy Celery Beat ở hai nơi cùng lúc: trước cutover phải xác định duy nhất một owner chạy scheduled jobs.

Before database migration or Render removal, test backup/restore independently and follow [migration plan](SELF_HOSTED_PRODUCTION_MIGRATION_PLAN.md).

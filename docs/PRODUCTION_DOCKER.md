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
└── backups/
    ├── postgres/
    └── assets/
```

Tạo `.env.production` từ `.env.production.example`. `POSTGRES_PASSWORD` và mật khẩu
trong `DATABASE_URL` phải cùng một giá trị; các ký tự đặc biệt trong URL phải URL-encode.
`DATA_DIR` phải là đường dẫn tuyệt đối, ví dụ `/srv/tacahu-ops/data`.

## Kiểm tra trước deploy

Từ root repo trên VPS:

```bash
git fetch --tags origin
git checkout --detach <commit-sha-hoac-tag-da-duyet>
git status --short                    # phải không in gì

cp .env.production.example .env.production
# sửa .env.production bằng editor trên VPS
# đặt APP_VERSION bằng commit SHA hoặc tag đúng với HEAD hiện tại
mkdir -p /srv/tacahu-ops/data/{postgres,redis,crawled_assets,order_assets,platform_data,playwright_evidence,chrome_profiles}
mkdir -p /srv/tacahu-ops/backups/{postgres,assets}
./scripts/production-preflight.sh
```

Preflight không build image. Nó kiểm tra Docker/Compose, biến môi trường, HTTPS origin,
dung lượng disk, release ref đúng với commit đang checkout, compose rendering và tracked
worktree phải sạch. Không dùng `git pull` mù trên VPS: mỗi deploy bắt đầu từ commit SHA
hoặc Git tag đã chọn rõ ràng.

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

## Backup, restore và rollback

### Backup PostgreSQL

```bash
./scripts/backup-production-postgres.sh
```

Archive custom-format và SHA-256 được lưu tại `$BACKUP_DIR/postgres`. Retention dùng
`BACKUP_RETENTION_DAYS`, mặc định 14 ngày. Nếu cấu hình
`BACKUP_OFFSITE_RCLONE_REMOTE`, script copy archive và checksum sang remote rclone sau
khi local backup thành công.

### Backup assets

```bash
./scripts/backup-production-assets.sh
```

Archive gồm crawl assets, order assets, platform data và Playwright evidence. Chrome
profiles không được đưa lên offsite mặc định vì có thể chứa session/cookie; chỉ bật
`BACKUP_INCLUDE_CHROME_PROFILES=true` khi remote storage đã được bảo vệ phù hợp.

### Lịch mỗi ngày trên VPS

Sau khi mày đã chọn Linux user sở hữu `/srv/tacahu-ops`, chạy một lần bằng `root`:

```bash
sudo DEPLOY_USER=<linux-user> ./scripts/install-production-backup-timers.sh
systemctl list-timers --all 'tacahu-*-backup.timer'
```

PostgreSQL chạy khoảng 00:30 và asset khoảng 01:00 mỗi ngày; `Persistent=true` giúp
systemd chạy bù khi VPS đã tắt đúng lịch. Đây là bước VPS, chưa chạy ở local.

### Restore PostgreSQL

Restore phá hủy nội dung database hiện tại. Trước đó phải chạy backup mới và xác nhận
archive đúng release:

```bash
./scripts/restore-production-postgres.sh --confirm-restore /srv/tacahu-ops/backups/postgres/tacahu-postgres-<timestamp>.dump
```

### Rollback application

Rollback chỉ đổi image application, không tự Alembic downgrade database:

```bash
./scripts/rollback-production.sh --release <image-tag> --with-tunnel
```

Chỉ rollback tới image còn tồn tại trên VPS và đã được kiểm tra tương thích schema.

### Quan sát runtime

```bash
./scripts/production-status.sh --with-tunnel
./scripts/production-logs.sh api
./scripts/production-logs.sh celery-general
```

## Google Sheets

Backup Google Sheet chưa được bật trong Phase 1. Phase 3 sẽ thêm task hằng ngày và mount
credential JSON từ ngoài repo. Không đặt JSON service account vào `.env.production`.

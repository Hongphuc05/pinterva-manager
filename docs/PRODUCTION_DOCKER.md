# Chạy Tacahu Ops production bằng Docker

> Đọc cùng [Tacahu Ops Core](tacahu-ops-core/operations.md) để hiểu boundary dữ liệu,
> migration, verify và workflow trước khi thao tác production.

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
    ├── private_work_note_assets/
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
mkdir -p /srv/tacahu-ops/data/{postgres,redis,crawled_assets,order_assets,private_work_note_assets,platform_data,playwright_evidence,chrome_profiles}
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

Ở lần deploy đầu tiên có mount `private_work_note_assets`, script kiểm tra API container cũ.
Nếu container cũ chưa có mount nhưng còn screenshot Note làm việc, script copy chúng vào
`$DATA_DIR/private_work_note_assets` **trước** khi recreate container. Nếu thư mục đích đã có
file, script dừng thay vì ghi đè; đối soát/merge thủ công rồi deploy lại.

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

Archive gồm crawl assets, order assets, private screenshot/attachment của Note làm việc,
platform data và Playwright evidence. Chrome
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

Google Sheet là snapshot báo cáo một chiều, không phải database backup/restore. Khi bật,
Celery Beat ghi đè tab cấu hình lúc `ORDER_SHEET_BACKUP_HOUR:ORDER_SHEET_BACKUP_MINUTE`
theo `CELERY_TIMEZONE`, chỉ với hai cột `Mã đơn` và `Link DES nộp bài`.

Trước khi bật trên VPS, mày phải tạo Service Account, enable Google Sheets API, tạo Sheet
và share quyền **Editor** cho email của Service Account. Sau đó đặt JSON bên ngoài repo:

```bash
sudo mkdir -p /srv/tacahu-ops/secrets
sudo install -o 10001 -g 10001 -m 600 /path/to/downloaded-service-account.json \
  /srv/tacahu-ops/secrets/google-service-account.json
```

Trong `.env.production`, điền path container, path JSON trên VPS và link Sheet, rồi bật job:

```dotenv
GOOGLE_SERVICE_ACCOUNT_FILE=/run/secrets/google-service-account.json
GOOGLE_SERVICE_ACCOUNT_HOST_FILE=/srv/tacahu-ops/secrets/google-service-account.json
GOOGLE_SHEETS_ORDER_BACKUP_URL=https://docs.google.com/spreadsheets/d/<id>/edit
GOOGLE_SHEETS_ORDER_BACKUP_TAB=Order Backup
ORDER_SHEET_BACKUP_ENABLED=true
```

JSON credential không đi vào `.env.production`, Git hoặc Docker image. Preflight sẽ chặn
deploy nếu job bật mà file/path/link bị thiếu. Lần đầu chỉ chạy task thủ công sau khi mày
đã kiểm tra sheet thử nghiệm; không chạy lên Google Sheet thật trong lúc phát triển.

Sau khi config Sheet thử nghiệm trên VPS, gửi một task thủ công rồi xem log worker:

```bash
docker compose --env-file .env.production -f compose.production.yaml exec celery-general \
  celery -A app.workers.celery_app call \
  app.workers.order_sheet_backup_tasks.export_order_sheet_backup
docker compose --env-file .env.production -f compose.production.yaml logs --tail=100 celery-general
```

Sau khi task hoàn tất, mở lại Sheet bằng trình duyệt để xác nhận tab chỉ có hai cột và
không có dòng trùng. Không dùng lệnh này với Sheet production cho đến khi Sheet thử đã pass.

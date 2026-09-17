# Kế hoạch production VPS Tacahu Ops và backup Google Sheets

**Ngày:** 18/09/2026
**Phạm vi:** đưa toàn bộ Tacahu Ops lên một VPS, phục vụ tại `https://tacahu.fun`, và xuất snapshot đơn hàng tự động hằng ngày sang Google Sheets.
**Không thuộc phạm vi:** triển khai thực tế lên VPS, tạo Cloudflare Tunnel, tạo Google Cloud credential, hoặc chạy Docker build. Các việc này cần thao tác bên ngoài repo và chỉ thực hiện khi có xác nhận/credential từ chủ hệ thống.

## 1. Mục tiêu và nguyên tắc

### Mục tiêu

1. VPS tự chạy đầy đủ React SPA, FastAPI, PostgreSQL, Redis, Celery general worker, Celery assignment worker, Celery Beat và Cloudflare Tunnel.
2. Web và API cùng origin `https://tacahu.fun`; frontend gọi API qua `/api`, không phụ thuộc Vercel.
3. Dữ liệu vận hành tồn tại qua restart/reboot: PostgreSQL, asset crawl, asset đơn, platform data, Playwright evidence và Chrome profiles.
4. Mỗi ngày một lần, Google Sheet chứa chính xác hai cột: `Mã đơn` và `Link DES nộp bài`.
5. Có cơ chế backup/restore thực sự cho PostgreSQL và file assets. Google Sheet chỉ là bản xuất để tra cứu, không phải bản backup có thể khôi phục hệ thống.

### Bất biến kỹ thuật

- PostgreSQL là nguồn sự thật duy nhất cho nghiệp vụ; Google Sheet là projection chỉ đọc.
- Không commit secret: mật khẩu DB, `SECRET_KEY`, Cloudflare token, cookie Printerval, JSON service account Google.
- Không public PostgreSQL hoặc Redis ra Internet.
- Một và chỉ một `celery-beat` chạy trong production để tránh crawl, status sync hoặc backup bị lặp.
- Không dùng source mount, `--reload`, credential trong image production.
- Không rebuild Docker nếu chưa có lệnh rõ ràng từ chủ hệ thống.

## 2. Kiến trúc đích

```mermaid
flowchart LR
    Browser[Admin / Designer browser] --> CF[Cloudflare DNS + Tunnel]
    CF --> API[api: FastAPI + React build]
    API --> PG[(PostgreSQL)]
    API --> Redis[(Redis)]
    General[celery-general] --> Redis
    Assign[celery-assignment] --> Redis
    Beat[celery-beat duy nhất] --> Redis
    General --> PG
    Assign --> PG
    Beat --> GS[Google Sheets snapshot mỗi ngày]
    PG --> DBBackup[pg_dump + offsite backup]
```

Cloudflare Tunnel định tuyến public hostname `tacahu.fun` tới `http://api:8000` trên Docker network. Không cần mở port 80/443; UFW chỉ cần SSH sau khi Cloudflare Tunnel hoạt động.

## 3. Quyết định dữ liệu Google Sheet

### Schema Sheet

| Cột | Nguồn |
|---|---|
| `Mã đơn` | `Order.external_order_id` |
| `Link DES nộp bài` | `ResultVersion.drive_url` mới nhất theo `submitted_at`, fallback `created_at` |

Nếu đơn không có bài nộp hợp lệ, cột link để trống. Không dùng `note_outsource` làm fallback: trường đó có thể là link sản phẩm hoặc ghi chú, không đồng nghĩa bài nộp DES.

### Semantics

- Sheet là **snapshot hiện tại**, không append cả danh sách mỗi ngày.
- Mỗi lần chạy sẽ thay thế vùng dữ liệu của tab `Order Backup`: header ở dòng 1 và dữ liệu bắt đầu từ dòng 2.
- Ghi đè snapshot khiến retry an toàn và không tạo dòng trùng.
- Lịch mặc định: `00:10` mỗi ngày theo `Asia/Ho_Chi_Minh`.
- Tên tab và giờ chạy cấu hình qua environment, không hard-code.

## 4. Phase 1 — Cấu hình Docker production đầy đủ

### 4.1 File sẽ tạo hoặc sửa

| File | Thay đổi |
|---|---|
| `Dockerfile.production` | Multi-stage build: Node build React, Python runtime cài FastAPI/Celery/Playwright Chromium, copy `frontend/dist` vào `/app/frontend/dist`. |
| `compose.production.yaml` | Stack độc lập: `postgres`, `redis`, `migrate`, `api`, hai worker, Beat và `cloudflared`. |
| `.env.production.example` | Danh sách biến production không chứa giá trị secret. |
| `.dockerignore` hoặc production-specific ignore | Loại `.git`, node_modules, credentials, local data, frontend dist và test artifact khỏi build context. |
| `scripts/production-preflight.sh` | Kiểm tra file env, secret path, compose rendering, disk space và không chạy nếu config thiếu. |
| `scripts/deploy-production.sh` | Luồng có kiểm soát: verify commit, build có chủ ý, migration, start service và healthcheck. |

Các file local hiện tại (`compose.local.yaml`, `Dockerfile.local`) giữ nguyên để chạy trên Mac. `compose.yaml` hiện tại chỉ có Redis và giả định PostgreSQL managed/remote; sẽ không bị dùng như production profile mới nếu chưa được chuẩn hóa rõ ràng.

### 4.2 Docker image production

1. Stage `frontend-build` dùng Node LTS, `npm ci`, sau đó `npm run build`.
2. Stage Python dựa trên `python:3.12-slim-bookworm`, cài dependencies từ `pyproject.toml` và Chromium Playwright.
3. Copy backend, Alembic migrations và frontend build vào image cuối.
4. Tạo user không phải root, sở hữu thư mục runtime.
5. API command dùng Uvicorn production; không hot reload.
6. SPA fallback hiện có trong `app/api/main.py` sẽ phục vụ frontend bundle tại cùng domain.

### 4.3 Compose production

`postgres`:

- PostgreSQL 16, named volume hoặc bind mount `/srv/tacahu-ops/data/postgres`.
- Không có `ports:`.
- healthcheck `pg_isready`.

`redis`:

- Redis 7 với AOF, persistent volume.
- Không có `ports:`.
- healthcheck `redis-cli ping`.

`migrate`:

- Chạy `alembic upgrade head`.
- Không restart và API/workers chỉ chạy khi migration thành công.

`api`, `celery-general`, `celery-assignment`, `celery-beat`:

- Dùng cùng một production image và volumes dữ liệu.
- `restart: unless-stopped` trừ migration.
- Log driver local có rotation.
- `celery-assignment` giữ worker riêng với `--pool=solo` theo behavior hiện tại.
- Celery Beat chỉ có đúng một replica.

`cloudflared`:

- Dùng profile `tunnel` để có thể bật sau khi tunnel được tạo.
- Token đọc từ `.env.production`, không in vào log.
- Chờ API healthcheck.

### 4.4 Volumes production

```text
/srv/tacahu-ops/data/postgres
/srv/tacahu-ops/data/redis
/srv/tacahu-ops/data/crawled_assets
/srv/tacahu-ops/data/order_assets
/srv/tacahu-ops/data/platform_data
/srv/tacahu-ops/data/playwright_evidence
/srv/tacahu-ops/data/chrome_profiles
/srv/tacahu-ops/backups/postgres
/srv/tacahu-ops/secrets/google-service-account.json
```

Google credential chỉ mount read-only vào container, ví dụ `/run/secrets/google-service-account.json`.

### 4.5 Environment production

```dotenv
ENVIRONMENT=production
DATABASE_URL=postgresql+psycopg://tacahu:CHANGE_ME@postgres:5432/tacahu_ops
REDIS_URL=redis://redis:6379/0
SECRET_KEY=CHANGE_ME
COOKIE_SECURE=true
CORS_ORIGINS=https://tacahu.fun
DATA_DIR=/srv/tacahu-ops/data

CLOUDFLARE_TUNNEL_TOKEN=

GOOGLE_SERVICE_ACCOUNT_FILE=/run/secrets/google-service-account.json
GOOGLE_SHEETS_ORDER_BACKUP_URL=
GOOGLE_SHEETS_ORDER_BACKUP_TAB=Order Backup
ORDER_SHEET_BACKUP_ENABLED=true
ORDER_SHEET_BACKUP_HOUR=0
ORDER_SHEET_BACKUP_MINUTE=10
CELERY_TIMEZONE=Asia/Ho_Chi_Minh
```

`GOOGLE_SHEETS_ORDER_BACKUP_URL` nhận nguyên link Sheet; backend sẽ parse spreadsheet ID từ link. JSON credential không đi vào `.env`.

### 4.6 Kiểm chứng Phase 1

1. `docker compose -f compose.production.yaml config` pass với env giả lập an toàn.
2. Production Docker image build pass trên máy local CI; không chạy rebuild tự động.
3. API healthcheck trả 200 khi stack khởi động.
4. Frontend bundle được trả tại `/`, API tại `/api`.
5. Postgres/Redis không có published port.
6. Restart stack không mất database/assets.

## 5. Phase 2 — Production readiness trong repo

### 5.1 Chuẩn hóa release

1. Sửa bất nhất `APP_VERSION`/`BACKEND_VERSION` và `APP_SOURCE_DIR` cũ trong script/env/documentation.
2. Mỗi deploy chọn commit SHA hoặc Git tag cụ thể; không `git pull` mù vào production.
3. Preflight kiểm tra Git worktree sạch, compose config, dung lượng disk, migration chain và secret path.
4. Deploy script ghi nhận release đang chạy để rollback về commit/image trước đó.

### 5.2 Backup và restore

1. Tạo job `pg_dump` hằng ngày sang `/srv/tacahu-ops/backups/postgres`.
2. Giữ tối thiểu 7 bản local, theo retention cấu hình.
3. Đồng bộ bản dump và asset sang storage ngoài VPS: ưu tiên Cloudflare R2/S3; Google Drive là lựa chọn thứ hai.
4. Viết script restore vào database rỗng và thực hiện rehearsal trước go-live.
5. Google Sheet không được xem là phương án restore DB.

### 5.3 Observability và vận hành

1. API health endpoint, Docker healthcheck và log rotation.
2. Alert khi container restart lặp, disk gần đầy, migration fail, backup fail hoặc Celery Beat không hoạt động.
3. Ghi rõ runbook: xem log, restart đúng service, restore DB, rollback release.
4. Khi cutover hoàn tất phải dừng API/worker/Beat cũ trên Mac, PC hoặc dịch vụ cũ để tránh task trùng.

### 5.4 Kiểm chứng Phase 2

- Backend tests, frontend production build và compose validation pass.
- Deploy thử từ commit sạch vào môi trường staging/local production-like.
- Reboot test: service tự lên lại, database/assets còn nguyên.
- Restore rehearsal thành công.
- Không có secret bị Git track.

### 5.5 Kết quả triển khai Phase 2

- Chuẩn hóa release production theo `APP_VERSION` trong `compose.production.yaml`;
  deploy chỉ ghi nhận release sau healthcheck, rollback chỉ dùng image tag có sẵn và
  không tự hạ Alembic schema.
- Thêm preflight kiểm tra `APP_VERSION`, backup directory, secrets bắt buộc, HTTPS
  origin, dung lượng, Git worktree và Compose config.
- Thêm backup PostgreSQL custom-format, backup asset, SHA-256, retention cấu hình và
  tùy chọn copy rclone sau khi local backup thành công.
- Thêm restore command có xác nhận phá hủy rõ ràng; archive được kiểm tra trước khi
  ghi vào database.
- Thêm systemd timers hằng ngày, status/log helpers và runbook production. Các
  tài liệu PC/Vercel cũ được đánh dấu legacy để tránh dùng nhầm.

## 6. Phase 3 — Job backup Google Sheets

### 6.1 Adapter

Adapter hiện tại `GoogleSheetsAdapter.export_snapshot` đang append dữ liệu, không phù hợp. Thay đổi interface thành thao tác replace snapshot idempotent:

1. Parse spreadsheet ID an toàn từ URL `docs.google.com/spreadsheets/d/<id>`.
2. Tạo header `Mã đơn`, `Link DES nộp bài`.
3. Clear vùng dữ liệu cũ ở tab cấu hình.
4. Ghi một batch gồm header và toàn bộ rows mới.
5. Fake adapter và contract tests phải dùng cùng semantics replace, không append.
6. Phân loại lỗi Google API: 403/404 là permanent config/access error; 400 là validation; timeout/5xx là transient.

### 6.2 Query dữ liệu

1. Query toàn bộ `Order` có mã external.
2. Join assignment và `ResultVersion`.
3. Chọn `ResultVersion` mới nhất cho mỗi order theo `submitted_at DESC NULLS LAST`, rồi `created_at DESC`.
4. Trả một row mỗi order, sắp xếp deterministic theo mã đơn.
5. Không dùng workflow evidence hay outsource note làm link khi thiếu ResultVersion.

### 6.3 Task và scheduler

1. Tạo module task riêng `app.workers.order_sheet_backup_tasks`.
2. Đăng ký task vào Celery include và route queue `celery`.
3. Cấu hình Celery timezone rõ ràng là `Asia/Ho_Chi_Minh`.
4. Beat schedule gọi task lúc `00:10` mỗi ngày, chỉ khi `ORDER_SHEET_BACKUP_ENABLED=true` và cấu hình Sheet hợp lệ.
5. Dùng khóa chống overlap (DB advisory lock hoặc operation record) để không có hai export đồng thời.
6. Retry có backoff cho lỗi transient; retry lại snapshot an toàn vì operation replace toàn bộ vùng.
7. Ghi audit run: started/finished, số dòng, trạng thái, lỗi đã loại secret.

### 6.4 Google Cloud: thao tác do mày thực hiện

Khi Phase 3 code đã sẵn sàng, mày cần:

1. Mở Google Cloud Console.
2. Chọn/tạo project dành riêng cho Tacahu Ops.
3. Enable **Google Sheets API**.
4. Tạo Service Account và JSON key.
5. Tạo Google Sheet đích, tạo tab `Order Backup` hoặc dùng tên mày chọn.
6. Share Sheet cho email Service Account quyền `Editor`.
7. Đặt JSON key ở VPS: `/srv/tacahu-ops/secrets/google-service-account.json`, quyền file `600`.
8. Dán link Sheet vào `GOOGLE_SHEETS_ORDER_BACKUP_URL` trong `.env.production`.

Không gửi JSON key hoặc Cloudflare token trong chat/repo.

### 6.5 Kiểm chứng Phase 3

1. Unit test parse Sheet URL.
2. Unit test chọn đúng ResultVersion mới nhất cho từng order.
3. Unit test empty link khi chưa nộp bài.
4. Unit/contract test replace snapshot không tạo rows trùng khi chạy hai lần.
5. Test lỗi transient retry và lỗi 403 fail rõ ràng.
6. Sau khi mày cấu hình Sheet thử nghiệm: chạy một task thủ công, đọc lại Sheet bằng request mới và xác nhận hai cột chính xác.

### 6.6 Kết quả triển khai Phase 3

- `GoogleSheetsAdapter` và fake adapter dùng replace snapshot: clear toàn bộ tab rồi
  batch-write header + dữ liệu, vì vậy retry không tạo dòng trùng.
- Export chỉ ghi hai cột `Mã đơn`, `Link DES nộp bài`; mỗi order chọn `ResultVersion`
  mới nhất theo `submitted_at`, fallback `created_at`, và để link trống nếu chưa nộp.
- Celery Beat chỉ đăng ký lịch khi `ORDER_SHEET_BACKUP_ENABLED=true`; giờ chạy theo
  `CELERY_TIMEZONE`, mặc định `00:10 Asia/Ho_Chi_Minh`.
- Mỗi ngày/config Sheet có một `operations` record idempotent làm audit và khóa overlap.
  Retry exponential chỉ áp dụng cho lỗi transient/rate-limit/unknown outcome; lỗi cấu hình
  hoặc 403/404 không retry. Không lưu raw Google error text vào audit.
- Credential JSON được bind-mount read-only từ VPS vào container và bị preflight kiểm tra;
  không có credential hay request Google thật trong test/repo.

## 7. Phase 4 — Cutover VPS

### 7.1 Thao tác trên VPS do mày thực hiện

Chỉ làm sau khi Phase 1–3 pass review/test.

1. Cài Ubuntu 24.04 LTS, đăng nhập SSH bằng root lần đầu.
2. Cài Docker Engine + Docker Compose plugin, Git, UFW.
3. Tạo user deploy và thư mục `/srv/tacahu-ops`.
4. Clone repo đúng commit/tag được duyệt.
5. Tạo `.env.production` từ template và điền secret trên VPS.
6. Tạo cấu trúc volume/data/secret ở phần 4.4.
7. Cấu hình Cloudflare DNS zone cho `tacahu.fun`, tạo Tunnel và lấy token.
8. Chạy preflight/deploy command được cung cấp tại thời điểm đó.
9. Kiểm tra `https://tacahu.fun`, login, crawl, nộp bài, asset, background workers và Google Sheet.
10. Sau xác nhận, dừng runtime cũ trên Mac/PC.

### 7.2 Quy trình deploy dự kiến

```bash
cd /srv/tacahu-ops
git fetch --tags origin
git checkout --detach <approved-commit-or-tag>
./scripts/production-preflight.sh
./scripts/deploy-production.sh --build
docker compose -f compose.production.yaml --env-file .env.production ps
```

Lệnh chính xác chỉ được chốt sau khi các scripts/configuration hoàn thành và được test; không chạy các lệnh trên VPS ngay từ bây giờ.

## 8. Thứ tự thực hiện

1. **Bây giờ:** review tài liệu này và chốt thiết kế.
2. **Sau khi được duyệt:** implement Phase 1 trong repo, không Docker rebuild.
3. Implement Phase 2, test/review production-like.
4. Implement Phase 3 bằng fake adapter/test; chưa gọi Google Sheet thật.
5. Mày tạo Google credential và share Sheet khi tao yêu cầu ở Phase 3.4.
6. Chuẩn bị VPS và cutover theo Phase 4.

## 9. Tiêu chí hoàn thành cuối cùng

- `https://tacahu.fun` phục vụ cả SPA và API từ VPS.
- PostgreSQL và Redis không exposed public.
- Reboot VPS không mất dữ liệu và service tự khởi động lại.
- Một Celery Beat duy nhất chạy trong production.
- Google Sheet cập nhật hằng ngày đúng giờ Việt Nam, chỉ hai cột, không duplicate.
- Lỗi Google Sheet có audit và retry phù hợp, không lộ secret.
- Có pg_dump, retention, offsite copy và restore rehearsal.
- Không còn Vercel/PC/Mac là dependency bắt buộc của production.

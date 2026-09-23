# Hướng dẫn crawl historical Printerval cho Support

Tài liệu này dành cho người chạy backfill một lần khoảng 100k design-job records.
Lệnh crawl chỉ đọc Printerval, lấy các status `done`, `confirm`, `review`, `fix`,
và lưu mã job, tên sản phẩm, status cùng link ảnh preview vào schema
`support_compare_image` trong PostgreSQL production.

Crawler **không tải binary ảnh**, không kiểm tra `note_outsource` để quyết định
include/exclude, và không gọi API đổi status/note/assignment.

## 1. Chuẩn bị máy chạy

Yêu cầu:

- Python 3.12 trở lên.
- Có đường kết nối private tới PostgreSQL production.
- Có quyền chạy migration và insert vào schema `support_compare_image`.
- Có credential Printerval của đúng platform/team mà Tacahu production đang dùng.

Không mở PostgreSQL ra Internet công khai. Nếu máy chạy crawler ở ngoài VPS,
dùng SSH tunnel:

```bash
ssh -N -L 15432:127.0.0.1:5432 USER@VPS_HOST
```

Giữ terminal này chạy trong suốt thời gian crawl. Nếu PostgreSQL đang lắng nghe
ở một private network khác, dùng private address tương ứng thay vì mở public port.

## 2. Cài package

Giải nén/copy toàn bộ folder `support_compare_image` sang máy chạy, sau đó:

```bash
cd support_compare_image
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Không commit `.env`, không gửi `.env` qua chat, và không ghi credential vào log.

## 3. Điền `.env`

Ví dụ khi dùng SSH tunnel:

```dotenv
DATABASE_URL=postgresql+psycopg://DB_USER:DB_PASSWORD@127.0.0.1:15432/DB_NAME
PRINTERVAL_API_BASE_URL=https://printerval.com
PRINTERVAL_TEAM_OUTSOURCE=thuyhuong
PRINTERVAL_USERNAME=...
PRINTERVAL_PASSWORD=...
PRINTERVAL_PAGE_SIZE=100
PRINTERVAL_REQUEST_DELAY_SECONDS=0.25
PRINTERVAL_TIMEOUT_SECONDS=30
PRINTERVAL_MAX_RETRIES=5
```

Có thể dùng cookie thay cho username/password:

```dotenv
PRINTERVAL_SESSION_COOKIE=Cookie: laravel_session=...; other_cookie=...
```

Cookie phải là chuỗi đầy đủ lấy từ session đang đăng nhập và có thể hết hạn.
Không dùng lại chuỗi cookie đã bị cắt ngắn hoặc đưa lên terminal history nếu máy
không được bảo vệ.

## 4. Tạo schema trước

Chạy từ bên trong folder `support_compare_image`:

```bash
source .venv/bin/activate
alembic -c alembic.ini upgrade head
```

Migration chỉ tạo schema và bảng có prefix logic `support_compare_image`; không
chạy migration của Tacahu Ops và không thay đổi bảng `orders`/`order_assets`.

Có thể kiểm tra:

```bash
python - <<'PY'
from sqlalchemy import create_engine, text
from support_compare_image.config import get_settings

engine = create_engine(get_settings().database_url)
with engine.connect() as conn:
    print(conn.execute(text("select current_database(), current_user")).one())
    print(conn.execute(text("select schema_name from information_schema.schemata where schema_name = 'support_compare_image'")).all())
PY
```

## 5. Dry-run, chưa ghi database

Dry-run sẽ gọi API theo từng status, báo tổng API, số row normalize được và số row
thiếu preview. Nó không tạo `crawl_run` và không insert dữ liệu:

```bash
python crawl_100k.py dry-run --delay 0.5 2>&1 | tee dry-run.log
```

Nếu chỉ muốn kiểm tra một status:

```bash
python crawl_100k.py dry-run --status done --delay 0.5
```

Không xem `preview_missing` là lý do bỏ cả job; job vẫn được lưu ở bước crawl để
count historical có thể đối soát với API.

## 6. Chạy pilot 100 row

`--limit 100` dừng ở biên page. Với `page_size=100`, pilot thường fetch một page
cho status đầu tiên, nhưng số row thực tế vẫn phải đọc từ JSON summary.

```bash
python crawl_100k.py crawl --limit 100 --confirm 2>&1 | tee pilot.log
```

Lưu lại `run_id` trong output. Kiểm tra pilot:

```sql
SELECT status, COUNT(*)
FROM support_compare_image.historical_jobs
GROUP BY status
ORDER BY status;

SELECT COUNT(*) AS jobs,
       COUNT(*) FILTER (WHERE preview_missing) AS missing_preview
FROM support_compare_image.historical_jobs;
```

Kiểm tra thủ công một số `external_order_id`, `product_name` và `preview_url` với
giao diện admin Printerval trước khi chạy full.

## 7. Chạy full historical crawl

Chỉ chạy sau khi dry-run và pilot đã được kiểm tra:

```bash
python crawl_100k.py crawl --full-run --confirm 2>&1 | tee crawl-100k.log
```

Lệnh này tuần tự crawl:

```text
done -> confirm -> review -> fix
```

Mỗi page được commit cùng checkpoint. Nếu dừng giữa chừng, không xóa dữ liệu và
không chạy lại từ đầu bằng một run mới.

## 8. Resume khi bị gián đoạn

Lấy `run_id` từ output hoặc query:

```sql
SELECT id, mode, run_status, discovered_count, stored_count,
       preview_missing_count, malformed_count, error_count,
       started_at, finished_at
FROM support_compare_image.crawl_runs
ORDER BY started_at DESC
LIMIT 10;
```

Resume đúng run:

```bash
python crawl_100k.py resume \
  --run-id RUN_UUID \
  --confirm \
  2>&1 | tee -a crawl-100k.log
```

Checkpoint được lưu theo status/page. Upsert dùng `(source_system, source_job_id)`
nên fetch lại một page không tạo duplicate job.

## 9. Theo dõi và đối soát

Trong lúc chạy, theo dõi:

- `run_status`, `last_status`, `last_page_id`;
- `discovered_count`, `stored_count`, `preview_missing_count`;
- `malformed_count`, `error_count`;
- CPU/RAM/connection của PostgreSQL production;
- lỗi `auth`, `rate_limit`, `transient_network`, `external_changed`.

Sau khi hoàn tất:

```sql
SELECT run_status, discovered_count, stored_count,
       preview_missing_count, malformed_count, error_count,
       status_counts
FROM support_compare_image.crawl_runs
WHERE id = 'RUN_UUID';

SELECT status, COUNT(*)
FROM support_compare_image.historical_jobs
GROUP BY status
ORDER BY status;

SELECT COUNT(*) AS preview_assets
FROM support_compare_image.image_assets;
```

`stored_count` là số row normalize/upsert trong các page; số job unique là
`COUNT(*)` trong `historical_jobs`.

## 10. Lưu ý vận hành

- Không chạy đồng thời hai full run.
- Không thêm `--full-run` vào cron/Celery/startup.
- Nếu gặp rate limit, dừng run và resume sau; không tăng concurrency.
- Nếu auth fail, lấy credential/cookie mới rồi resume cùng `run_id`.
- Nếu API trả schema lỗi, giữ lại `crawl_errors` để điều tra; không coi lỗi đó là
  page rỗng.
- Folder này chưa chạy embedding. Dimension/model/version/metric sẽ được bổ sung
  ở migration và worker riêng sau khi hợp đồng model được chốt.

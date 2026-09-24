# dup-compare — phát hiện ảnh sản phẩm trùng thiết kế

Bench kiểm tra xem hai ảnh sản phẩm (mockup áo...) có **trùng thiết kế** hay không.
Mỗi cặp ảnh được chấm theo 4 tín hiệu:

| Tín hiệu | Dùng để | Nguồn |
|---|---|---|
| Visual similarity | độ giống về bố cục/artwork (tín hiệu chính) | DINOv2 embedding, cosine |
| pHash distance | bắt ảnh gần như y hệt (resize, nén nhẹ) | `imagehash`, 256-bit |
| SSIM | chặn trường hợp sim cao nhưng họa tiết khác | `scikit-image` |
| Color ΔE (LAB) | nhận biết đổi màu sản phẩm | `scikit-image`, CIE76 |

Kết quả chỉ có 2 nhãn: **`TRUNG`** / **`KHONG_TRUNG`**. Lý do cụ thể (y hệt, đổi màu,
có thể khác custom text) nằm trong `reasons`.

Module có 3 phần:

1. **So 1-1** (`frontend/index.html`): upload 2 ảnh rồi xem ngay từng tín hiệu.
2. **Quét pool tăng dần** (`frontend/scan.html`): ingest kho `data/old/` một lần,
   sau đó quét `data/new/` lần lượt theo tên file. Mỗi ảnh mới được so với toàn bộ
   pool (gồm ảnh cũ và ảnh mới đã quét trước nó), gắn nhãn, rồi được thêm vào pool.
   Dữ liệu lưu trong SQLite.
3. **Backfill embedding** (`embed_backfill.py`): tính embedding cho ảnh Printerval đã
   crawl và ghi vào Postgres trên VPS (schema `support_compare_image`). Chạy trên máy
   có GPU.
4. **So sánh với PostgreSQL** (`compare_orders.py`): lấy ảnh preview của order từ
   `public.orders`, đọc pool DINOv2 cũ từ `support_compare_image.image_embeddings`,
   tính candidate và ghi kết quả vào các bảng `comparison_*`. Có thể chạy thử với
   order `review`; các order này không được promote ngược vào pool.

## Cài đặt

```bash
cd dup-compare
pip install -r ../requirements.txt -r ../requirements.compare-runtime.txt
```

Lần đầu chạy, model `facebook/dinov2-base` (khoảng 300–400MB) được tải từ Hugging Face,
nên máy cần có mạng. Có GPU CUDA thì dùng GPU, không thì chạy CPU.

> **Fallback:** nếu không load được DINOv2 (mất mạng, thiếu thư viện...), hệ thống tự
> chuyển sang descriptor HOG cổ điển. Lúc đó UI hiện cảnh báo màu vàng và
> `meta.embedding_backend` ghi rõ backend đang dùng. Fallback chỉ để demo cho chạy được,
> **không dùng số liệu của nó để đánh giá hay calibrate**.

## 1. Chạy server (so 1-1 + quét pool)

```bash
uvicorn backend.main:app --reload --port 8000
```

- `http://127.0.0.1:8000/`: so 1-1
- `http://127.0.0.1:8000/scan.html`: quét pool

### Quét pool

Mặc định thư mục `data/` nằm cạnh `dup-compare/`:

```
dup-product/
  data/
    old/               <- kho ảnh gốc
    new/               <- ảnh mới, chờ kiểm tra
    dup_detection.db   <- SQLite, tự tạo
    labeled_examples/  <- dataset gán nhãn tay (cho calibrate_dataset.py)
  dup-compare/
```

Nếu thư mục nằm chỗ khác, đặt biến môi trường trước khi chạy uvicorn
(`DATA_DIR`, hoặc chỉ định riêng `OLD_IMAGES_DIR`, `NEW_IMAGES_DIR`, `DB_PATH`):

```powershell
$env:DATA_DIR = "D:\Project\dup-product\data"
```

Trên `scan.html`:

1. **Ingest kho ảnh cũ**: encode và lưu các ảnh trong `old/`. Chạy lại nhiều lần không
   bị trùng, ảnh đã có sẽ được bỏ qua.
2. **Quét ảnh mới tuần tự**: với mỗi ảnh trong `new/`, lấy Top-K ứng viên gần nhất theo
   embedding (`TOP_K_CANDIDATES`, mặc định 5), tính pHash/SSIM/ΔE cho từng ứng viên rồi
   gắn nhãn. Chỉ cần 1 ứng viên `TRUNG` là ảnh bị gắn `TRUNG`. Bấm vào card để xem
   tất cả ứng viên.
3. **Reset DB**: xóa file SQLite. File ảnh trong `old/` và `new/` không bị đụng tới.

Tìm Top-K bằng cách nhân ma trận numpy trong RAM, không dùng index. Khoảng 100k ảnh
× 768 chiều tốn chừng 300MB RAM. Nếu lên tới hàng triệu ảnh thì cần vector index
(pgvector/HNSW), chỗ cần thay là `db.get_pool()`.

> **Embedding chỉ so sánh được với nhau khi dùng cùng model.** Ảnh trong DB được lưu
> kèm tên model. Khi đổi `EMBEDDING_MODEL_NAME`, hoặc đổi qua lại giữa fallback và
> DINOv2, các ảnh của model cũ sẽ bị loại khỏi pool (`scan.html` có hiện cảnh báo).
> Muốn cả pool dùng model mới thì Reset DB rồi Ingest lại.

### API

| Method | Path | Mô tả |
|---|---|---|
| `GET` | `/health` | backend embedding đang dùng + các đường dẫn |
| `GET` | `/config` | threshold đang áp dụng |
| `POST` | `/compare` | so 1-1, form-data `old_image`, `new_image` |
| `GET` | `/admin/pool` | thống kê pool + số ảnh thuộc model khác |
| `POST` | `/admin/ingest-old` | ingest `data/old/` |
| `POST` | `/admin/scan-new` | quét `data/new/` tuần tự |
| `POST` | `/admin/reset` | xóa DB |
| `GET` | `/admin/image/{id}` | trả file ảnh (hoặc redirect nếu là URL) |

Ví dụ response của `/compare`:

```json
{
  "is_duplicate": true,
  "classification": "TRUNG",
  "confidence": 0.958,
  "signals": {
    "visual_similarity": 0.958,
    "phash_distance": 8,
    "phash_max_distance": 256,
    "ssim": 0.94,
    "color_delta_e": 18.4,
    "ocr_similarity": null
  },
  "reasons": ["...", "=> Bố cục/artwork giống nhau nhưng màu sản phẩm lệch (...): đổi màu."],
  "meta": {
    "embedding_backend": "facebook/dinov2-base",
    "model_version": "dinov2-base-v1",
    "processing_version": "mvp-0.2.0",
    "elapsed_ms": 412.3
  }
}
```

## 2. Backfill embedding lên Postgres VPS

Script `embed_backfill.py` tính embedding, pHash và màu LAB cho các ảnh trong
`support_compare_image.image_assets`, rồi ghi vào bảng `image_embeddings`. Schema bảng
này do migration `0002_image_embeddings` bên `pinterva-manager` tạo ra.

```powershell
# Terminal 1: mở SSH tunnel tới Postgres, để nguyên cửa sổ này
ssh -N -L 15432:127.0.0.1:5432 USER@VPS_HOST

# Terminal 2
cd dup-compare
$env:DATABASE_URL = "postgresql://USER:PASS@127.0.0.1:15432/DB"
py embed_backfill.py --limit 200   # chạy thử
py embed_backfill.py               # chạy toàn bộ
```

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `--limit` | – | chỉ xử lý N ảnh (để chạy thử) |
| `--chunk` | 512 | số ảnh ghi DB mỗi transaction |
| `--batch` | 64 | batch size trên GPU |
| `--workers` | 16 | số thread tải ảnh song song |

- **Chạy tiếp được:** ảnh đã có embedding của model hiện tại sẽ được bỏ qua, nên cứ chạy
  lại để làm tiếp chỗ dở. Nếu mất tunnel giữa chừng thì chỉ mất chunk đang chạy dở.
- **Ảnh lỗi** (link chết, 403, ảnh hỏng) bị đánh dấu `fetch_status='failed'` kèm
  `last_error`, và không làm dừng cả lượt chạy.

**Kiểm tra tiến độ** (chạy psql trên VPS):

```bash
docker exec -it $(docker ps -qf name=postgres) sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

```sql
-- Chỉ còn 'embedded' và 'failed' nghĩa là đã xong
SELECT fetch_status, COUNT(*) FROM support_compare_image.image_assets GROUP BY 1;

-- Xem lý do lỗi
SELECT last_error, COUNT(*) FROM support_compare_image.image_assets
WHERE fetch_status = 'failed' GROUP BY 1 ORDER BY 2 DESC LIMIT 10;

-- Cho các ảnh lỗi chạy lại, rồi chạy lại embed_backfill.py
UPDATE support_compare_image.image_assets SET fetch_status = 'pending' WHERE fetch_status = 'failed';
```

**Quy ước lưu embedding** (bên đọc dữ liệu phải theo đúng quy ước này):
`embedding` là bytes float32 little-endian, đã L2-normalize, lấy trung bình các patch
token (bỏ CLS), 768 chiều với dinov2-base. `model_version` là tên model trên Hugging
Face. Metric là cosine, bằng dot product vì vector đã chuẩn hóa. Tiền xử lý ảnh
(`convert("RGB")`) giống hệt `scan.py`, nên vector từ hai phía so với nhau được.

> Hiện tại luồng quét pool (`scan.html`) vẫn đọc từ SQLite, chưa đọc từ bảng
> `image_embeddings` trên Postgres.

## 3. So sánh order mẫu từ `public.orders`

Migration `support_compare_image/migrations/versions/0003_comparison_runs.py` tạo
`comparison_runs`, `comparison_items` và `comparison_candidates`. Chạy migration
trước khi compare:

```bash
cd support_compare_image
alembic upgrade head
cd dup-compare
```

`compare_orders.py` dùng model Hugging Face thật, mặc định là
`facebook/dinov2-base`. Nó không dùng HOG fallback, vì vector fallback không cùng
không gian với 85k embedding DINOv2 đang có.

Mở SSH tunnel tới PostgreSQL nếu chạy ngoài VPS:

```bash
ssh -N -L 15432:127.0.0.1:5432 USER@VPS_HOST
export DATABASE_URL='postgresql://USER:PASSWORD@127.0.0.1:15432/DB_NAME'
```

Chạy thử tối đa 10 order có `printerval_status='review'` hoặc `state='QC_PENDING'`:

```bash
python compare_orders.py \
  --source review \
  --limit 10 \
  --model facebook/dinov2-base \
  --confirm
```

Ảnh mới được chọn theo thứ tự `thumbnail_url`, rồi tới ảnh đầu tiên của
`product_image_urls`. Khi source là `review`, comparator loại candidate có cùng
`external_order_id` với order mới để tránh tự match, vì pool historical trước đó
đã chứa cả status `review`.

Kiểm tra kết quả:

```sql
SELECT id, source_kind, run_status, baseline_count, requested_count,
       processed_count, duplicate_count, error_count, started_at, finished_at
FROM support_compare_image.comparison_runs
ORDER BY started_at DESC
LIMIT 10;

SELECT i.external_order_id AS new_order,
       i.product_name AS new_product,
       c.matched_external_order_id AS old_order,
       c.matched_product_name AS old_product,
       c.visual_similarity, c.phash_distance, c.ssim,
       c.classification, c.decision_status
FROM support_compare_image.comparison_candidates c
JOIN support_compare_image.comparison_items i
  ON i.id = c.comparison_item_id
ORDER BY c.created_at DESC
LIMIT 50;
```

Không dùng `--include-self` trong test thông thường. Không bật `SUPPORT_COMPARE_ENABLED`
cho production trước khi kiểm tra kết quả thực tế và Telegram recipient.

Migration `0004_support_unchecked_source.py` mở source runtime `support_unchecked`. Source này
quét order `uncheck` ở cả Waiting và Doing; ảnh preview được embedding, so sánh với pool rồi
promote vào pool sau khi xử lý thành công. Top-1 theo similarity mới được dùng làm cặp Telegram.
Nếu top-1 là `KHONG_TRUNG`, order không bị đổi status và vẫn nằm trong tab Chưa kiểm tra để
được quét lại khi pool tăng.

Có thể chạy pilot thủ công toàn bộ queue (nên dùng `--limit` nhỏ khi test):

```bash
python compare_orders.py \
  --source support_unchecked \
  --limit 10 \
  --model facebook/dinov2-base \
  --confirm
```

Source `waiting` cũ vẫn giữ cơ chế terminal sau khi promote ở model/version hiện tại và chỉ
dành cho compatibility. Có thể chạy pilot Waiting cũ:

```bash
python compare_orders.py \
  --source waiting \
  --limit 10 \
  --model facebook/dinov2-base \
  --confirm
```

Trong production, bật `SUPPORT_COMPARE_ENABLED=true` sẽ để Celery Beat enqueue vào queue
`support-compare`; worker `celery-compare` xử lý tuần tự, tách khỏi queue general/assignment.
Review chỉ là nguồn test: candidate được lưu để kiểm tra, nhưng callback Telegram bị chặn không
cho đổi trạng thái order. Candidate live `support_unchecked` mới được phép đi qua command Support;
Doing chỉ được phân loại qua callback Telegram, còn command web vẫn Waiting-only.

## 4. Chuyển sang weight fine-tune ở phase 2

Có thể trỏ runner tới một thư mục Hugging Face local:

```bash
python compare_orders.py \
  --source review \
  --limit 10 \
  --model /path/to/finetuned-dinov2 \
  --model-version dinov2-finetuned-v1 \
  --confirm
```

Nếu dimension, preprocessing hoặc model space thay đổi, phải re-embed pool cũ bằng
đúng weight mới trước khi so sánh. Không trộn vector `facebook/dinov2-base` với
vector fine-tune trong cùng một pool.

## 5. Test và calibrate

```bash
# Smoke test bằng ảnh vẽ tay tổng hợp, không cần ảnh thật
python test_pipeline.py
EMBEDDING_BACKEND=classical python test_pipeline.py   # ép dùng fallback, không cần mạng

# Chạy dataset gán nhãn tay data/labeled_examples/manifest.json, in số thật của từng
# cặp và đánh dấu những cặp classify() đang phân loại sai
python calibrate_dataset.py
```

Chỉ dùng `calibrate_dataset.py` với DINOv2 thật. Script sẽ cảnh báo nếu đang chạy
fallback.

## Cấu hình (biến môi trường, xem `backend/config.py`)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `EMBEDDING_MODEL_NAME` | `facebook/dinov2-base` | model trên Hugging Face (đổi sang DINOv3 cũng chỉ cần sửa biến này) |
| `EMBEDDING_BACKEND` | `auto` | `classical` = ép dùng fallback HOG |
| `EXACT_PHASH_MAX_DISTANCE` | 6 | pHash ≤ ngưỡng này và sim ≥ `EXACT_SIMILARITY_THRESHOLD` thì coi là y hệt |
| `EXACT_SIMILARITY_THRESHOLD` | 0.97 | |
| `DESIGN_SIMILARITY_THRESHOLD` | 0.85 | sim tối thiểu để coi là cùng thiết kế |
| `DESIGN_SSIM_MIN_THRESHOLD` | 0.60 | sim cao nhưng SSIM dưới ngưỡng này thì vẫn là `KHONG_TRUNG` |
| `COLOR_DIFFERENCE_THRESHOLD` | 12.0 | ΔE từ ngưỡng này trở lên thì ghi lý do "đổi màu" (không ảnh hưởng nhãn) |
| `OCR_SIMILARITY_THRESHOLD` | 0.90 | chưa dùng, OCR chưa được tích hợp |
| `TOP_K_CANDIDATES` | 5 | số ứng viên được kiểm tra kỹ cho mỗi ảnh mới |
| `DATA_DIR`, `OLD_IMAGES_DIR`, `NEW_IMAGES_DIR`, `DB_PATH` | xem trên | đường dẫn |
| `MODEL_VERSION`, `PROCESSING_VERSION` | `dinov2-base-v1`, `mvp-0.2.0` | chỉ để hiển thị trong `meta` |

Các ngưỡng mới được calibrate sơ bộ trên vài cặp ảnh gán nhãn tay, **cần tune lại khi có
thêm dữ liệu thật** (dùng `calibrate_dataset.py`).

## Giới hạn hiện tại

- **Chưa tách riêng vùng áo (garment segmentation):** mọi tín hiệu đều tính trên toàn
  ảnh, nên nền, ánh sáng và tư thế người mẫu có thể làm lệch số.
- **Chưa có OCR:** ảnh cùng thiết kế nhưng khác custom text (NAME/YEAR/NUMBER) vẫn bị
  tính là `TRUNG`.
- **Chưa crop riêng vùng in:** vùng in chưa được đánh trọng số cao hơn phần còn lại.
- **SQLite + tìm kiếm vét cạn:** đủ cho cỡ khoảng 100k ảnh trên một máy, chưa phải hệ
  thống production.

## Cấu trúc

```
dup-compare/
  backend/
    config.py       # threshold, model, đường dẫn (đọc từ biến môi trường)
    embedding.py    # VisualEmbedder: DinoV2Embedder + ClassicalFallbackEmbedder
    signals.py      # pHash, SSIM, màu LAB / ΔE
    classifier.py   # luật gắn nhãn TRUNG / KHONG_TRUNG
    db.py           # SQLite: bảng images, matches
    scan.py         # ingest_folder(), scan_new_sequential()
    main.py         # FastAPI
  frontend/
    index.html      # UI so 1-1
    scan.html       # UI quét pool
  embed_backfill.py     # backfill embedding lên Postgres VPS
  calibrate_dataset.py  # đo trên dataset gán nhãn tay
  test_pipeline.py      # smoke test bằng ảnh tổng hợp
  requirements.txt
```

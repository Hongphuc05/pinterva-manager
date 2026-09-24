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

Module có 3 phần (pool 85k ảnh lịch sử đã được crawl và embedding một lần trước đó, nay chỉ tăng thêm qua luồng `/check`):

1. **So 1-1** (`frontend/index.html`): upload 2 ảnh rồi xem ngay từng tín hiệu.
2. **Tìm ảnh trong pool** (`review-ui`, mục "Tìm ảnh"): tải 1 ảnh từ máy lên (kéo thả, dán hoặc chọn),
   tìm 10 ảnh gần nhất trong pool Postgres kèm mã đơn, độ giống, pHash/SSIM, kết luận của model và
   custom configuration.
3. **So sánh với PostgreSQL** (`compare_orders.py`): lấy ảnh preview của order từ
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

## 1. Chạy server (so 1-1, duyệt kết quả, tìm ảnh)

```bash
uvicorn backend.main:app --reload --port 8000
```

- `http://127.0.0.1:8000/`: duyệt kết quả và tìm ảnh (cần đã build `review-ui`, xem mục Docker)
- `http://127.0.0.1:8000/index.html`: so 1-1 hai ảnh

### API

| Method | Path | Mô tả |
|---|---|---|
| `GET` | `/health` | backend embedding đang dùng + các đường dẫn |
| `GET` | `/config` | threshold đang áp dụng |
| `POST` | `/compare` | so 1-1, form-data `old_image`, `new_image` |

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

## 2. So sánh order mẫu từ `public.orders`

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
quét order `uncheck` chưa từng có kết quả so sánh (state Waiting hoặc Doing); ảnh preview được
embedding và so với pool Postgres. Các order trong cùng lô **không so chéo nhau**; cả lô được
thêm vào pool sau khi so xong. Mỗi order ghi `review_status`: `pending_review` (model nghi trùng)
hoặc `no_match`. Không có cặp nào tự gửi Telegram: Support duyệt ở giao diện `review-ui` (mục dưới).

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

Trong production, bật `SUPPORT_COMPARE_ENABLED=true`. Job `support_unchecked` chỉ được tạo khi
Support xác nhận `/check` trên Telegram (hoặc nút **Kiểm tra trùng** trên web) vào bảng
`support_compare_image.comparison_jobs`; **không có job tự động theo lịch**. VPS chỉ tạo job và
gửi Telegram; nó không cài hoặc load DINO. `local_worker.py` trên máy Support mới claim job,
load Hugging Face model và ghi kết quả.
Review chỉ là nguồn test: candidate được lưu để kiểm tra, nhưng callback Telegram bị chặn không
cho đổi trạng thái order. Candidate live `support_unchecked` mới được phép đi qua command Support;
Doing chỉ được phân loại qua callback Telegram, còn command web vẫn Waiting-only.

### Chạy local worker cho job `/check`

```bash
cd support_compare_image
cp .env.local-worker.example .env.local-worker

# Terminal 1: giữ tunnel tới PostgreSQL trên VPS
ssh -N -L 15432:127.0.0.1:5432 USER@VPS_HOST

# Terminal 2: cài dependency và chạy worker trên máy Support
set -a; source .env.local-worker; set +a
python -m pip install -r requirements.txt -r requirements.compare-runtime.txt
python dup-compare/local_worker.py
```

Smoke test một job rồi thoát bằng `python dup-compare/local_worker.py --once`. Worker giữ model
trong RAM giữa các job; nếu máy Support dừng, job còn `queued` sẽ chạy tiếp khi worker lên lại.
Không mở PostgreSQL public Internet chỉ để phục vụ worker.

### Chạy bằng Docker (khuyên dùng trên máy Support)

Một lệnh chạy cả tunnel SSH tới Postgres, worker DINOv2 và trang duyệt, không cần mở nhiều terminal:

```bash
cd support_compare_image
docker compose up -d           # lần đầu build image (~5 phút), model DINOv2 tải khi có job đầu tiên
# duyệt tại http://127.0.0.1:8000/
docker compose logs -f worker  # xem tiến trình embedding/so sánh
docker compose down            # tắt
```

Cần `.env.local-worker` (giữ `DATABASE_URL=...@127.0.0.1:15432/...`; tunnel, worker và review dùng chung
network nên địa chỉ này vẫn đúng). Tunnel dùng `~/.ssh/id_ed25519` (đổi bằng `SSH_KEY=...`) và
`~/.ssh/known_hosts`; khóa phải không có passphrase. Code Python `dup-compare/` được mount vào
container, sau khi `git pull` chỉ cần `docker compose restart worker review`. Giao diện duyệt
(`review-ui/`, React + Vite + Tailwind) được build vào image, nên khi đổi giao diện hoặc requirements
thì chạy `docker compose up -d --build`.
Đừng chạy song song worker/tunnel thủ công với compose.

### Duyệt kết quả trên localhost (`review-ui/`)

Sau khi worker so sánh xong một job, Support duyệt các order nghi trùng:

```bash
cd support_compare_image/dup-compare
set -a; source ../.env.local-worker; set +a      # cần tunnel tới Postgres đang mở
../../.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
# mở http://127.0.0.1:8000/
```

Giao diện là app React 19 + Vite 8 + Tailwind 4 + TypeScript trong `review-ui/` (cùng stack và design
token với dashboard Tacahu Ops). Muốn chạy không dùng Docker: `cd review-ui && npm ci && npm run build`
trước khi chạy `uvicorn`. Phát triển giao diện: chạy `uvicorn` ở cổng 8000 rồi `npm run dev` trong
`review-ui/` (Vite proxy `/review/*` về cổng 8000); test bằng `npm test`. Hai công cụ cũ vẫn ở
`/index.html` (so sánh 1-1).

Mỗi thẻ hiện ảnh gốc và top-5 candidate, tất cả kèm mã đơn:

- **Chọn ảnh này là trùng**: ghi `selected_duplicate`; VPS gửi cặp (ảnh gốc, ảnh đã chọn) lên
  Telegram trong ≤60 giây. **Xác nhận trùng** gắn tag Trùng lặp và chuyển tab; **Từ chối** đưa order
  vào Không trùng lặp.
- **Model sai**: ghi `ai_wrong`; order nằm cùng nhóm với các order `no_match`, vẫn ở tab Chưa kiểm
  tra cho tới khi Support gõ `/handle` trên Telegram.
- Sau khi cặp đã gửi Telegram thì lựa chọn không đổi được nữa.

Trang này chỉ ghi vào schema `support_compare_image`, chỉ nhận request same-origin tới
`127.0.0.1`/`localhost`, và không bao giờ đổi order. Không mở cổng ra ngoài (`--host 127.0.0.1`).

## 3. Chuyển sang weight fine-tune ở phase 2

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

## 4. Test và calibrate

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
- **Tìm kiếm vét cạn (nhân ma trận numpy trong RAM):** đủ cho cỡ khoảng 100k ảnh; nhiều hơn cần vector index.

## Cấu trúc

```
dup-compare/
  backend/
    config.py       # threshold, model (đọc từ biến môi trường)
    embedding.py    # VisualEmbedder: DinoV2Embedder + ClassicalFallbackEmbedder
    signals.py      # pHash, SSIM, màu LAB / ΔE
    classifier.py   # luật gắn nhãn TRUNG / KHONG_TRUNG
    postgres_compare.py  # so sánh với pool Postgres (worker), promote vào pool
    review.py       # API duyệt kết quả job + proxy ảnh
    search.py       # API tìm ảnh tải lên trong pool
    main.py         # FastAPI
  frontend/
    index.html      # UI so 1-1 (cũ)
  review-ui/        # UI React: duyệt kết quả + tìm ảnh
  calibrate_dataset.py  # đo trên dataset gán nhãn tay
  test_pipeline.py      # smoke test bằng ảnh tổng hợp
  requirements.txt
```

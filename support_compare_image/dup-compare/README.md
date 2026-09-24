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

1. **Agent** (`agent.py`, chạy trên máy Support): embedding DINOv2 và so sánh với pool 85k ảnh lịch
   sử, cho job `/check` và cho mục **Tìm ảnh** trên web. Chỉ nói chuyện với API Tacahu qua HTTPS.
2. **Trang web** (trong dashboard Tacahu, `frontend/src/pages/DuplicateReviewPage.tsx`,
   `SupportQueuePage.tsx`): duyệt kết quả, tìm ảnh, xem hàng đợi và cho phép máy chạy.
3. **So 1-1** (`frontend/index.html`, `backend/main.py`): công cụ dev, upload 2 ảnh rồi xem từng tín hiệu.

## Luồng

```
Support: /check → Có ──► VPS xếp job vào hàng đợi (PostgreSQL)
Máy Support: chạy agent → hiện mã ──► Support đăng nhập web, Hàng đợi → nhập mã → "Cho phép"
Agent: nhận job (có lease), tải pool (lần đầu, sau đó chỉ phần mới), embedding + so sánh trên
       CPU/GPU của máy, gửi từng lô kết quả ──► VPS thêm cả lô vào pool khi job xong
Support: trang "Duyệt trùng" → chọn ảnh trùng / "Model sai" ──► Telegram xác nhận
```

- Máy chỉ chạy khi người đã cho phép còn **mở web** (web gửi tín hiệu "có mặt" mỗi 20 giây; quá
  90 giây không thấy thì API từ chối agent). **Đăng xuất** thu hồi mọi máy của người đó; token hết
  hạn sau 12 giờ. Việc đang làm dở quay lại hàng đợi (hết lease 3 phút) và máy khác làm tiếp các
  đơn còn lại.
- Agent không có quyền vào database: nó chỉ giữ token của máy, thu hồi được bất cứ lúc nào
  (Hàng đợi → Dừng máy).
- Các order trong cùng lô **không so chéo nhau**; cả lô được thêm vào pool sau khi so xong.
  Mỗi order ghi `review_status`: `pending_review` (model nghi trùng) hoặc `no_match`.

## Cài đặt và chạy agent

Cần `.env.agent` (mẫu: `../.env.agent.example`): `SUPPORT_API_URL` (domain API, không có `/api`),
`SUPPORT_WEB_URL`, `AGENT_NAME`, và `MODEL_VERSION` khớp `model_version` của pool.

### Docker (mọi hệ điều hành; trên macOS chỉ chạy CPU)

```bash
cd support_compare_image
cp .env.agent.example .env.agent      # rồi điền
docker compose up -d --build
docker compose logs -f agent          # xem mã kết nối, tiến độ
docker compose down                   # tắt
```

Code Python `dup-compare/` được mount vào container: sau `git pull` chỉ cần `docker compose restart agent`.
Model Hugging Face và token của máy nằm trong volume (`hf-cache`, `agent-data`).

### Chạy trực tiếp (khuyên dùng trên Mac Apple Silicon để dùng GPU/MPS, hoặc máy có NVIDIA)

```bash
cd support_compare_image
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.compare-runtime.txt
set -a; source .env.agent; set +a
cd dup-compare && python agent.py     # --once: nhận tối đa một việc rồi thoát
```

Thiết bị tự chọn `cuda` → `mps` → `cpu` (đặt `EMBEDDING_DEVICE` để ép). Docker trên macOS không
truyền được GPU vào container.

Lần đầu agent tải model (~350MB) và toàn bộ pool (~85k vector, vài trăm MB); các lần sau chỉ tải
phần mới thêm vào pool.

## Trên web

- **Hàng đợi** (`/support-queue`): máy đang kết nối, job đang chạy (tiến độ, máy nào), job đang chờ,
  yêu cầu tìm ảnh, job gần đây. Nhập mã của agent để cho phép máy; Admin hủy được job đang chờ.
- **Duyệt trùng** (`/duplicate-review`): mỗi thẻ hiện ảnh gốc và top-10 candidate, đều kèm mã đơn.
  **Chọn trùng** ghi `selected_duplicate` (VPS gửi cặp ảnh lên Telegram trong ≤60 giây; **Xác nhận
  trùng** gắn tag Trùng lặp, **Từ chối** đưa đơn vào Không trùng lặp). **Model sai** ghi `ai_wrong`
  (đơn ở lại Chưa kiểm tra cho tới khi gõ `/handle`). Cặp đã gửi Telegram thì không đổi được nữa.
  Phím tắt: J/K chuyển đơn, 1-9/0 chọn ảnh, D chi tiết, X model sai.
- **Tìm ảnh** (cùng trang): tải một ảnh lên, ảnh vào hàng đợi, agent trả 10 ảnh gần nhất kèm mã
  đơn, độ giống, pHash/SSIM và custom configuration. Lịch sử tìm lưu trong trình duyệt.

## Test

```bash
cd support_compare_image/dup-compare && ../../.venv/bin/python -m pytest test_agent.py test_compare_core.py
pytest tests/test_support_worker.py tests/test_support_compare_flow.py   # API (cần Postgres test)
cd frontend && npm test
```

## So sánh 1-1 và calibrate (dev)

```bash
docker compose --profile tools up -d compare        # http://127.0.0.1:8000 (so 1-1)
# hoặc: uvicorn backend.main:app --reload --port 8000
python test_pipeline.py                             # smoke test bằng ảnh tổng hợp
```

`POST /compare` (form-data `old_image`, `new_image`) trả nhãn, tín hiệu và lý do; `GET /health`,
`GET /config` cho biết backend/ngưỡng đang dùng. Nếu không load được DINOv2 thì `main.py` (chỉ
công cụ 1-1) dùng HOG để demo và ghi rõ trong `meta.embedding_backend`; **agent không bao giờ
dùng fallback** vì vector HOG không cùng không gian với pool DINOv2.

Chuyển sang weight fine-tune: đặt `EMBEDDING_MODEL_NAME` trỏ tới thư mục Hugging Face local và
`MODEL_VERSION` mới. Nếu dimension, preprocessing hoặc model space đổi, phải re-embed pool bằng
đúng weight mới; không trộn vector `facebook/dinov2-base` với vector fine-tune trong cùng một pool.

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
| `TOP_K_CANDIDATES` | 10 | số ứng viên được kiểm tra kỹ cho mỗi ảnh mới |
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
  agent.py          # agent trên máy Support: device login, pool, job/search, heartbeat
  backend/
    config.py       # threshold, model (đọc từ biến môi trường)
    embedding.py    # DinoV2Embedder (cuda/mps/cpu) + fallback HOG cho công cụ 1-1
    signals.py      # pHash, SSIM, màu LAB / ΔE
    classifier.py   # luật gắn nhãn TRUNG / KHONG_TRUNG
    compare_core.py # so một ảnh với pool: top-K, tín hiệu, phân loại
    main.py         # FastAPI công cụ 1-1
  frontend/index.html   # UI so 1-1
  test_agent.py, test_compare_core.py, test_pipeline.py
```

Phía server: `app/api/routes/support_worker_api.py` (agent), `support_review_api.py` (web),
`app/application/support_worker.py` (device login, lease, pool, lưu kết quả, đưa lô vào pool).

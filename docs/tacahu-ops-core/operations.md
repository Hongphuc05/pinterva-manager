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
  queue (`celery-general`, `celery-assignment`) và Cloudflare Tunnel. DINO local worker
  không chạy trong production Compose.
- Migration service chạy cả Alembic root và migration riêng của
  `support_compare_image`. Kiểm tra `support_compare_image.comparison_runs` tồn tại trước
  khi bật runner.
- Backup PostgreSQL và private assets trước deploy/rollback. Không dùng `down -v` lên data
  production.
- Sau mỗi thay đổi compose, kiểm tra tất cả thư mục có file ghi runtime đều được bind-mount.
  `private_work_note_assets` được mount vào `/app/private_work_note_assets` và phải có trong
  backup asset; preflight sẽ chặn deploy nếu thư mục host chưa được tạo.
- Nếu build SPA mới, deploy cả `frontend/dist`; code local đã pass build không đồng nghĩa
  website production đã nhận bundle mới.

### Thiết lập routing Bot Telegram cho Designer

1. Chạy migration tới `head` trước khi mở tab **Quản lý Bot Telegram**.
2. Thêm Bot `des-mana` vào group riêng tương ứng với Designer và cấp quyền gửi tin.
3. Lấy `chat_id` group, vào tab quản trị, dán ID đúng dòng Designer rồi bấm **Lưu**.
4. Bấm **Kiểm tra**. Chỉ khi `getChat`/`getChatMember` xác nhận group hợp lệ mới chọn được
   mode **Group chat**.
5. Bấm **Gửi test** để kiểm tra đích thực tế. Nếu không muốn dùng group, đổi mode về **Chat
   riêng**; hệ thống yêu cầu Designer đã link chat riêng qua `/start <link_code>`.
6. Sửa template trong cùng trang nếu cần. Chỉ sửa text và placeholder được hiển thị; dùng
   **Xem preview** trước khi lưu. **Mặc định** xóa override và quay về nội dung seed.

Không gán một group cho hai Designer. Khi group bị xóa, mode group tự chuyển về private nhưng
không tự tạo kết nối chat riêng; mọi thay đổi mapping/mode/template được lưu audit trong
PostgreSQL. Kiểm tra `group_last_error`, log API và Bot API trước khi kết luận worker bị lỗi.

### Chạy thử image comparison bằng order Review

Phase 1 dùng model Hugging Face `facebook/dinov2-base`; chỉ chạy local worker trên máy Support
có đủ `torch/transformers` và kết nối PostgreSQL qua private network/SSH tunnel:

```bash
cd support_compare_image
cp .env.local-worker.example .env.local-worker
# mở SSH tunnel ở một terminal khác, sau đó nạp biến môi trường:
ssh -N -L 15432:127.0.0.1:5432 USER@VPS_HOST
set -a; source .env.local-worker; set +a
pip install -r requirements.txt -r requirements.compare-runtime.txt
python dup-compare/local_worker.py --once
```

Migration `support_compare_image` phải ở `head` (tới `0007_item_review_status`) trước khi bật
`SUPPORT_COMPARE_ENABLED=true`. Cờ này bật lệnh `/check`, `/handle`, nút web và notifier; **không
có job tự động theo lịch** nên không còn `SUPPORT_COMPARE_INTERVAL_SECONDS`. Máy local chạy
`python dup-compare/local_worker.py` liên tục để claim job. `SUPPORT_COMPARE_SCAN_LIMIT` giới hạn
số order mỗi lô; `SUPPORT_COMPARE_BATCH_LIMIT` giới hạn số tin Telegram gửi mỗi lần notifier chạy.

Luồng vận hành một lô (ví dụ 100 order admin vừa crawl về Waiting):

1. Support gõ `/check` (hoặc bấm **Kiểm tra trùng (N)** trên web). Bot báo số order chưa từng được
   so sánh rồi hỏi **Có**/**Không**. Gõ lại `/check` hoặc `/handle` sẽ thay prompt còn chờ trước đó.
2. Bấm **Có** khi giao diện localhost và worker đang chạy: job được queue, worker so sánh cả lô rồi
   thêm cả lô vào pool. Bot báo số order đã so, số nghi trùng, số không thấy trùng và số lỗi.
3. Support mở `http://127.0.0.1:8000/review.html` (chạy `uvicorn backend.main:app` trong
   `support_compare_image/dup-compare` với `.env.local-worker` đã nạp). Với mỗi order nghi trùng:
   **Chọn ảnh này là trùng** (Telegram gửi cặp ảnh kèm mã đơn trong ≤60 giây) hoặc **Model sai**.
4. Trên Telegram: **Xác nhận trùng** gắn tag Trùng lặp và chuyển order sang tab Trùng lặp;
   **Từ chối** chuyển sang Không trùng lặp.
5. `/handle` đếm các order đã so mà không trùng (không thấy trùng hoặc **Model sai**, không còn
   review đang mở), hỏi xác nhận rồi chuyển chúng sang Không trùng lặp. `/help` liệt kê lệnh.

Mỗi order chỉ được so sánh một lần; order đã có kết quả không được đưa vào `/check` lần sau. Order
lỗi được thử lại. Mọi ảnh, tin nhắn và màn hình đều kèm mã đơn. Localhost chỉ nhận request
same-origin tới `127.0.0.1`/`localhost` và không bao giờ ghi vào `public.orders`.

Weight fine-tune ở phase 2 phải có `MODEL_VERSION` riêng. Nếu đổi dimension, preprocessing hoặc
model space, re-embed toàn bộ baseline trước khi so sánh; không trộn vector DINOv2 gốc với vector
fine-tune.

## Kiểm tra tối thiểu trước bàn giao

```bash
.venv/bin/alembic heads
.venv/bin/ruff check app tests
.venv/bin/pytest -q tests/test_order_work_notes_api.py
cd frontend && npm test && npm run build
```

Sau khi thêm Telegram management, chạy thêm các test API/service Telegram liên quan và xác nhận
`telegram_message_templates`, `telegram_configuration_audits` đã có sau migration; kiểm tra thêm
hai template audience `support` dùng cho candidate duplicate và preview trong Admin. DB-backed
pytest phải chạy tuần tự trên database test riêng.

Chạy DB-backed pytest tuần tự. Không chạy parallel trên cùng `pinterval_test` vì có thể
deadlock/che lỗi concurrency.

## Monitoring cần xem

- API health, error/latency command và HTTP 409 conflict.
- Celery general/assignment/beat; dead letter và external write evidence.
- status-sync cycle, crawl cycle, private asset volume và database backup.
- Cloudflare tunnel/HTTPS ở production.

### Status sync: heartbeat và tác vụ treo

`GET /api/orders/sync-status` chỉ đọc `PlatformSyncState`; polling giao diện không được
tự ý đổi `is_running` hay ghi lỗi timeout. Mỗi status-sync worker ghi:

- `worker_task_id`: task Celery để truy vết log/worker;
- `run_token`: lease của lần chạy, ngăn worker cũ ghi đè lần chạy mới;
- `last_heartbeat_at`: heartbeat định kỳ, kể cả lúc đang chờ HTTP Printerval;
- `progress`: phase, số đơn đã xử lý/cập nhật/lỗi và mã đơn hiện tại nếu có.

Watchdog Celery chạy mỗi phút và chỉ đánh dấu `SyncJob`/`PlatformSyncState` là `failed` khi heartbeat quá hạn theo
`STATUS_SYNC_HEARTBEAT_STALE_SECONDS` (mặc định 180 giây). Một full sweep lâu hơn 15 phút
nhưng vẫn có heartbeat hợp lệ sẽ tiếp tục chạy bình thường. Nếu cần dừng cưỡng bức, admin
dùng endpoint reset; sau đó kiểm tra `worker_task_id`, heartbeat cuối và log Celery trước
khi chạy lại.

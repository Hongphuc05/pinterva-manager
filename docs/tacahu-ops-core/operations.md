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

### Image comparison: agent trên máy Support

Phase 1 dùng model Hugging Face `facebook/dinov2-base`. VPS không chạy DINO: máy Support chạy
**agent** (`support_compare_image/dup-compare/agent.py`, Docker hoặc trực tiếp) và chỉ nói chuyện
với API bằng HTTPS, không có SSH tunnel hay quyền vào database. Cài đặt và chạy: xem
`support_compare_image/dup-compare/README.md`.

Migration `support_compare_image` phải ở `head` (tới `0010_review_access_job_orders`) trước khi bật
`SUPPORT_COMPARE_ENABLED=true`. Cờ này bật lệnh `/check`, `/handle`, nút web và notifier; **không
có job tự động theo lịch**. `SUPPORT_COMPARE_BATCH_LIMIT` giới hạn số tin Telegram gửi mỗi lần
notifier chạy.

Luồng vận hành một lô (ví dụ 100 order admin vừa crawl về Waiting):

**Thông báo lô mới (trước bước 1):** mỗi lần Admin quét đơn (Quét Đơn Print) mà có đơn mới ở Waiting
   (`added_waiting` > 0), bot gửi **một tin** cho các Support đã liên kết Telegram của platform: số
   đơn mới, số đơn chưa kiểm tra và nhắc gõ `/check`, kèm nút **Claim**. Support nào bấm trước thì
   nhận lô: nút biến mất ở mọi tin và cả nhóm nhận thêm "Support A đã nhận lô N đơn mới". Claim chỉ
   là phối hợp, không tự chạy `/check`. Lỗi Telegram không làm hỏng lượt quét.

1. Support gõ `/check` (hoặc bấm **Kiểm tra trùng (N)** trên web). Bot báo số order chưa từng được
   so sánh và chưa nằm trong job nào rồi hỏi **Có**/**Không**. Gõ lại `/check` hoặc `/handle` sẽ
   thay prompt còn chờ trước đó.
2. Bấm **Có**: tạo **một job** với danh sách đơn được chốt lúc đó (mỗi lần bấm Có là một job; nhiều
   job có thể cùng chờ, mỗi đơn chỉ thuộc một job). Xem ở trang **Hàng đợi** trên web: số job đang
   đợi, bấm vào job để xem các đơn còn chờ kiểm tra.
3. Chỉ cần **một máy** chạy Docker và một Support đăng nhập trên máy đó bấm **Có** ở câu hỏi "Cho phép
   dùng GPU/CPU của máy này để chạy hàng đợi?" (một lần). Agent giữ token (volume cache) nên sau khi
   khởi động lại vẫn tự online, kể cả khi không ai mở web. Máy chạy job của **mọi** tài khoản Support
   trong platform; các tài khoản khác không cần Docker, chỉ xem trang **Hàng đợi** để biết máy nào đang
   chạy, của tài khoản nào và tiến độ. Việc dở được máy khác nhận tiếp khi hết lease 3 phút. Chỉ máy
   chủ bấm **Dừng máy này** được; token hết hạn sau 30 ngày thì bấm **Có** lại.
4. Agent so sánh cả lô rồi VPS thêm cả lô vào pool. Bot báo số order đã so, số nghi trùng, số không
   thấy trùng và số lỗi.
5. Support mở khu vực ẩn **Quản lý trùng lặp** (`/duplicate-review`, không có trong menu; vào bằng Alt+Shift+D hoặc bấm nhanh 5 lần vào logo; mật khẩu riêng,
   lần đầu mở thì đặt, đổi ở mục Cài đặt; khóa 10 phút sau 5 lần nhập sai). Với mỗi order nghi trùng:
   **Chọn trùng** hoặc **Model sai**. Đơn đã chọn vào tab **1. Chờ xử lý** của lô; Support bấm
   **Gửi cho Support** hoặc chọn một Admin đã liên kết Telegram rồi **Gửi cho Admin** để gửi cả loạt
   cặp ảnh. Quên mật khẩu: xóa dòng của platform trong `support_compare_image.review_access` để đặt
   lại ở lần mở sau.
6. Trên Telegram: **Xác nhận trùng** chỉ đánh dấu đã verify, **Từ chối** đưa đơn sang tab **2. Không
   trùng lặp**; chưa có tag nào đổi. Cuối mỗi tab có nút chuyển toàn bộ sang Trùng lặp / Không trùng
   lặp. Tab **3. Gắn link** nhận các đơn đã chuyển Trùng lặp để Support dán link vào note làm việc.
7. `/handle` đếm các order đã so mà không trùng (không thấy trùng hoặc **Model sai**, không còn
   review đang mở), hỏi xác nhận rồi chuyển chúng sang Không trùng lặp. `/help` liệt kê lệnh.

Mỗi order chỉ được so sánh một lần; order đã có kết quả không được đưa vào `/check` lần sau. Order
lỗi được thử lại. Mọi ảnh, tin nhắn và màn hình đều kèm mã đơn. Hàng đợi và khu vực Quản lý trùng lặp chỉ dành
cho role Support (Admin không dùng), giới hạn theo platform của tài khoản và không bao giờ ghi vào
`public.orders`. Support hủy job đang chờ ở mục Lịch sử job của khu vực ẩn.

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

### Ghi lên Printerval thất bại: thử lại và báo Admin

Mọi thao tác **ghi** lên Printerval (đẩy Review/trạng thái và note khi designer nộp bài hay Admin
duyệt/từ chối Fix, đổi Designer/trạng thái qua `PrintervalAssignmentRequest`, giao designer) đều báo
Admin qua Telegram khi thất bại hẳn, kèm việc cần làm tay trên Printerval (mẫu `admin_system_alert`).

- Đẩy Review (`sync_order_review_to_printerval_task`): lỗi tạm thời (Printerval chậm, mạng, 5xx/429)
  được thử lại sau 1, 3 rồi 7 phút; cookie bị từ chối (`AUTH`) thì báo ngay. Hết lượt thử thì ghi
  `dead_letters` (`source=printerval.review_sync`, có `recovery_action`) rồi báo Admin. Không còn
  fallback Playwright cho job này (không chạy được trong container production).
- `login()` bằng cookie: hết thời gian chờ được báo là `TRANSIENT_NETWORK`, không còn bị báo nhầm là
  "cookie hết hạn" (sự cố DJ4141056 ngày 14/10).
- Chỉ tra locale (`local_code`) một lần ở đúng queue hiện tại của đơn; tra lỗi thì vẫn ghi với
  locale mặc định thay vì bỏ cả lượt.
- Các request **đọc** (crawl, đồng bộ status) không báo Telegram: lượt sau tự chạy lại.
- Danh sách designer của đội đọc từ `GET /outsource/pod/member/options` trên printerval.com bằng phiên
  outsource (email, full_name, status, team). Từ 15/10/2026 Printerval khoá API cũ
  `central.api.printerval.com/designer_outsource` (trả `{"error":"token required!"}`) và báo các lượt
  gọi kiểu cũ là client lạ; không dùng lại URL đó. Lỗi đọc danh sách được nhớ trong một lượt sync,
  không gọi lại cho mỗi trang.

## Monitoring cần xem

- API health, error/latency command và HTTP 409 conflict.
- Celery general/assignment/beat; dead letter và external write evidence.
- status-sync cycle, crawl cycle, private asset volume và database backup.
- Cloudflare tunnel/HTTPS ở production.

### Status sync: lịch 3 tầng

Celery Beat chạy theo `CELERY_TIMEZONE` (mặc định `Asia/Ho_Chi_Minh`). Mọi tầng đều chỉ
đọc từ Printerval và dùng chung lease `PlatformSyncState`, nên không chạy chồng nhau trên
một platform (tầng đến sau bỏ lượt).

| Tầng | Lịch | Đơn được sync | Cách đọc |
|---|---|---|---|
| Đang làm | mỗi `STATUS_SYNC_INTERVAL_SECONDS` (300s) | đơn trong queue `doing` + `fix` | danh sách 2 queue |
| Gần đây | phút :02 và :32 | đơn tạo trong 7 ngày (`RECENT_SYNC_WINDOW`) | danh sách các queue `doing/fix/review/confirm/done` lọc `date_from` |
| Hằng đêm | 02:00 | đơn tạo trong 60 ngày (`NIGHTLY_SYNC_WINDOW`) | như tầng gần đây |

Hai tầng sau đọc danh sách queue (100 đơn mỗi request, `date_from` lùi thêm 1 ngày làm
biên), rồi áp dụng từng dòng qua cùng luật với sync đơn được chọn. Chỉ đơn không có trong
danh sách (bị huỷ, chưa gán) mới tra riêng từng đơn. Nếu đọc danh sách lỗi sau 3 lần thử
thì cả lượt `failed`; vắng mặt trong danh sách không bao giờ bị coi là huỷ. Đơn tạo quá
60 ngày không còn được sync tự động — Admin vẫn đồng bộ được qua nút đồng bộ đơn được
chọn. Số liệu chọn khung (14/10/2026): không đơn nào quay lại Fix sau 12 ngày kể từ lúc
tạo, hay sau 7 ngày kể từ lúc vào Review/Done.

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

Endpoint `design-job/find` của Printerval có lúc mất 10–30 giây hoặc hơn mới trả lời. Các
client sync chạy nền (3 tầng ở trên, job "Đồng bộ" toàn bộ) dùng timeout 60
giây và đọc lại mỗi trang queue tối đa 3 lần khi gặp lỗi `TRANSIENT_NETWORK` (nghỉ 3s, 6s,
có jitter). Các đường gọi Printerval trong request web (Quét Đơn Print, đồng bộ đơn được
chọn) vẫn giữ timeout 30 giây. Một deploy giữa lúc sync đang chạy sẽ cắt ngang lượt đó
(Docker chỉ cho worker 10 giây để dừng); watchdog ở trên dọn lease, lượt sau chạy lại.

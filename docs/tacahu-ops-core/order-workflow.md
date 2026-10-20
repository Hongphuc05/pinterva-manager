# Luồng đơn hàng hiện hành

## Role và domain

- `admin`: quản trị platform, user, phân loại/phân công, state, Fix, tài chính và audit.
- `support`: gắn tag trùng/không trùng cho đơn còn `Waiting` và xem/duyệt danh sách bài nộp;
  không có quyền Admin tổng quát. Support thấy mọi đơn `Waiting` và `Doing` của platform, chia
  thành bốn tab không chồng nhau (xem [architecture.md](architecture.md)); đơn Admin đã chia cho
  designer mà chưa gắn tag nằm ở tab `Đang làm` và chỉ xem. Đơn designer đã nộp bài không còn hiện
  với Support.
- `designer`: chỉ làm assignment standard của chính mình.
- `designer-trello`: làm duplicate domain trên board cộng tác; đây là ngoại lệ visibility có chủ đích.

Mỗi order thuộc một `platform_id`. Mọi query/command order phải bị scope theo platform.

## State canonical

State lưu hiện tại chỉ gồm `OPEN`, `WAITING`, `IN_PROGRESS`, `QC_PENDING`, `REVISION`,
`DONE`, `CANCELLED`, `EXCEPTION`.

Các state cũ/ngoài (`DISCOVERED`, `ASSIGNED`, `RESULT_SUBMITTED`, `FIX`, `SKIPPED`, ...)
được normalize khi đọc để tương thích dữ liệu cũ, không phải state canonical mới.

```mermaid
stateDiagram-v2
    [*] --> OPEN: crawl/import
    OPEN --> WAITING: sẵn sàng phân công
    OPEN --> IN_PROGRESS: assignment/duplicate allocation
    WAITING --> IN_PROGRESS: nhận việc
    IN_PROGRESS --> QC_PENDING: nộp kết quả
    QC_PENDING --> DONE: platform xác nhận done hoặc Admin action hợp lệ
    QC_PENDING --> REVISION: platform trả Fix
    REVISION --> IN_PROGRESS: Admin duyệt Fix, Designer bắt đầu sửa
    REVISION --> QC_PENDING: Admin từ chối Fix về Review
    QC_PENDING --> IN_PROGRESS: nộp lại/làm lại
    DONE --> REVISION: Fix muộn từ platform
    state EXCEPTION
    OPEN --> EXCEPTION
    WAITING --> EXCEPTION
    IN_PROGRESS --> EXCEPTION
    QC_PENDING --> EXCEPTION
    REVISION --> EXCEPTION
```

`EXCEPTION` chỉ được rời bằng recovery tường minh của operator; state-machine cho phép
transition nhưng application layer không được tự động recover.

## Luồng chuẩn

1. **Crawl/refresh**: worker hoặc Admin lấy job/platform detail, asset, gallery, custom
   configuration và metadata. Import tạo/mapping order về `OPEN` hoặc `WAITING` theo
   command hiện hành; refresh metadata không tự đổi state.
2. **Phân loại**: Admin/Support đặt `work_domain` là `standard` hoặc `duplicate` và cập
   nhật duplicate check status. Support chỉ được thực hiện bước này khi order còn ở
   `Waiting`; chỉ quyết định `duplicate` mới ghi người + thời điểm, timeline và công
   Support. Quyết định `non_duplicate` không tạo timeline/công Support. Standard
   được Admin phân công; duplicate vào Duplicate Board. Đơn chưa gắn tag mà đã được chia
   chuyển sang tab `Đang làm` của Support (chỉ xem).
3. **Làm việc**: assignment approved hoặc Designer Trello nhận thẻ đưa order vào
   `IN_PROGRESS`. Assignment/status Printerval là write async, serialized trên queue
   `assignment`.
4. **Nộp bài**: Designer gửi link **và 1–3 ảnh mockup (bắt buộc)**, tạo `ResultVersion`, state
   sang `QC_PENDING`. Worker đẩy sang Printerval theo thứ tự link → ảnh vào cột Design → trạng
   thái Review, và chỉ thực hiện khi order vẫn ở state mong đợi. Chi tiết ở "Chuyển đơn sang
   Review trên Printerval" bên dưới.
   **Nộp lại / đổi link** (Designer standard, không áp dụng cho Trello): đơn ở
   `QC_PENDING` hoặc `DONE` nội bộ vẫn nộp lại được cho tới khi `printerval_status` là
   `confirm`/`done` (sau đó trả 404). Link mới tạo `ResultVersion` kế tiếp (bản cũ giữ làm
   lịch sử), `ApprovalRequest` QC `pending` cũ chuyển `superseded`, đơn về `QC_PENDING`
   chờ QC lại, link mới được đẩy sang Printerval. Đơn Fix cũng dùng link Designer gửi;
   để trống thì giữ link bản nộp đầu. Lý do: Printerval đã có khung chat riêng nên link
   không còn là kênh ghi chú yêu cầu sửa.
5. **Đồng bộ status**: Celery Beat đọc status platform. `Done` đưa nội bộ sang `DONE`;
   `Fix` đưa sang `REVISION` và tăng `fix_return_count`. Tacahu **không đọc** `note_outsource`
   từ Printerval về nữa (nó chỉ giữ link bài Tacahu đã đẩy lên); QC ghi yêu cầu sửa vào khung
   chat của đơn trên Printerval — xem "Chat Printerval" bên dưới.
6. **Fix**: Fix trước hết nằm ở Admin. Admin duyệt sẽ release hướng dẫn riêng cho
   Designer, Designer sửa và nộp lại Review (lại kèm 1–3 ảnh mockup mới). Admin từ chối Fix
   thì trả về `QC_PENDING` cùng ghi chú phản hồi cho platform. Không expose trực tiếp upstream
   `note_outsource` cho Designer.

## Chuyển đơn sang Review trên Printerval (luật Printerval từ 19/10/2026)

Printerval chỉ cho một job sang **Review** (kể cả job Fix nộp lại) khi có đủ:

1. link design trong `Note outsource`;
2. ít nhất một ảnh mockup/design trong **cột Design** của job trên tool Printerval.

Riêng job đang **Fix** còn phải: đọc hết tin của Printerval trong chat (còn tin chưa đọc thì
Printerval giữ job ở Fix), và nếu lý do Fix là **"Đổi template"** thì gửi kèm xác nhận
`template_confirm` = `agree`, hoặc `disagree` + `template_confirm_note` (giải thích, ≤ 500 ký tự).
Thiếu điều kiện nào Printerval từ chối PATCH `design-job/update` (thiếu xác nhận template thì trả
`code: template_confirm` kèm `outsource_fix_template`).

Tacahu đáp ứng như sau:

| Điều kiện | Tacahu làm |
|---|---|
| Link trong Note outsource | Designer dán link khi nộp; worker ghi lên Printerval (một chiều, không đọc ngược). |
| Ảnh trong cột Design | Designer **bắt buộc** gắn 1–3 ảnh PNG/JPEG (≤ 10 MB/ảnh) ở ô nộp bài; ảnh được tải trước (staged), lần nộp gắn chúng vào (`result_images`). Worker tải từng ảnh chưa có trên Printerval: `POST /printerval-central/upload` (lấy URL) rồi `POST /service/pod/design-job/store-image` (gắn vào job, ảnh đầu là primary khi job chưa có ảnh). Mỗi ảnh ghi `pushed_at` ngay khi Printerval nhận, nên thử lại không tải trùng; Review chỉ gửi khi mọi ảnh đã lên. |
| Đọc hết chat (job Fix) | Ngay trước khi đổi trạng thái của một job đang Fix, worker đọc chat của job (Printerval tính là đã đọc cho cả team). |
| Xác nhận "Đổi template" | Không tự quyết. Printerval đòi xác nhận → không thử lại, ghi `dead_letters` (`kind=template_confirm`) và toast Admin; trang chi tiết đơn của Admin hiện khung **Xác nhận / Không đúng + lý do**. Admin trả lời (`POST /orders/{id}/printerval-template-confirm`, idempotent, ghi `WorkflowEvent` `CONFIRM_FIX_TEMPLATE`) → đơn về `QC_PENDING` và worker gửi lại Review kèm xác nhận; thành công thì yêu cầu được đánh dấu đã xử lý. |

**Không coi lệnh đẩy chưa tới là Fix mới.** Tacahu chuyển đơn sang Review nội bộ ngay rồi mới đẩy
lên Printerval; trong lúc đó Printerval vẫn báo Fix. Trong **30 phút** sau khi đơn sang Review
(hoặc khi đơn đang chờ Admin xác nhận template), trạng thái `fix` từ Printerval chỉ được tính là
Fix mới nếu chat có tin **"Mở Fix"** (`fix_open`) gửi sau thời điểm đó; quá 30 phút thì lấy Fix của
Printerval như cũ. Trước đây việc này đưa bài nộp lại về Fix giả (20/52 lần nộp lại ngày 19/10).

**Không im lặng khi thất bại.** Lệnh đẩy Review thử lại sau 1, 3, 7 phút; Printerval từ chối thì
toast kèm đúng lý do Printerval trả (HTTP code + message). Lệnh đã từng lỗi mà lần thử sau thấy đơn
đã đổi trạng thái cũng phải toast (trước đây nó tự bỏ qua).

Ngoài phạm vi: Admin đổi trạng thái tay sang Review không bắt buộc ảnh (Printerval vẫn có thể từ
chối nếu job chưa có ảnh — toast sẽ báo).

## Duplicate Board

Duplicate là domain xử lý cộng tác, không phải state riêng. Designer Trello có thể thấy
card duplicate của cùng platform và link kết quả mới nhất trên board; điều này **không**
mở quyền tương tự cho Support, Designer standard hay toàn bộ order detail/source.

## Thiếu template và Note làm việc

- Designer có thể flag thiếu temp. Order/assignment vào trạng thái chờ Admin xử lý;
  Admin dùng command resolve để thêm hướng dẫn/temp và đưa lại Doing.
- `Note làm việc` là cuộc trao đổi chung append-only giữa Admin và designer được phép.
  Có thể dán ảnh raster; file được lưu private và download qua endpoint có auth.
- Khi người còn lại thêm note, lần mở note tiếp theo trả cờ unread để UI hiện chấm xanh.
  Việc đọc ghi cursor theo từng `(order, user)`.
- `note_outsource` trên Tacahu chỉ là link bài đã nộp: Tacahu ghi lên Printerval một chiều (nộp lần đầu
  và mỗi lần Designer cập nhật link), không đọc ngược về; không dùng nó làm chat nội bộ.

## Chat Printerval (chỉ Admin, chỉ đọc)

QC của Printerval ghi yêu cầu Fix và nhận xét vào khung chat từng đơn. Tacahu đọc chat theo 3 cách,
đều chỉ cho Admin và không bao giờ đổi state đơn:

1. **Mở đơn**: `GET /orders/{id}/printerval-chat` lấy cả hội thoại ngay lúc đó (không lưu DB).
2. **Toast tin mới**: web Admin hỏi `GET /printerval-chat/unread` mỗi 30 giây khi tab đang xem; server
   hỏi Printerval 1 lần/phút/platform (danh sách unread của chính Printerval, không đánh dấu đã đọc) và
   cache. Mỗi đơn có tin mới hiện một toast.
3. **Đơn đổi status sang Fix/Confirm/Done**: job đồng bộ trạng thái đẩy task `capture_order_chat`, lưu
   tin mới của đơn vào `external_observations` (`source=printerval.chat`, tăng dần theo
   `last_message_id`). Đây là lưới an toàn cho tin đã được ai đó đọc trên Printerval nên không còn trong
   danh sách unread. Với Fix, task đọc chat **rồi** gửi thẻ Telegram cho Admin; đọc chat lỗi thì thẻ ghi
   "chưa đọc được khung chat" và việc đọc được thử lại sau 2 và 5 phút.

**Nội dung Fix** = toàn bộ tin của QC (không tính tin của mình) thuộc lượt Fix mới nhất trong các
snapshot, cũ trước mới sau, mỗi tin một dòng, kèm link ảnh (`fix_chat_text`). Dùng ở:

- Thẻ Fix Telegram: trích nguyên văn (tối đa 3000 ký tự); dài quá 1024 ký tự thì gửi tin chữ thay ảnh.
- Chi tiết đơn (Admin): `fix_reason` là nội dung này; dòng trong danh sách đơn chỉ hiện tin QC mới nhất.
- Modal duyệt Fix trên web: hiện nội dung này cho Admin (`GET /orders/{id}/fix-chat`; chưa có snapshot
  thì đọc chat 1 lần ngay lúc đó, `read_fix_chat_text`).

Duyệt Fix (web modal, hoặc Telegram "Có, soạn Ghi chú Admin" / "Không, dùng nguyên văn nội dung chat"):
Admin nhập Ghi chú cho Designer thì des nhận đúng ghi chú đó; để trống thì copy nội dung Fix **không kèm
link ảnh** (link trỏ host Printerval) vào `designer_note`. Không có nội dung chat thì web trả 422, Telegram
báo bấm lại hoặc soạn ghi chú. Duyệt Fix không đọc hay ghi `note_outsource` (đó là link Tacahu đẩy lên).

Đọc tin nhắn làm Printerval đánh dấu **đã đọc cho cả team**. Designer không thấy chat; muốn designer biết,
Admin tự ghi vào Note làm việc. `ORDER_CHAT_ENABLED=false` tắt cách 2 và 3 (thẻ Fix Telegram vẫn gửi như cũ,
chỉ không kèm lý do); mở chat của một đơn luôn dùng được.

## Điều không được giả định

- Không coi một request enqueue là external write thành công; phải kiểm tra state/evidence.
- Không để job async cũ ghi đè Fix/Review mới hơn.
- Không coi link Drive hoặc chat là approval bền vững; state/event/backend mới là authority.

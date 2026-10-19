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
4. **Nộp bài**: Designer tạo `ResultVersion`, state sang `QC_PENDING`. Với flow hiện
   hành, worker đẩy Review/link/note sang Printerval và chỉ thực hiện khi order vẫn ở
   revision/state mong đợi.
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
   Designer, Designer sửa và nộp lại Review. Admin từ chối Fix thì trả về `QC_PENDING`
   cùng ghi chú phản hồi cho platform. Không expose trực tiếp upstream `note_outsource`
   cho Designer.

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
   danh sách unread. Với Fix, task đọc chat **rồi** gửi thẻ Telegram cho Admin (lý do Fix lấy từ chat; đọc
   chat lỗi thì thẻ ghi "xem trong khung chat" và việc đọc được thử lại sau 2 và 5 phút).

Đọc tin nhắn làm Printerval đánh dấu **đã đọc cho cả team**. Designer không thấy chat; muốn designer biết,
Admin tự ghi vào Note làm việc. `ORDER_CHAT_ENABLED=false` tắt cách 2 và 3 (thẻ Fix Telegram vẫn gửi như cũ,
chỉ không kèm lý do); mở chat của một đơn luôn dùng được.

## Điều không được giả định

- Không coi một request enqueue là external write thành công; phải kiểm tra state/evidence.
- Không để job async cũ ghi đè Fix/Review mới hơn.
- Không coi link Drive hoặc chat là approval bền vững; state/event/backend mới là authority.

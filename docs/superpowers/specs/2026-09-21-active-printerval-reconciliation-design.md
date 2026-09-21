# Active Printerval reconciliation

## Mục tiêu

Giảm chi phí đồng bộ trạng thái từ `O(toàn bộ orders trong DB)` về `O(queue active
trên Printerval)`. Queue nguồn dùng hai filter Printerval độc lập: `Doing` và `Fix`.
Luồng chỉ đọc từ Printerval, không ghi ngược trạng thái.

## Hai phạm vi đồng bộ

1. Celery Beat mỗi 5 phút và nút Topbar: crawl riêng feed `doing` rồi `fix`.
   `waiting` chỉ được Admin crawl thủ công để thêm đơn mới. Source `doing`/`fix`
   chưa từng theo dõi được đếm là skipped, không kéo backlog cũ.
2. Nút màu từng tab: snapshot order ID của tab Tacahu, tìm các ID đó trên Printerval
   và chỉ reconcile chúng. Không import order mới hay chạm order ngoài snapshot.

## Quy tắc reconcile

- Observation `fix` chuyển order sang `REVISION`, ghi audit `REQUEST_FIX`, tăng
  `fix_return_count`, giữ nguyên `is_paid`.
- Order `DONE` có `is_paid=true` nhận `fix` vẫn chuyển `REVISION`; khi Designer nộp
  bản Fix, flow nội bộ hiện hữu đưa nó thẳng `DONE`.
- Observation `done` không tự đưa Review sang Done; thanh toán là owner của Done.
- Feed active không chứa review/done, nên absence không được suy luận là cancel,
  done, review, hoặc thay đổi internal state.
- Luồng nội bộ nộp bài, thiếu template, duyệt/từ chối Fix và cập nhật result không
  được thay đổi bởi feature này.

## An toàn và quan sát

- Không fetch full detail cho mọi row trong feed active; chỉ fetch detail khi một
  tracked order chuyển/vẫn ở Fix để lấy note. Kết quả job phải có
  checked/added/updated/skipped_untracked/failed (`added` luôn bằng 0 ở flow này).
- Transition dùng cùng logic audit/Fix notification đã có. Mỗi external observation
  chỉ thay đổi version/timestamp khi giá trị thực sự đổi.
- Job scheduler dùng đúng cùng service với Topbar, có PlatformSyncState để chống
  overlap và ghi last_result/error.

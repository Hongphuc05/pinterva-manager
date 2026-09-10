# Kế hoạch: domain Đơn trùng lặp và Kanban Designer Trello

## Global constraints

- `work_domain` chỉ là `standard` hoặc `duplicate`; default là `standard`.
- Domain duplicate không được có assignment active tới Designer thường.
- Kéo thả chỉ thay ownership nội bộ, không đổi state hoặc gọi Printerval.
- Backend là nơi xác thực role, platform và quyền nhận/thả thẻ.
- Admin có toàn quyền board; Designer Trello chỉ claim/release thẻ của mình.

## Task 1 — Model, migration và role

**Consumes:** bảng `users`, `orders`, migration head hiện tại.

**Produces:** role `designer-trello`, cột `orders.work_domain`, migration nâng
constraint role, user API chấp nhận và tạo đúng role/platform.

1. Bổ sung hằng số role/domain dùng chung.
2. Viết Alembic migration thêm `work_domain` không null/default và sửa check
constraint `users.role`.
3. Cập nhật User API và các query role-aware.
4. Viết test migration/user creation.

## Task 2 — Business command và API board

**Consumes:** Order, Assignment, WorkflowEvent, active platform/user.

**Produces:** `duplicate_board.py`, `/duplicate-board`, `/duplicate-board/move`,
`/orders/duplicate-domain`.

1. Viết read model có cột unassigned + user `designer-trello` active.
2. Viết command chuyển domain, cancel assignment active và audit.
3. Viết command move có lock, kiểm tra platform/role/policy và audit.
4. Register router; cập nhật query visibility để `designer-trello` chỉ xem
domain duplicate.
5. Test authorization, platform scope, conversion, move và concurrent-safe
reassignment behavior.

## Task 3 — Admin assignment UX

**Consumes:** bulk selection OrdersListPage và `/orders/duplicate-domain`.

**Produces:** nút đưa/chuyển khỏi domain duplicate cùng feedback, không lẫn với
phân công Designer/Printerval.

1. Thêm action chỉ hiện cho admin khi có selection.
2. Reload cached order list sau success và hiển thị toast/error.
3. Test TypeScript build và API action contract.

## Task 4 — Trello board UX và routing

**Consumes:** `GET /duplicate-board`, move endpoint, current Auth/Sidebar.

**Produces:** `DuplicateBoardPage`, route `/kanban`, role-aware sidebar/routing.

1. Vẽ cột cuộn ngang/card/drop-zone bằng native HTML5 drag and drop, không thêm
dependency nặng.
2. Phân biệt click mở order với thao tác drag; show loading/error/drop feedback.
3. Admin và Designer Trello đều vào board; role khác không có nav entry.
4. Cập nhật UsersPage để tạo/hiển thị nhãn role mới.
5. Build frontend và test tương tác cơ bản.

## Task 5 — Verification và tài liệu vận hành

**Consumes:** toàn bộ thay đổi branch.

**Produces:** test pass, Docker local rebuild, RUNME có luồng test ngắn.

1. `ruff`, compile, targeted pytest, full pytest nếu môi trường backup client
tương thích.
2. `npm --prefix frontend run build`.
3. `docker compose -f compose.local.yaml up --build -d` và `/api/health`.
4. Review diff theo spec, ghi kết quả và commit theo task.

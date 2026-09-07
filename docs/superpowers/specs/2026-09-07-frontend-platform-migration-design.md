# Frontend Platform Migration — Design

**Sub-project 2/6** của chuỗi "web trung gian thay Printerval". Thay Jinja2+HTMX+Alpine
(Phase 4) bằng React + TypeScript + Vite + Tailwind CSS, theo quyết định người dùng
2026-09-07 (claude.md §4 đã cập nhật). Đây là nền tảng bắt buộc trước khi build
allocation board (sub-project 3) — không giữ song song 2 bộ UI.

**Phân loại brainstorming: architectural** (subsystem mới hoàn toàn — build pipeline,
routing client-side, tách hẳn JSON API khỏi HTML) — quyết định theo phán đoán của
controller, không dừng hỏi user (theo chỉ đạo "chạy liên tục" của người dùng).

## 1. Phạm vi

Đạt lại đúng chức năng Phase 4 đã có (login/logout, danh sách đơn có filter, chi tiết
đơn + lịch sử, Refresh crawl, đăng nhập Printerval qua web) trên React, KHÔNG thêm tính
năng mới — allocation board/kanban/QC là các sub-project sau. Xoá hoàn toàn
`app/api/routes/web.py` và `app/api/templates/` sau khi React đạt parity.

## 2. Kiến trúc

```
frontend/                    # dự án Vite riêng, KHÔNG phải Artifact — npm deps thật
  src/
    api/client.ts            # fetch wrapper, credentials: 'same-origin'
    auth/AuthContext.tsx     # session state qua GET /api/me
    pages/LoginPage.tsx
    pages/OrdersListPage.tsx
    pages/OrderDetailPage.tsx
    pages/PrintervalLoginPage.tsx
    App.tsx                  # react-router routes + ProtectedRoute
    main.tsx
  index.html
  vite.config.ts             # dev proxy /api -> http://localhost:8000
  tailwind.config.js
  package.json
app/api/routes/orders_api.py # JSON API mới (thay web.py's HTML routes)
app/api/main.py              # thêm StaticFiles mount cho frontend/dist (SPA fallback)
```

- **Auth không đổi:** session cookie httponly/samesite=lax, `/api/login`,
  `/api/logout`, `/api/me` (Phase 1, JSON, không sửa). SPA cùng origin với backend
  (dev: Vite proxy `/api`; prod: FastAPI serve luôn `frontend/dist`) → không cần CORS,
  không đổi sang JWT/OAuth (giữ đúng claude.md §4/§14).
- **Business logic không đổi:** JSON API mới chỉ là lớp mỏng gọi lại
  `order_queries.py`/`crawl.py`/`playwright_support` đã có — domain/application layer
  không sửa. React không tự quyết định quyền (admin/designer) — chỉ hiển thị theo dữ
  liệu server trả về, mọi enforcement vẫn ở backend (claude.md §4/§10).
- **State management:** `fetch` + React hooks (`useState`/`useEffect`) thuần, KHÔNG
  thêm React Query/Redux — 3 trang, mỗi trang gọi API 1 lần, không cần cache phức tạp
  (YAGNI). Thêm state library sau nếu allocation board (sub-project 3) thực sự cần.
- **Router:** `react-router-dom` (thư viện chuẩn, không có lựa chọn "0 dependency" hợp
  lý cho client-side routing nhiều trang).
- **Test:** Vitest + React Testing Library (bộ chuẩn đi kèm Vite), 1 test/trang tối
  thiểu (render + gọi API giả qua `vi.fn()`/mock fetch).

## 3. JSON API mới (thay thế HTML routes trong `web.py`)

```
GET  /api/orders?status=&batch_id=&designer_id=   -> {orders: [...]}
GET  /api/orders/{id}                             -> {order: {...}, history: [...]}
POST /api/orders/refresh                          -> {summary: {...}, flash: str} (admin only, 403 khác)
GET  /api/printerval-login/status                 -> {session_open: bool}
POST /api/printerval-login/start                  -> {ok: bool}
POST /api/printerval-login/done                   -> {ok: bool}
```

Mỗi field trong response map trực tiếp từ cột `Order` (đã có đủ từ sub-project 1:
`product_name`, `thumbnail_url`, `sku`, `deadline_at_ext`, v.v.) — serialize qua Pydantic
response model, không trả raw SQLAlchemy object.

## 4. Migration path (không có giai đoạn "chạy song song 2 UI")

Build React đạt parity xong (task cuối của plan) rồi mới xoá `web.py`/`templates/` trong
cùng plan — tại mọi thời điểm giữa các task, cả 2 vẫn cùng tồn tại trong repo (test cũ
của `test_web_orders.py` vẫn chạy) cho tới task xoá, để không có khoảng trống không test
được. Sau task xoá, `test_web_orders.py` cũng bị xoá cùng (thay bằng test JSON API mới).

## 5. Non-goal

Không có SSR, không có state management library, không polish UI/UX (Tailwind styling
tối thiểu, đẹp hơn để sub-project 3 làm khi có drag-drop) — mục tiêu duy nhất: đúng chức
năng cũ, trên React, sẵn sàng nền cho drag-drop.

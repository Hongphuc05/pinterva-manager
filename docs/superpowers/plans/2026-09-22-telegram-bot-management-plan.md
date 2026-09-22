# Kế hoạch triển khai: Quản lý Bot Telegram

## Global constraints

- PostgreSQL là source of truth; Telegram chỉ là kênh phụ.
- Không expose token bot, callback token hoặc raw credential trong UI/log.
- Mọi mutation admin phải enforce role ở backend, scope platform và có audit.
- Giữ tương thích `users.telegram_chat_id` và flow `/start <link_code>`.
- Không fallback âm thầm từ group sang chat riêng.
- Template chỉ chứa text + placeholder allowlist; không cho sửa logic gửi.

## Task 1 — Schema, migration và model

1. Thêm các cột group/mode/verification vào `User`.
2. Thêm `TelegramMessageTemplate` với default seed deterministic.
3. Thêm `TelegramConfigurationAudit` cho thay đổi mapping/mode/template.
4. Tạo Alembic migration nối từ head hiện tại, có downgrade.
5. Seed template bằng migration với `ON CONFLICT DO NOTHING` để chạy lại an toàn.

**Consumes:** `User`, Telegram service hiện hành, Alembic head.
**Produces:** model/migration, default templates, constraints/index.

## Task 2 — Telegram application service

1. Tạo constants cho mode/event/template placeholders.
2. Tạo resolver đích gửi cho designer.
3. Tạo renderer template với validation placeholder và giới hạn độ dài.
4. Tạo `inspect_telegram_group` dùng `getChat`/`getChatMember`.
5. Chuyển notification designer sang resolver + template.
6. Chuyển notification admin sang template, giữ nguyên recipient/callback behavior.
7. Trả trạng thái delivery/error rõ ràng, không nuốt lỗi cấu hình.

**Consumes:** models, Bot API wrapper, existing notification functions.
**Produces:** service API ổn định cho routes/workers và tests.

## Task 3 — Admin API

1. Thêm endpoint overview cho danh sách designer + trạng thái bot.
2. Thêm endpoint lưu/xóa group ID.
3. Thêm endpoint verify group.
4. Thêm endpoint đổi delivery mode.
5. Thêm endpoint gửi test text.
6. Thêm CRUD template + preview.
7. Ghi audit before/after bằng actor hiện tại.
8. Viết permission/platform-scope/idempotency tests.

**Consumes:** Task 1/2.
**Produces:** `/api/telegram/admin/*` contract cho SPA.

## Task 4 — Frontend tab admin

1. Thêm route `/telegram-management`, protected `admin`.
2. Thêm Sidebar item và mobile navigation nếu phù hợp.
3. Hiển thị bot status, bảng designer, filter/search.
4. Form group ID + verify + test + mode selector.
5. Hiển thị lỗi gửi gần nhất và trạng thái connected.
6. Khu vực sửa template, placeholder guide, preview và reset default.
7. Toast/error/loading/empty state; không đưa secret lên client.

**Consumes:** Task 3 API types.
**Produces:** tab quản lý dùng được trên desktop/mobile.

## Task 5 — Documentation và regression tests

1. Backend unit/integration tests cho routing, verify, templates, permissions.
2. Frontend tests cho route, mode/group form, template editor.
3. Cập nhật `docs/tacahu-ops-core/api-surface.md`, `architecture.md`,
   `data-storage.md`, `access-and-privacy.md`, `operations.md`.
4. Cập nhật `.env.example` chỉ khi có cấu hình mới thực sự cần; không thêm secret.

## Task 6 — Verification và handoff

1. `git diff --check`, Ruff, compile/import.
2. Chạy test Telegram/API liên quan tuần tự.
3. Chạy frontend test/build.
4. Chạy migration head trên DB test.
5. Kiểm tra git diff, báo rõ pass/fail và phần chưa live-verify.
6. Không commit/push/deploy nếu chưa có yêu cầu riêng.

# Printerval order chat → Tacahu (read-only mirror, toasts)

Status: approved in chat 2026-10-14. Implementation plan at the end.

## Why

Printerval added a chat box per design job. Its QC staff now report Fix requests and other
remarks there, sometimes still in `note_outsource`. Tacahu must show both. The existing
`note_outsource` mirroring (status sync) stays exactly as it is; chat is an additional, parallel,
read-only channel.

## What Printerval exposes (observed 2026-10-14, account session)

- `GET /central/outsource/pod/design-job/chat/messages?design_job_id=<numeric id>&after_id=<id>`
  → `{status, chat: {design_job_id, fix_round, last_message_id, job_status, team, closed},
  messages: [{id, design_job_id, fix_round, type, sender_type, sender_name, sender_email, team,
  content, image_urls, fix_reason, fix_reason_label, created_at, mine}], can_post, side, me}`.
  `type` seen: `fix_open`. `sender_type`: `staff` = Printerval side. `created_at` is a naive
  Vietnam-time string (`2026-10-14 14:05:10`).
- **Reading messages marks the job as read for the whole team** (it leaves `unread.job_ids`).
- `GET /central/outsource/pod/design-job/chat/unread?ids=<csv>` → `{unread: {<id>: n}, total,
  job_ids: [...]}`; `job_ids` lists every job of the team with unread messages. Does not mark read.
- `POST .../chat/send` exists; not used (read-only).

## Decisions (operator)

| Topic | Decision |
|---|---|
| Scope | Read only, never post to Printerval |
| Who sees | Admin only (whole platform). Designers do not see the chat (changed 2026-10-14) |
| What | The whole conversation, both sides, exactly as on Printerval |
| Sync | Every 2 minutes, orders in Doing / Review / Fix; plus on opening an order |
| Read state | Tacahu fetches content itself and keeps its own per-user unread state. Accepted: the web-mẹ badge is cleared by Tacahu and Printerval sees "read" early |
| Notify | Web toast (no Telegram) to Admins, and to the assigned designer, for Printerval-side messages only |
| Retention | Delete an order's chat data 30 days after it is Done/Cancelled; refetched from 0 if it reopens |
| Safety | Chat never changes order state; Fix detection stays with status sync |

## Design

### Data (root Alembic chain)

- `order_chat_messages`: `id` uuid, `order_id` FK orders (CASCADE), `platform_id`, `external_id`
  int, `fix_round`, `type`, `sender_type`, `sender_name`, `mine` bool, `content` text,
  `image_urls` JSONB, `fix_reason_label`, `sent_at` timestamptz, `created_at`.
  Unique `(order_id, external_id)`; index `(platform_id, sent_at)`.
- `orders.chat_last_message_id` int null (the `after_id` cursor), `orders.chat_synced_at`.
- `order_chat_reads`: `(order_id, user_id)` unique, `last_read_external_id` int — same shape as
  `order_work_note_reads`.

### Sync — `app/application/order_chat.py`, worker `app/workers/order_chat_tasks.py`

Beat task every 120 s, one platform at a time, guarded by a Postgres advisory lock so runs never
overlap:
1. `unread` once → `job_ids` ∩ the platform's orders in `IN_PROGRESS / QC_PENDING / REVISION`.
2. Plus up to 40 more of those orders, oldest `chat_synced_at` first (catches messages someone
   already read on Printerval).
3. Per order: `messages?after_id=<cursor>`; insert new rows (`ON CONFLICT DO NOTHING`), move the
   cursor to `chat.last_message_id`, set `chat_synced_at`. One order failing never aborts the run.

On-demand: `GET /orders/{id}/chat` syncs that order first when `chat_synced_at` is older than 30 s
(failure → stored messages plus `stale: true`).

Nightly cleanup task: for orders Done/Cancelled with `status_changed_at` older than 30 days, delete
their chat messages and reads, reset the cursor and `chat_synced_at`.

### API

- `GET /orders/{id}/chat` → messages (oldest first) + `unread_from` for the caller. Access = the
  existing `get_order_detail_for_user` rule (same as work notes), Admin and designers only.
- `POST /orders/{id}/chat/read` → caller's `last_read_external_id = max id`.
- `GET /chat/unread` → for the caller: orders in scope with Printerval-side messages
  (`mine = false`) newer than their read marker: order id/code, count, latest sender/snippet/
  external id. Admin: platform; designer: their active assignments.
- Order list rows get `chat_unread` (one aggregate query for the page).

### Web

- `ChatPanel` on the order detail page: bubbles left (Printerval) / right (mine), sender, time,
  images (links open full size), a "Mở Fix vòng N" label for `fix_open`. Opening marks read.
- `useChatToasts` in the dashboard layout: polls `/chat/unread` every 30 s, toasts each message id
  once (highest toasted id kept in localStorage per user), click opens the order.
- Badge on order-list rows and a "Có tin chat mới" filter.

### Errors, security

- Printerval errors are logged and skipped; status 401/403 re-logs in once (existing client
  pattern). Content is rendered as text (no HTML), image URLs must be http(s).
- Designers never see a chat of an order not assigned to them; platform scoping everywhere.

## Implementation plan

1. Migration + models (`OrderChatMessage`, `OrderChatRead`, two `Order` columns).
2. `PrintervalApiClient.fetch_chat_messages(job_id, after_id)` and `fetch_chat_unread(ids)`.
3. `order_chat.py`: `parse_message`, `sync_order_chat`, `sync_platform_chats`, `unread_for_user`,
   `mark_read`, `purge_closed_chats`; tests with a fake client (idempotent insert, cursor,
   per-order failure isolation, unread scope, designer isolation, purge).
4. Worker tasks + beat entries (120 s sync, nightly purge), behind `order_chat_enabled` setting.
5. API routes + tests (access rules, on-demand sync throttle, read marker, platform isolation).
6. Web: `ChatPanel`, `useChatToasts`, list badge/filter; vitest.
7. Docs: `data-storage.md`, `access-and-privacy.md`, `api-surface.md`, `operations.md`.
8. Verify against production read-only (`unread` call only) before enabling the beat task.

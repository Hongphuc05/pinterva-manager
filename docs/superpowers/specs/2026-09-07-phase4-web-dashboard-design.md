# Phase 4 — Web Dashboard Skeleton Design

**Status:** Approved by user 2026-09-07.

## 1. Scope

Implement Phase 4 per roadmap.md: the web dashboard skeleton — layout, role-based nav,
an order list page (filterable by status/batch/designer), an order detail page, login/
logout, and role-gated routes. Per claude.md §4/§10: server-rendered Jinja2 + HTMX +
Alpine.js, no separate SPA.

**Acceptance criteria (from roadmap.md):** admin sees every order; a designer sees only
their own (via `Assignment.designer_id` — this will legitimately be empty right now,
since Phase 5/C2 hasn't been built yet and no assignments exist); the UI shows each
order's current state and its full `WorkflowEvent` history.

**No new DB migration** — `orders`, `batches`, `assignments`, `workflow_events`, `users`
already cover everything this phase needs (Phase 1).

**Explicitly out of scope:** anything from C2-C5 (offer/assign/QC/submit UI) — this
phase only *displays* what already exists in the DB; Phase 5 onward adds the actions
that create assignments/results/QC decisions.

## 2. Architecture

```
Existing (Phase 1, untouched): /api/login, /api/logout, /api/me, /api/admin/ping,
/api/designer/ping — pure JSON, session cookie, used by whatever still needs a JSON
auth API (kept as-is, not repurposed).

New (this phase), plain paths (no /api prefix — pages, not API):
  GET  /                -> redirect to /orders (authed) or /login
  GET  /login            -> render login form
  POST /login             -> verify credentials, set cookie, redirect /orders;
                             on failure: re-render form with an error, HTTP 200
  POST /logout            -> clear cookie, redirect /login
  GET  /orders            -> full order list page (table + filter form)
  GET  /orders/table       -> HTMX partial: just the <table> fragment, same filters
  GET  /orders/{id}        -> order detail page (fields + WorkflowEvent history)
```

`app/api/routes/web.py` holds these routes. They call into a new
`app/application/order_queries.py` for all DB access (claude.md §13: domain/application
code stays independent of FastAPI) — route handlers only parse query params, call the
query function, and render a template; no query logic lives in the route file.

## 3. Auth for web routes vs. the existing JSON API

The existing `get_current_user` dependency (`app/api/deps.py`) raises `HTTPException`
on missing/invalid session — correct for a JSON API, wrong for a browser page (should
redirect to `/login`, not show a raw 401 JSON body).

New dependency `get_current_user_web(request, db) -> User` in `app/api/deps.py`:
identical session-cookie lookup, but raises a new `WebAuthRedirect` exception instead of
`HTTPException` on failure. A new `@app.exception_handler(WebAuthRedirect)` (registered
in `app/api/main.py`) returns `RedirectResponse("/login", status_code=302)`. This keeps
`get_current_user`/`/api/*` completely untouched — the web routes use the new
dependency, the JSON routes keep the old one.

## 4. Order queries (`app/application/order_queries.py`)

```python
def list_orders_for_user(
    session: Session, user: User, status: str | None = None,
    batch_id: str | None = None, designer_id: str | None = None,
) -> list[Order]:
```
Admin: all orders, optionally filtered by `status`/`batch_id`/`designer_id` (the last
via a join to `Assignment`). Designer: forces the query to only orders with an
`Assignment.designer_id == user.id` (ignores any `designer_id` param passed in — a
designer can't view someone else's queue by tampering with the query string), plus
still honors `status`/`batch_id` if given. Ordered by `created_at desc`.

```python
def get_order_detail_for_user(session: Session, user: User, order_id: str) -> Order | None:
```
Admin: any order, or `None` if the ID doesn't exist. Designer: `None` unless they have
an `Assignment` on that order (this **is** the access-control check for the detail
page — the route returns 404 either way, so a designer can't distinguish "doesn't
exist" from "not yours" by probing IDs).

Both functions return plain `Order` ORM objects (with relationships available for the
template to walk: `order.batch`, and the route separately queries
`WorkflowEvent.filter_by(order_id=...).order_by(created_at)` for the detail page's
history — kept as a third small function
`get_order_history(session, order_id) -> list[WorkflowEvent]` in the same module for
symmetry, rather than inlined in the route).

## 5. Templates

`app/api/templates/`:
- `base.html` — `<html>` shell, one CDN `<link>` to Pico.css (classless, no build
  step), a nav bar rendered from a `user` template variable (role-conditional links:
  admin sees "Đơn hàng" only for now — more links arrive in later phases), a
  `{% block content %}`.
- `login.html` — extends base (nav omitted/minimal when logged out), a plain form
  (`username`, `password`), an optional `{{ error }}` line.
- `orders_list.html` — extends base; a filter form (`status` select, `batch_id` text/
  select, `designer_id` select — admin only, hidden entirely for a designer user) whose
  inputs use `hx-get="/orders/table" hx-target="#orders-table" hx-trigger="change"`
  (submits itself on every filter change, swaps only the table); includes
  `orders_table.html` for the initial render so the page isn't empty before any HTMX
  interaction fires.
- `orders_table.html` — just the `<table id="orders-table">...</table>` fragment
  (columns: external_order_id linking to the detail page, state, batch, designer if
  assigned, created_at). This exact same template renders both the full page's initial
  table AND the `/orders/table` partial response — one template, two call sites,
  matching DRY.
- `order_detail.html` — extends base; order fields, then a chronological list of
  `WorkflowEvent` rows (`from_state -> to_state`, `created_at`, `actor` if present).

## 6. Testing

`TestClient` (already used in `tests/test_api_auth.py`) — no real browser needed for
server-rendered HTML.

- Login: GET renders a form; POST with valid credentials sets the cookie and redirects
  to `/orders`; POST with invalid credentials re-renders the form with an error and
  does NOT set a cookie.
- Unauthenticated `GET /orders` redirects to `/login` (proves `get_current_user_web`
  wired correctly, distinct from the JSON API's 401 behavior).
- Admin sees all seeded orders; a designer with no assignments sees an empty table; a
  designer with one assignment sees exactly that order and no others.
- `GET /orders/table` returns a response whose body contains `<table` but not `<html`
  (proves it's genuinely a partial, not accidentally rendering the full page).
- Order detail: admin can view any order; a designer gets 404 on an order they have no
  assignment for (not 403 — indistinguishable from "doesn't exist", per §4); the
  rendered page contains the order's `WorkflowEvent` history entries.

## 7. Out of scope / follow-ups

- Any action that changes state (offer, assign, approve, submit) — Phase 5 onward.
- Exception queue UI specifically — the order list's `status` filter already lets an
  admin filter to `EXCEPTION`, which covers the roadmap's "exception queue" need for
  this phase without a dedicated separate screen; a richer exception-queue view (with
  recovery actions) is a natural Phase 5+ follow-up once `dead_letters` needs an
  operator-facing recovery action (already tracked as a Phase 3 follow-up).

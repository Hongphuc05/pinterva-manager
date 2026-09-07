# Phase 4 — Web Dashboard Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the server-rendered web dashboard skeleton — login/logout, role-gated
pages, an order list (filterable, HTMX partial-refresh), and an order detail page with
`WorkflowEvent` history.

**Architecture:** New plain-path routes (`/login`, `/orders`, `/orders/{id}`, etc.) in
`app/api/routes/web.py`, backed by a new query module `app/application/order_queries.py`
and a new redirect-based auth dependency, alongside (not replacing) the existing
`/api/*` JSON auth API from Phase 1.

**Tech Stack:** Jinja2 templates (FastAPI's `Jinja2Templates`), HTMX (CDN, no build
step), Pico.css (CDN, classless). Reuses Phase 1's `verify_password`,
`create_session_token`, `read_session_token`, `SessionLocal`, `get_db`.

**Spec:** `docs/superpowers/specs/2026-09-07-phase4-web-dashboard-design.md`

## Global Constraints

- No new DB migration — `orders`, `batches`, `assignments`, `workflow_events`, `users`
  already cover everything (Phase 1 schema).
- Domain/application logic stays independent of FastAPI/Jinja2 (claude.md §13) — route
  handlers only parse params, call an application-layer function, and render a
  template; query logic lives in `app/application/order_queries.py`, never inline in a
  route.
- The existing `/api/*` JSON routes (`app/api/routes/auth.py`, `app/api/deps.py`'s
  `get_current_user`) stay completely untouched — new web routes get their own
  redirect-based auth dependency, never repurpose the JSON one.
- A designer's order-list/detail access is enforced server-side via `Assignment` rows —
  never trust a client-supplied `designer_id` query param for a designer's own view.
- Every template extends `base.html`; no page duplicates the `<html>`/nav shell.
- Automated tests use `fastapi.testclient.TestClient` + the real test-Postgres
  `db_session` fixture (established pattern, see `tests/test_api_auth.py`) — no real
  browser needed for server-rendered HTML.

---

### Task 1: Templates infra + login/logout web routes

**Files:**
- Modify: `pyproject.toml` (add `jinja2`, `python-multipart` — required by FastAPI's
  `Jinja2Templates` and `Form(...)` parsing respectively)
- Create: `app/api/templates/base.html`
- Create: `app/api/templates/login.html`
- Create: `app/api/routes/web.py`
- Modify: `app/api/main.py` (register the new router)
- Test: `tests/test_web_login.py`

**Interfaces:**
- Consumes: `app.application.auth.{verify_password, create_session_token}` (exist),
  `app.api.deps.{SESSION_COOKIE_NAME, get_db}` (exist), `app.config.get_settings`
  (exists).
- Produces: `app/api/routes/web.py`'s `router` (an `APIRouter`) and its module-level
  `templates` (a `Jinja2Templates` instance pointed at `app/api/templates`) — Tasks 2-4
  add more routes to this same router and reuse this same `templates` object, don't
  create a second one.

- [ ] **Step 1: Add dependencies to `pyproject.toml`**

Read the current `dependencies = [...]` list first. Add:
```toml
  "jinja2>=3.1",
  "python-multipart>=0.0.9",
```
Run `pip install -e ".[dev]"` (check `RUNME.md` if unsure of the exact install command).

- [ ] **Step 2: Create `app/api/templates/base.html`**

```html
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Pinterval Ops{% endblock %}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
  <script src="https://cdn.jsdelivr.net/npm/htmx.org@1.9.12/dist/htmx.min.js"></script>
</head>
<body>
  <nav class="container">
    <ul><li><strong>Pinterval Ops</strong></li></ul>
    <ul>
      {% if user %}
        <li>{{ user.full_name }} ({{ user.role }})</li>
        <li><a href="/orders">Đơn hàng</a></li>
        <li>
          <form method="post" action="/logout" style="display:inline">
            <button type="submit" class="secondary">Đăng xuất</button>
          </form>
        </li>
      {% endif %}
    </ul>
  </nav>
  <main class="container">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 3: Create `app/api/templates/login.html`**

```html
{% extends "base.html" %}
{% block title %}Đăng nhập{% endblock %}
{% block content %}
<article style="max-width: 400px; margin: 4rem auto;">
  <h1>Đăng nhập</h1>
  {% if error %}<p style="color: red;">{{ error }}</p>{% endif %}
  <form method="post" action="/login">
    <label>Tên đăng nhập
      <input type="text" name="username" required autofocus>
    </label>
    <label>Mật khẩu
      <input type="password" name="password" required>
    </label>
    <button type="submit">Đăng nhập</button>
  </form>
</article>
{% endblock %}
```

- [ ] **Step 4: Write the failing tests — `tests/test_web_login.py`**

```python
import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import User
from app.api.deps import get_db
from app.api.main import create_app
from app.application.auth import hash_password


@pytest.fixture()
def client(db_session):
    app = create_app()

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_user(db_session):
    user = User(
        username="admin1", full_name="Admin One", role="admin",
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_login_page_renders(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "<form" in resp.text


def test_login_success_redirects_and_sets_cookie(client, admin_user):
    resp = client.post(
        "/login", data={"username": "admin1", "password": "s3cret!"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/orders"
    assert "session" in resp.cookies


def test_login_failure_rerenders_with_error_and_no_cookie(client, admin_user):
    resp = client.post("/login", data={"username": "admin1", "password": "wrong"})
    assert resp.status_code == 401
    assert "session" not in resp.cookies
    assert "Sai tên đăng nhập" in resp.text


def test_logout_clears_cookie_and_redirects(client, admin_user):
    client.post("/login", data={"username": "admin1", "password": "s3cret!"})
    resp = client.post("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `pytest tests/test_web_login.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api.routes.web'` (or a
404, once you get further)

- [ ] **Step 6: Create `app/api/routes/web.py`**

Note on `TemplateResponse`'s signature: the installed starlette version (confirmed via
`grep -n "def TemplateResponse" -A 20 .venv/lib/python3.12/site-packages/starlette/templating.py`
at plan-writing time) only accepts the newer positional form
`TemplateResponse(request, name, context)` — NOT the older `TemplateResponse(name,
{"request": request, ...})` some training data defaults to. Every `TemplateResponse`
call in this plan already uses the correct newer form — if you see the older form
anywhere while implementing, that's a mistake to fix, not a pattern to follow. If a
different starlette version somehow ends up installed, re-check that grep command
yourself before writing template response calls.

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.api.deps import SESSION_COOKIE_NAME, get_db
from app.application.auth import create_session_token, verify_password
from app.config import get_settings

router = APIRouter()
templates = Jinja2Templates(directory="app/api/templates")


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"user": None})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter_by(username=username).one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"user": None, "error": "Sai tên đăng nhập hoặc mật khẩu"},
            status_code=401,
        )
    settings = get_settings()
    token = create_session_token(str(user.id), user.role)
    response = RedirectResponse("/orders", status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_max_age_seconds,
    )
    return response


@router.post("/logout")
def logout_submit():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
```

- [ ] **Step 7: Register the router in `app/api/main.py`**

Read the current file first. Add the import and registration (no prefix — these are
plain paths, not `/api/*`):

```python
from app.api.routes import web as web_routes
...
    app.include_router(web_routes.router)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_web_login.py -v`
Expected: all 4 tests PASS

- [ ] **Step 9: Run the full suite + ruff**

Run: `pytest -q` (no regressions) and `ruff check .` (clean).

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml app/api/templates/base.html app/api/templates/login.html app/api/routes/web.py app/api/main.py tests/test_web_login.py
git commit -m "feat: web dashboard login/logout pages (Jinja2 + session cookie)"
```

---

### Task 2: Redirect-based auth dependency + order query functions

**Files:**
- Modify: `app/api/deps.py` (add `WebAuthRedirect` + `get_current_user_web`)
- Modify: `app/api/main.py` (register the exception handler)
- Create: `app/application/order_queries.py`
- Test: `tests/test_order_queries.py`

**Interfaces:**
- Consumes: `app.adapters.db.models.{Assignment, Order, User, WorkflowEvent}` (exist —
  read `app/adapters/db/models.py` first to confirm field names before writing
  anything), `app.domain.models.OrderState` (exists).
- Produces: `get_current_user_web(request, db) -> User` and `WebAuthRedirect`
  (exception class), both in `app.api.deps` — Task 3 depends on both by these exact
  names. `list_orders_for_user(session, user, status=None, batch_id=None,
  designer_id=None) -> list[Order]`, `get_order_detail_for_user(session, user,
  order_id) -> Order | None`, `get_order_history(session, order_id) ->
  list[WorkflowEvent]`, all in `app.application.order_queries` — Tasks 3-4 call these
  exact names/signatures.

This task's `get_current_user_web`/`WebAuthRedirect` don't get an isolated unit test
here — they're exercised for real in Task 3's first protected route (testing a FastAPI
dependency in isolation means manufacturing a fake `Request`, which is more awkward
and less meaningful than testing it through an actual route). This task's tests cover
`order_queries.py` only.

- [ ] **Step 1: Write the failing tests — `tests/test_order_queries.py`**

```python
from app.adapters.db.models import Assignment, Order, User, WorkflowEvent
from app.application.auth import hash_password
from app.application.order_queries import (
    get_order_detail_for_user,
    get_order_history,
    list_orders_for_user,
)
from app.domain.models import OrderState


def _make_user(db_session, role, username):
    user = User(
        username=username, full_name=username, role=role,
        password_hash=hash_password("x"),
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_list_orders_for_user_admin_sees_all(db_session):
    admin = _make_user(db_session, "admin", "admin1")
    db_session.add(Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value))
    db_session.add(Order(external_order_id="DJ2", state=OrderState.DISCOVERED.value))
    db_session.commit()

    orders = list_orders_for_user(db_session, admin)

    assert {o.external_order_id for o in orders} == {"DJ1", "DJ2"}


def test_list_orders_for_user_designer_sees_only_assigned(db_session):
    designer = _make_user(db_session, "designer", "designer1")
    other_designer = _make_user(db_session, "designer", "designer2")
    o1 = Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value)
    o2 = Order(external_order_id="DJ2", state=OrderState.DISCOVERED.value)
    db_session.add_all([o1, o2])
    db_session.commit()
    db_session.add(Assignment(order_id=o1.id, designer_id=designer.id, status="active"))
    db_session.add(Assignment(order_id=o2.id, designer_id=other_designer.id, status="active"))
    db_session.commit()

    orders = list_orders_for_user(db_session, designer)

    assert [o.external_order_id for o in orders] == ["DJ1"]


def test_list_orders_for_user_designer_with_no_assignments_sees_empty(db_session):
    designer = _make_user(db_session, "designer", "designer1")
    db_session.add(Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value))
    db_session.commit()

    orders = list_orders_for_user(db_session, designer)

    assert orders == []


def test_list_orders_for_user_designer_ignores_supplied_designer_id(db_session):
    designer = _make_user(db_session, "designer", "designer1")
    other_designer = _make_user(db_session, "designer", "designer2")
    order = Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value)
    db_session.add(order)
    db_session.commit()
    db_session.add(Assignment(order_id=order.id, designer_id=designer.id, status="active"))
    db_session.commit()

    # designer1 tries to view designer2's queue by passing designer_id — must be ignored.
    orders = list_orders_for_user(db_session, designer, designer_id=str(other_designer.id))

    assert [o.external_order_id for o in orders] == ["DJ1"]


def test_list_orders_for_user_filters_by_status(db_session):
    admin = _make_user(db_session, "admin", "admin1")
    db_session.add(Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value))
    db_session.add(Order(external_order_id="DJ2", state=OrderState.CLAIMED_IMPORTED.value))
    db_session.commit()

    orders = list_orders_for_user(db_session, admin, status=OrderState.CLAIMED_IMPORTED.value)

    assert [o.external_order_id for o in orders] == ["DJ2"]


def test_list_orders_for_user_invalid_batch_id_returns_empty_not_error(db_session):
    admin = _make_user(db_session, "admin", "admin1")
    db_session.add(Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value))
    db_session.commit()

    orders = list_orders_for_user(db_session, admin, batch_id="not-a-uuid")

    assert orders == []


def test_get_order_detail_for_user_admin_sees_any_order(db_session):
    admin = _make_user(db_session, "admin", "admin1")
    order = Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value)
    db_session.add(order)
    db_session.commit()

    result = get_order_detail_for_user(db_session, admin, str(order.id))

    assert result is not None
    assert result.external_order_id == "DJ1"


def test_get_order_detail_for_user_designer_without_assignment_gets_none(db_session):
    designer = _make_user(db_session, "designer", "designer1")
    order = Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value)
    db_session.add(order)
    db_session.commit()

    result = get_order_detail_for_user(db_session, designer, str(order.id))

    assert result is None


def test_get_order_detail_for_user_invalid_uuid_returns_none(db_session):
    admin = _make_user(db_session, "admin", "admin1")

    result = get_order_detail_for_user(db_session, admin, "not-a-uuid")

    assert result is None


def test_get_order_history_returns_events_in_order(db_session):
    order = Order(external_order_id="DJ1", state=OrderState.CLAIMED_IMPORTED.value)
    db_session.add(order)
    db_session.commit()
    db_session.add(
        WorkflowEvent(order_id=order.id, from_state="DISCOVERED", to_state="CLAIMED_IMPORTED")
    )
    db_session.commit()

    events = get_order_history(db_session, str(order.id))

    assert len(events) == 1
    assert events[0].to_state == "CLAIMED_IMPORTED"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_order_queries.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.application.order_queries'`

- [ ] **Step 3: Create `app/application/order_queries.py`**

```python
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.adapters.db.models import Assignment, Order, User, WorkflowEvent


def list_orders_for_user(
    session: Session,
    user: User,
    status: str | None = None,
    batch_id: str | None = None,
    designer_id: str | None = None,
) -> list[Order]:
    """Admin: all orders, optionally filtered. Designer: forced to only their own
    assigned orders (any designer_id param is ignored, never trusted for a designer's
    own view) — status/batch_id filters still apply on top of that.
    """
    query = session.query(Order)

    if user.role == "designer":
        query = query.join(Assignment, Assignment.order_id == Order.id).filter(
            Assignment.designer_id == user.id
        )
    elif designer_id:
        try:
            designer_uuid = uuid.UUID(designer_id)
        except ValueError:
            return []
        query = query.join(Assignment, Assignment.order_id == Order.id).filter(
            Assignment.designer_id == designer_uuid
        )

    if status:
        query = query.filter(Order.state == status)

    if batch_id:
        try:
            batch_uuid = uuid.UUID(batch_id)
        except ValueError:
            return []
        query = query.filter(Order.batch_id == batch_uuid)

    return query.order_by(Order.created_at.desc()).all()


def get_order_detail_for_user(session: Session, user: User, order_id: str) -> Order | None:
    """Admin: any order. Designer: only if they have an Assignment on it — returning
    None either way (not 403) so a designer can't distinguish "doesn't exist" from
    "not yours" by probing IDs.
    """
    try:
        order_uuid = uuid.UUID(order_id)
    except ValueError:
        return None

    order = session.get(Order, order_uuid)
    if order is None:
        return None

    if user.role == "designer":
        has_assignment = (
            session.query(Assignment)
            .filter_by(order_id=order.id, designer_id=user.id)
            .first()
            is not None
        )
        if not has_assignment:
            return None

    return order


def get_order_history(session: Session, order_id: str) -> list[WorkflowEvent]:
    try:
        order_uuid = uuid.UUID(order_id)
    except ValueError:
        return []
    return (
        session.query(WorkflowEvent)
        .filter_by(order_id=order_uuid)
        .order_by(WorkflowEvent.created_at)
        .all()
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_order_queries.py -v`
Expected: all 10 tests PASS

- [ ] **Step 5: Add `WebAuthRedirect` + `get_current_user_web` to `app/api/deps.py`**

Read the current file in full first (Task 1 didn't touch it, but confirm it still
matches what's shown in this plan's earlier reads before editing). Add, after the
existing `get_current_user` function:

```python
class WebAuthRedirect(Exception):
    """Raised by get_current_user_web when a browser request has no valid session.
    Caught by an app-level exception handler (app/api/main.py) that redirects to
    /login — unlike get_current_user's HTTPException (401 JSON, for the /api/* routes).
    """


def get_current_user_web(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise WebAuthRedirect()
    data = read_session_token(token)
    if data is None:
        raise WebAuthRedirect()
    user = db.get(User, uuid.UUID(data["user_id"]))
    if user is None or not user.active:
        raise WebAuthRedirect()
    return user
```

- [ ] **Step 6: Register the exception handler in `app/api/main.py`**

Read the current file first (Task 1 already modified it). Add:

```python
from fastapi.responses import RedirectResponse

from app.api.deps import WebAuthRedirect
```

and, inside `create_app()`, after the router registrations:

```python
    @app.exception_handler(WebAuthRedirect)
    def _redirect_to_login(request, exc):
        return RedirectResponse("/login", status_code=302)

    return app
```

(If `create_app()` currently ends with `return app` directly after the router
registrations, insert the handler registration before that `return`.)

- [ ] **Step 7: Run the full suite + ruff**

Run: `pytest -q` (no regressions) and `ruff check .` (clean).

- [ ] **Step 8: Commit**

```bash
git add app/api/deps.py app/api/main.py app/application/order_queries.py tests/test_order_queries.py
git commit -m "feat: redirect-based web auth dependency + order query functions"
```

---

### Task 3: Order list page (`/`, `/orders`, `/orders/table`)

**Files:**
- Modify: `app/api/routes/web.py` (add the three routes)
- Create: `app/api/templates/orders_list.html`
- Create: `app/api/templates/orders_table.html`
- Test: `tests/test_web_orders.py`

**Interfaces:**
- Consumes: `get_current_user_web`, `WebAuthRedirect` (Task 2, from `app.api.deps`);
  `list_orders_for_user` (Task 2, from `app.application.order_queries`); `router`,
  `templates` (Task 1, from this same `app/api/routes/web.py` file — add to them, don't
  recreate).
- Produces: nothing new consumed by a later task in this plan — Task 4 is
  self-contained on top of Task 2's query functions.

- [ ] **Step 1: Write the failing tests — `tests/test_web_orders.py`**

```python
import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import Order, User
from app.api.deps import get_db
from app.api.main import create_app
from app.application.auth import hash_password
from app.domain.models import OrderState


@pytest.fixture()
def client(db_session):
    app = create_app()

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, db_session, role, username="user1"):
    user = User(
        username=username, full_name=username, role=role,
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(user)
    db_session.commit()
    client.post("/login", data={"username": username, "password": "s3cret!"})
    return user


def test_root_redirects_authed_user_to_orders(client, db_session):
    _login(client, db_session, "admin")
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/orders"


def test_orders_requires_login_redirects_to_login(client):
    resp = client.get("/orders", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_orders_list_shows_all_orders_for_admin(client, db_session):
    _login(client, db_session, "admin")
    db_session.add(Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value))
    db_session.add(Order(external_order_id="DJ2", state=OrderState.DISCOVERED.value))
    db_session.commit()

    resp = client.get("/orders")

    assert resp.status_code == 200
    assert "DJ1" in resp.text
    assert "DJ2" in resp.text


def test_orders_list_shows_empty_for_designer_with_no_assignments(client, db_session):
    _login(client, db_session, "designer")
    db_session.add(Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value))
    db_session.commit()

    resp = client.get("/orders")

    assert resp.status_code == 200
    assert "DJ1" not in resp.text


def test_orders_table_partial_returns_only_table_fragment(client, db_session):
    _login(client, db_session, "admin")

    resp = client.get("/orders/table")

    assert resp.status_code == 200
    assert "<table" in resp.text
    assert "<html" not in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_orders.py -v`
Expected: FAIL — `/` and `/orders` don't exist yet (404s)

- [ ] **Step 3: Create `app/api/templates/orders_table.html`**

```html
<table id="orders-table">
  <thead>
    <tr><th>Mã đơn</th><th>Trạng thái</th><th>Batch</th><th>Ngày tạo</th></tr>
  </thead>
  <tbody>
    {% for order in orders %}
    <tr>
      <td><a href="/orders/{{ order.id }}">{{ order.external_order_id }}</a></td>
      <td>{{ order.state }}</td>
      <td>{{ order.batch_id or "-" }}</td>
      <td>{{ order.created_at }}</td>
    </tr>
    {% else %}
    <tr><td colspan="4">Không có đơn nào.</td></tr>
    {% endfor %}
  </tbody>
</table>
```

- [ ] **Step 4: Create `app/api/templates/orders_list.html`**

```html
{% extends "base.html" %}
{% block title %}Đơn hàng{% endblock %}
{% block content %}
<h1>Đơn hàng</h1>
<form hx-get="/orders/table" hx-target="#orders-table" hx-trigger="change" hx-include="this">
  <label>Trạng thái
    <select name="status">
      <option value="">Tất cả</option>
      {% for s in order_states %}
      <option value="{{ s }}" {% if status == s %}selected{% endif %}>{{ s }}</option>
      {% endfor %}
    </select>
  </label>
  {% if user.role == "admin" %}
  <label>Batch ID
    <input type="text" name="batch_id" value="{{ batch_id or '' }}">
  </label>
  {% endif %}
</form>
{% include "orders_table.html" %}
{% endblock %}
```

- [ ] **Step 5: Add the three routes to `app/api/routes/web.py`**

Read the current file first (Task 1 created it). Add these imports at the top
alongside the existing ones:

```python
from app.adapters.db.models import User  # already imported by Task 1 — confirm, don't duplicate
from app.api.deps import get_current_user_web
from app.application.order_queries import list_orders_for_user
from app.domain.models import OrderState
```

Then add, after the existing `logout_submit` function:

```python
@router.get("/")
def index(user: User = Depends(get_current_user_web)):
    return RedirectResponse("/orders", status_code=303)


@router.get("/orders")
def orders_list(
    request: Request,
    status: str | None = None,
    batch_id: str | None = None,
    designer_id: str | None = None,
    user: User = Depends(get_current_user_web),
    db: Session = Depends(get_db),
):
    orders = list_orders_for_user(
        db, user, status=status, batch_id=batch_id, designer_id=designer_id
    )
    return templates.TemplateResponse(
        request,
        "orders_list.html",
        {
            "user": user,
            "orders": orders,
            "status": status,
            "batch_id": batch_id,
            "order_states": [s.value for s in OrderState],
        },
    )


@router.get("/orders/table")
def orders_table(
    request: Request,
    status: str | None = None,
    batch_id: str | None = None,
    designer_id: str | None = None,
    user: User = Depends(get_current_user_web),
    db: Session = Depends(get_db),
):
    orders = list_orders_for_user(
        db, user, status=status, batch_id=batch_id, designer_id=designer_id
    )
    return templates.TemplateResponse(
        request, "orders_table.html", {"orders": orders}
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_web_orders.py -v`
Expected: all 5 tests PASS

- [ ] **Step 7: Run the full suite + ruff**

Run: `pytest -q` (no regressions) and `ruff check .` (clean).

- [ ] **Step 8: Commit**

```bash
git add app/api/routes/web.py app/api/templates/orders_list.html app/api/templates/orders_table.html tests/test_web_orders.py
git commit -m "feat: order list page with HTMX-filtered table"
```

---

### Task 4: Order detail page (`/orders/{id}`)

**Files:**
- Modify: `app/api/routes/web.py` (add the route)
- Create: `app/api/templates/order_detail.html`
- Test: `tests/test_web_order_detail.py`

**Interfaces:**
- Consumes: `get_current_user_web` (Task 2); `get_order_detail_for_user`,
  `get_order_history` (Task 2, from `app.application.order_queries`); `router`,
  `templates` (Task 1/3, same `app/api/routes/web.py` file).
- Produces: nothing consumed elsewhere — final task of this plan.

- [ ] **Step 1: Write the failing tests — `tests/test_web_order_detail.py`**

```python
import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import Order, User, WorkflowEvent
from app.api.deps import get_db
from app.api.main import create_app
from app.application.auth import hash_password
from app.domain.models import OrderState


@pytest.fixture()
def client(db_session):
    app = create_app()

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, db_session, role, username="user1"):
    user = User(
        username=username, full_name=username, role=role,
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(user)
    db_session.commit()
    client.post("/login", data={"username": username, "password": "s3cret!"})
    return user


def test_order_detail_admin_sees_any_order_with_history(client, db_session):
    _login(client, db_session, "admin")
    order = Order(external_order_id="DJ1", state=OrderState.CLAIMED_IMPORTED.value)
    db_session.add(order)
    db_session.commit()
    db_session.add(
        WorkflowEvent(order_id=order.id, from_state="DISCOVERED", to_state="CLAIMED_IMPORTED")
    )
    db_session.commit()

    resp = client.get(f"/orders/{order.id}")

    assert resp.status_code == 200
    assert "DJ1" in resp.text
    assert "CLAIMED_IMPORTED" in resp.text


def test_order_detail_designer_without_assignment_gets_404(client, db_session):
    _login(client, db_session, "designer")
    order = Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value)
    db_session.add(order)
    db_session.commit()

    resp = client.get(f"/orders/{order.id}")

    assert resp.status_code == 404


def test_order_detail_invalid_id_returns_404(client, db_session):
    _login(client, db_session, "admin")

    resp = client.get("/orders/not-a-real-uuid")

    assert resp.status_code == 404


def test_order_detail_requires_login_redirects_to_login(client, db_session):
    order = Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value)
    db_session.add(order)
    db_session.commit()

    resp = client.get(f"/orders/{order.id}", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_order_detail.py -v`
Expected: FAIL — `/orders/{id}` doesn't exist yet (matches nothing, or hits `/orders`
routing incorrectly; either way, 404/error rather than the expected behavior)

- [ ] **Step 3: Create `app/api/templates/order_detail.html`**

```html
{% extends "base.html" %}
{% block title %}Đơn {{ order.external_order_id }}{% endblock %}
{% block content %}
<h1>Đơn {{ order.external_order_id }}</h1>
<p>Trạng thái hiện tại: <strong>{{ order.state }}</strong></p>
<p>Batch: {{ order.batch_id or "-" }}</p>
<p>Tạo lúc: {{ order.created_at }}</p>

<h2>Lịch sử</h2>
<table>
  <thead><tr><th>Thời gian</th><th>Từ</th><th>Đến</th></tr></thead>
  <tbody>
    {% for event in history %}
    <tr><td>{{ event.created_at }}</td><td>{{ event.from_state or "-" }}</td><td>{{ event.to_state }}</td></tr>
    {% else %}
    <tr><td colspan="3">Chưa có lịch sử.</td></tr>
    {% endfor %}
  </tbody>
</table>
<p><a href="/orders">← Quay lại danh sách</a></p>
{% endblock %}
```

- [ ] **Step 4: Add the route to `app/api/routes/web.py`**

Read the current file first (Tasks 1 and 3 already modified it). Update the two import
lines that already reference `fastapi` and `app.application.order_queries` (added by
Tasks 1 and 3) to include the new names — don't add a second, separate `from fastapi
import ...` or `from app.application.order_queries import ...` line for the same
module:

```python
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
```
```python
from app.application.order_queries import (
    get_order_detail_for_user,
    get_order_history,
    list_orders_for_user,
)
```

Then add, after `orders_table`:

```python
@router.get("/orders/{order_id}")
def order_detail(
    request: Request,
    order_id: str,
    user: User = Depends(get_current_user_web),
    db: Session = Depends(get_db),
):
    order = get_order_detail_for_user(db, user, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    history = get_order_history(db, order_id)
    return templates.TemplateResponse(
        request,
        "order_detail.html",
        {"user": user, "order": order, "history": history},
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_web_order_detail.py -v`
Expected: all 4 tests PASS

- [ ] **Step 6: Run the full suite + ruff**

Run: `pytest -q` (no regressions) and `ruff check .` (clean).

- [ ] **Step 7: Commit**

```bash
git add app/api/routes/web.py app/api/templates/order_detail.html tests/test_web_order_detail.py
git commit -m "feat: order detail page with workflow event history"
```

---

## Self-review notes

- **Spec coverage:** §2 (routes) -> Tasks 1/3/4; §3 (auth dependency) -> Task 2 Steps
  5-6; §4 (query functions) -> Task 2 Steps 1-4; §5 (templates) -> all 4 tasks'
  template files; §6 (testing) -> every task's test file covers its own bullet from the
  spec's testing section exactly.
- **Placeholder scan:** no TODO/TBD; every step has complete code.
- **Type consistency:** `list_orders_for_user`/`get_order_detail_for_user`/
  `get_order_history` signatures in Task 2 match exactly what Task 3/4's routes call.
  `get_current_user_web`/`WebAuthRedirect` names match between Task 2's definition and
  Task 3/4's imports. `router`/`templates` from Task 1 are reused (not recreated) by
  Tasks 2-4.
- **Scope check:** this plan is display-only (no state-changing actions) — matches the
  approved spec scope; C2-C5 actions are later phases.
- **Deliberate deviation from spec §5's `orders_list.html` description:** the spec
  mentions a `designer_id` select "admin only" in the filter form; Task 3's actual
  template omits it (backend support still exists via `list_orders_for_user`'s
  `designer_id` param, per Task 2, and `/orders/table` still accepts the query param —
  only the `<select>` control itself is skipped). Reason: no `Assignment` rows exist
  anywhere yet (Phase 5/C2 isn't built), so a designer dropdown would have nothing
  meaningful to filter by right now — pure YAGNI, not a capability gap. Trivial to add
  the `<select>` once Phase 5 makes it useful; not worth the template complexity today.

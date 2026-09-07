# Frontend Platform Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Jinja2+HTMX+Alpine web UI (Phase 4) with a React + TypeScript +
Vite + Tailwind CSS single-page app, reaching feature parity (login, order list/detail,
refresh, Printerval login flow) with zero business-logic change.

**Architecture:** New JSON API layer (`app/api/routes/orders_api.py`) thinly wraps the
existing `order_queries.py`/`crawl.py`/`playwright_support` application layer → new
`frontend/` Vite project consumes it via same-origin `fetch` (session cookie, no CORS) →
FastAPI serves the built SPA as static files in prod, Vite dev server proxies `/api` in
dev → old `web.py`/`templates/` deleted once parity is reached.

**Tech Stack:** React 18+, TypeScript, Vite, Tailwind CSS v4, react-router-dom, Vitest +
React Testing Library. Backend: FastAPI (existing), Pydantic v2.

**Spec:** `docs/superpowers/specs/2026-09-07-frontend-platform-migration-design.md`

## Global Constraints

- Session cookie auth unchanged (httponly, samesite=lax) — no JWT/OAuth (claude.md §4).
- Business logic/state transitions stay in `application/`/`domain/` — the new JSON API
  and React are presentation-only, no logic duplicated client-side (claude.md §4/§10).
- No new state-management library (Redux/React Query) — plain `fetch` + hooks (spec §2,
  YAGNI ruling).
- `frontend/` is a real npm project, NOT an Artifact — no CDN-allowlist constraints
  apply; install real dependencies via `npm install`.
- Old Jinja2 UI and new React UI never run "in parallel" as two supported UIs — the
  deletion task (Task 6) happens in this same plan, not deferred.

---

### Task 1: JSON API endpoints (`orders_api.py`)

**Files:**
- Create: `app/adapters/printerval/login_session.py` (extracted module-level
  `_login_session` state, shared by the new API — avoids duplicating it if `web.py`
  still exists mid-plan)
- Create: `app/api/routes/orders_api.py`
- Modify: `app/api/main.py` (register the new router)
- Test: `tests/test_orders_api.py`

**Interfaces:**
- Consumes: `list_orders_for_user`, `get_order_detail_for_user`, `get_order_history`
  (`app/application/order_queries.py`, unchanged signatures), `run_crawl_cycle`
  (`app/workers/crawl_tasks.py`), `DiscoverFailedError` (`app/application/crawl.py`),
  `open_playwright_session`/`close_playwright_session`/`playwright_session`
  (`app/adapters/playwright_support.py`), `get_current_user`/`require_role`
  (`app/api/deps.py` — already exist, unchanged).
- Produces: `GET /api/orders`, `GET /api/orders/{id}`, `POST /api/orders/refresh`,
  `GET /api/printerval-login/status`, `POST /api/printerval-login/start`,
  `POST /api/printerval-login/done` — exact response shapes below, consumed by Task 4/5.

- [ ] **Step 1: Extract the login-session global**

Create `app/adapters/printerval/login_session.py`:

```python
from __future__ import annotations

from app.adapters.playwright_support import close_playwright_session, open_playwright_session
from app.adapters.printerval.playwright_adapter import ADMIN_URL

# Module-level state for the interactive "log in to Printerval" flow: one admin, one
# browser window, opened by one request and closed by a later one — a plain global is
# enough for this single-operator, rare, admin-only action. None means no interactive
# login window is currently open. Extracted from web.py so both the old Jinja2 routes
# (until Task 6 deletes them) and the new JSON API can share the same live session
# instead of each holding a separate, inconsistent one.
_login_session: dict | None = None


def is_session_open() -> bool:
    global _login_session
    if _login_session is not None:
        try:
            _ = _login_session["context"].pages  # cheap liveness check
        except Exception:
            _login_session = None
    return _login_session is not None


def start_session() -> None:
    global _login_session
    if not is_session_open():
        playwright_cm, context, page = open_playwright_session()
        page.goto(ADMIN_URL)
        _login_session = {"playwright_cm": playwright_cm, "context": context}


def close_session() -> None:
    global _login_session
    if _login_session is not None:
        close_playwright_session(_login_session["playwright_cm"], _login_session["context"])
        _login_session = None
```

- [ ] **Step 2: Update `web.py` to use the extracted module** (keeps it working until Task 6)

In `app/api/routes/web.py`, replace the module-level `_login_session = None` line and
the 3 route bodies' direct manipulation of it:

```python
from app.adapters.printerval import login_session
```

Replace `printerval_login_page`'s context dict value `_login_session is not None` with
`login_session.is_session_open()`. Replace `printerval_login_start`'s body (everything
between the docstring and `return RedirectResponse`) with `login_session.start_session()`.
Replace `printerval_login_done`'s body with `login_session.close_session()`. Remove the
now-unused `global _login_session`, `open_playwright_session`, `close_playwright_session`,
`ADMIN_URL` imports from `web.py` if no longer referenced elsewhere in that file (check
before removing — `playwright_session` and `PlaywrightPrintervalAdapter` are still used
by `orders_refresh`).

- [ ] **Step 3: Write `app/api/routes/orders_api.py`**

```python
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.adapters.playwright_support import playwright_session
from app.adapters.printerval import login_session
from app.adapters.printerval.playwright_adapter import PlaywrightPrintervalAdapter
from app.api.deps import get_current_user, get_db, require_role
from app.application.crawl import DiscoverFailedError
from app.application.order_queries import (
    get_order_detail_for_user,
    get_order_history,
    list_orders_for_user,
)
from app.workers.crawl_tasks import run_crawl_cycle

router = APIRouter()


class OrderSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    external_order_id: str
    state: str
    batch_id: uuid.UUID | None
    sku: str | None
    thumbnail_url: str | None
    deadline_at_ext: datetime | None
    created_at: datetime


class OrdersListResponse(BaseModel):
    orders: list[OrderSummaryOut]


class OrderDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    external_order_id: str
    state: str
    batch_id: uuid.UUID | None
    product_name: str | None
    thumbnail_url: str | None
    sku: str | None
    product_category: str | None
    product_variants: list[dict] | None
    has_template: bool
    multiple_design: bool
    double_sided: bool
    priority_label: str | None
    deadline_at_ext: datetime | None
    note_outsource: str
    order_note: str
    custom_config: dict | None
    design_tool_url: str | None
    created_at: datetime


class WorkflowEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    created_at: datetime
    from_state: str | None
    to_state: str


class OrderDetailResponse(BaseModel):
    order: OrderDetailOut
    history: list[WorkflowEventOut]


class RefreshResponse(BaseModel):
    flash: str
    summary: dict | None = None


class PrintervalLoginStatus(BaseModel):
    session_open: bool


@router.get("/orders", response_model=OrdersListResponse)
def api_orders_list(
    status_filter: str | None = None,
    batch_id: str | None = None,
    designer_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    orders = list_orders_for_user(
        db, user, status=status_filter, batch_id=batch_id, designer_id=designer_id
    )
    return OrdersListResponse(orders=[OrderSummaryOut.model_validate(o) for o in orders])


@router.get("/orders/{order_id}", response_model=OrderDetailResponse)
def api_order_detail(
    order_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    order = get_order_detail_for_user(db, user, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    history = get_order_history(db, order_id)
    return OrderDetailResponse(
        order=OrderDetailOut.model_validate(order),
        history=[WorkflowEventOut.model_validate(e) for e in history],
    )


@router.post("/orders/refresh", response_model=RefreshResponse)
def api_orders_refresh(
    user: User = Depends(require_role("admin")), db: Session = Depends(get_db)
):
    try:
        with playwright_session() as page:
            adapter = PlaywrightPrintervalAdapter(page=page)
            summary = run_crawl_cycle(db, adapter)
        flash = (
            f"Đã crawl xong: {summary['discovered']} đơn mới, "
            f"{summary['imported']} đơn nhập thành công"
        )
        failed_total = summary["failed_claim"] + summary["failed_import"]
        if failed_total:
            flash += f", {failed_total} lỗi (xem dead_letters)"
        flash += "."
        return RefreshResponse(flash=flash, summary=summary)
    except DiscoverFailedError:
        db.rollback()
        flash = (
            "Crawl thất bại khi tìm đơn mới — có thể site đổi giao diện hoặc bộ lọc "
            "sai. Xem bảng dead_letters (source=crawl.discover_waiting_orders) để "
            "biết chi tiết lỗi thật."
        )
        return RefreshResponse(flash=flash)
    except Exception:
        db.rollback()
        flash = "Crawl thất bại — kiểm tra Chrome profile đã đăng nhập Printerval chưa."
        return RefreshResponse(flash=flash)


@router.get("/printerval-login/status", response_model=PrintervalLoginStatus)
def api_printerval_login_status(user: User = Depends(require_role("admin"))):
    return PrintervalLoginStatus(session_open=login_session.is_session_open())


@router.post("/printerval-login/start", response_model=PrintervalLoginStatus)
def api_printerval_login_start(user: User = Depends(require_role("admin"))):
    login_session.start_session()
    return PrintervalLoginStatus(session_open=True)


@router.post("/printerval-login/done", response_model=PrintervalLoginStatus)
def api_printerval_login_done(user: User = Depends(require_role("admin"))):
    login_session.close_session()
    return PrintervalLoginStatus(session_open=False)
```

Note the query param is named `status_filter` (not `status`) to avoid shadowing
FastAPI's `status` module imported for `HTTPException` — `list_orders_for_user`'s
`status` keyword argument is passed `status_filter`'s value, so the external query
string stays `?status=...` from the frontend's point of view... **actually check**:
FastAPI binds the query parameter by the Python parameter's name unless a `Query(alias=...)`
is given. To keep the wire-level query param named `status` (matching Task 4's frontend
code below) while not shadowing the `status` module, add the alias explicitly:

```python
from fastapi import Query
...
def api_orders_list(
    status_filter: str | None = Query(default=None, alias="status"),
    ...
```

- [ ] **Step 4: Register the router in `app/api/main.py`**

Add `from app.api.routes import orders_api as orders_api_routes` and
`app.include_router(orders_api_routes.router, prefix="/api")` alongside the existing
`include_router` calls (order doesn't matter relative to `web_routes`, but must be
before Task 2's catch-all SPA route, which doesn't exist yet at this point in the plan).

- [ ] **Step 5: Write the tests**

Create `tests/test_orders_api.py`:

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
    client.post("/api/login", json={"username": username, "password": "s3cret!"})
    return user


def test_api_orders_list_returns_all_orders_for_admin(client, db_session):
    _login(client, db_session, "admin")
    db_session.add(Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value))
    db_session.commit()

    resp = client.get("/api/orders")

    assert resp.status_code == 200
    ids = [o["external_order_id"] for o in resp.json()["orders"]]
    assert ids == ["DJ1"]


def test_api_orders_list_requires_auth(client):
    resp = client.get("/api/orders")
    assert resp.status_code == 401


def test_api_orders_list_filters_by_status(client, db_session):
    _login(client, db_session, "admin")
    db_session.add(Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value))
    db_session.add(Order(external_order_id="DJ2", state=OrderState.CLAIMED_IMPORTED.value))
    db_session.commit()

    resp = client.get("/api/orders", params={"status": OrderState.DISCOVERED.value})

    ids = [o["external_order_id"] for o in resp.json()["orders"]]
    assert ids == ["DJ1"]


def test_api_order_detail_returns_404_for_missing_order(client, db_session):
    _login(client, db_session, "admin")
    resp = client.get("/api/orders/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_api_order_detail_returns_order_and_history(client, db_session):
    _login(client, db_session, "admin")
    order = Order(
        external_order_id="DJ1", state=OrderState.DISCOVERED.value, product_name="Test Mug"
    )
    db_session.add(order)
    db_session.commit()

    resp = client.get(f"/api/orders/{order.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["order"]["product_name"] == "Test Mug"
    assert body["history"] == []


def test_api_orders_refresh_requires_admin(client, db_session):
    _login(client, db_session, "designer")
    resp = client.post("/api/orders/refresh")
    assert resp.status_code == 403


def test_api_printerval_login_status_requires_admin(client, db_session):
    _login(client, db_session, "designer")
    resp = client.get("/api/printerval-login/status")
    assert resp.status_code == 403


def test_api_printerval_login_status_defaults_closed(client, db_session):
    _login(client, db_session, "admin")
    resp = client.get("/api/printerval-login/status")
    assert resp.status_code == 200
    assert resp.json() == {"session_open": False}
```

- [ ] **Step 6: Run tests, lint, commit**

Run: `.venv/bin/pytest tests/test_orders_api.py -v` — all pass.
Run: `.venv/bin/pytest tests/ -q` — full suite still green (old `web.py`/`test_web_orders.py`
untouched in behavior, still pass).
Run: `.venv/bin/ruff check app tests`.

```bash
git add app/adapters/printerval/login_session.py app/api/routes/orders_api.py app/api/routes/web.py app/api/main.py tests/test_orders_api.py
git commit -m "feat(api): add JSON orders API (orders list/detail/refresh, printerval-login) alongside existing web routes"
```

---

### Task 2: Vite + React + TS + Tailwind scaffold, FastAPI static serving

**Files:**
- Create: `frontend/` (new Vite project — exact files below)
- Modify: `app/api/main.py` (SPA static-file fallback)
- Modify: `.gitignore` (add `frontend/node_modules/`, `frontend/dist/`)

**Interfaces:**
- Produces: a buildable `frontend/` project (`npm run build` → `frontend/dist/`) that
  Task 3-5 add pages to, and that `app/api/main.py` serves in prod.

- [ ] **Step 1: Scaffold the Vite project**

From the repo root:

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install react-router-dom
npm install -D tailwindcss @tailwindcss/vite
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```

- [ ] **Step 2: Wire Tailwind v4 into Vite**

Replace `frontend/vite.config.ts` with:

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.ts',
  },
})
```

Replace the contents of `frontend/src/index.css` with just:

```css
@import "tailwindcss";
```

Create `frontend/src/setupTests.ts`:

```ts
import '@testing-library/jest-dom'
```

Add a `"test": "vitest run"` script to `frontend/package.json`'s `"scripts"` block
(alongside the existing `dev`/`build`/`preview` scripts create-vite already added).

- [ ] **Step 3: Replace the default template content with a minimal placeholder**

Replace `frontend/src/App.tsx`:

```tsx
function App() {
  return (
    <div className="p-6">
      <h1 className="text-xl font-bold">Pinterval Ops Dashboard</h1>
    </div>
  )
}

export default App
```

Delete `frontend/src/App.css` and its import in `App.tsx` if create-vite generated one
(the template above has no such import — remove the file if present since it's now
unused). Keep `frontend/src/main.tsx` as create-vite generated it (renders `<App />`
into `#root`, imports `./index.css`).

- [ ] **Step 4: Build and verify**

Run: `cd frontend && npm run build` — expect a `frontend/dist/` directory with
`index.html` and an `assets/` subfolder. Run: `cd frontend && npm run test` — expect
"No test files found" is NOT a failure at this step (no tests exist yet); this step
only confirms the vitest config itself doesn't error out (run `npx vitest run --passWithNoTests`
if the bare command exits non-zero on zero tests).

- [ ] **Step 5: Serve the built SPA from FastAPI**

Add to `.gitignore` (repo root): two new lines, `frontend/node_modules/` and
`frontend/dist/` (build artifacts, never committed — same convention as
`chrome-profile/`).

Edit `app/api/main.py`:

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.deps import WebAuthRedirect
from app.api.routes import auth as auth_routes
from app.api.routes import health as health_routes
from app.api.routes import orders_api as orders_api_routes
from app.api.routes import protected_example
from app.api.routes import web as web_routes

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(title="Pinterval Ops Dashboard")
    app.include_router(health_routes.router, prefix="/api")
    app.include_router(auth_routes.router, prefix="/api")
    app.include_router(orders_api_routes.router, prefix="/api")
    app.include_router(protected_example.router, prefix="/api")
    app.include_router(web_routes.router)

    @app.exception_handler(WebAuthRedirect)
    def _redirect_to_login(request, exc):
        return RedirectResponse("/login", status_code=302)

    if FRONTEND_DIST.exists():
        app.mount(
            "/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="spa-assets"
        )

        @app.get("/spa/{full_path:path}")
        def spa_fallback(full_path: str):
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
```

`ponytail: mounted under /spa/ for this task only, not / — the old web.py still owns /,
/orders, /login etc. at this point in the plan. Task 6 removes web_routes and moves the
SPA fallback to catch everything at /, after React reaches parity.` This is a deliberate
intermediate state, not a design mistake — do not "fix" it before Task 6.

- [ ] **Step 6: Verify and commit**

Run: `.venv/bin/uvicorn app.api.main:app --port 8000 &` then
`curl -s http://localhost:8000/spa/anything | grep -o '<title>[^<]*'` — expect it to
print whatever `<title>` Vite's default `index.html` has (confirms the static file is
served). Kill the uvicorn process afterward.

Run: `.venv/bin/pytest tests/ -q` — full suite still green (no Python business logic
touched this task).

```bash
git add frontend/ app/api/main.py .gitignore
git commit -m "feat(frontend): scaffold React+TS+Vite+Tailwind, serve build from FastAPI under /spa"
```

---

### Task 3: Auth (API client, AuthContext, LoginPage, ProtectedRoute)

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/auth/AuthContext.tsx`
- Create: `frontend/src/auth/ProtectedRoute.tsx`
- Create: `frontend/src/pages/LoginPage.tsx`
- Create: `frontend/src/App.tsx` (replaces Task 2's placeholder)
- Test: `frontend/src/pages/LoginPage.test.tsx`

**Interfaces:**
- Consumes: `POST /api/login` (`{username, password}` -> `{id, role}`),
  `POST /api/logout`, `GET /api/me` (-> `{id, role, full_name}`) — Task 1's spec §3,
  unchanged from Phase 1.
- Produces: `useAuth()` hook (`{user, login, logout, loading}`) used by Task 4/5;
  `<ProtectedRoute>` wrapper component.

- [ ] **Step 1: API client**

Create `frontend/src/api/client.ts`:

```ts
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    ...init,
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  if (!resp.ok) {
    let message = resp.statusText
    try {
      const body = await resp.json()
      message = body.detail ?? message
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new ApiError(resp.status, message)
  }
  if (resp.status === 204) return undefined as T
  return resp.json() as Promise<T>
}
```

- [ ] **Step 2: Auth context**

Create `frontend/src/auth/AuthContext.tsx`:

```tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { apiFetch, ApiError } from '../api/client'

export type User = { id: string; role: 'admin' | 'designer'; full_name: string }

type AuthState = {
  user: User | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    apiFetch<User>('/me')
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  async function login(username: string, password: string) {
    await apiFetch('/login', { method: 'POST', body: JSON.stringify({ username, password }) })
    const me = await apiFetch<User>('/me')
    setUser(me)
  }

  async function logout() {
    await apiFetch('/logout', { method: 'POST' })
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export { ApiError }
```

- [ ] **Step 3: Protected route wrapper**

Create `frontend/src/auth/ProtectedRoute.tsx`:

```tsx
import { Navigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from './AuthContext'

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="p-6">Đang tải...</div>
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}
```

- [ ] **Step 4: Login page**

Create `frontend/src/pages/LoginPage.tsx`:

```tsx
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth, ApiError } from '../auth/AuthContext'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await login(username, password)
      navigate('/orders')
    } catch (err) {
      setError(err instanceof ApiError ? 'Sai tên đăng nhập hoặc mật khẩu' : 'Lỗi kết nối')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="max-w-sm mx-auto mt-20 p-6 space-y-4">
      <h1 className="text-xl font-bold">Đăng nhập</h1>
      {error && <p className="text-red-600">{error}</p>}
      <input
        className="border w-full p-2"
        placeholder="Tên đăng nhập"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
      />
      <input
        className="border w-full p-2"
        type="password"
        placeholder="Mật khẩu"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <button className="bg-blue-600 text-white w-full p-2" type="submit">
        Đăng nhập
      </button>
    </form>
  )
}
```

- [ ] **Step 5: App shell with routing (placeholder routes for Task 4/5)**

Replace `frontend/src/App.tsx`:

```tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { LoginPage } from './pages/LoginPage'

function App() {
  return (
    <BrowserRouter basename="/spa">
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/orders"
            element={
              <ProtectedRoute>
                <div className="p-6">Danh sách đơn (Task 4)</div>
              </ProtectedRoute>
            }
          />
          <Route path="/" element={<Navigate to="/orders" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
```

`ponytail: basename="/spa" matches Task 2's temporary mount path; Task 6 removes it once
the SPA takes over /.`

- [ ] **Step 6: Test**

Create `frontend/src/pages/LoginPage.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { LoginPage } from './LoginPage'

describe('LoginPage', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({ ok: false, status: 401, statusText: 'Unauthorized' })
        }
        if (url.includes('/api/login')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({}) })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      })
    )
  })

  it('renders the login form', async () => {
    render(
      <BrowserRouter>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </BrowserRouter>
    )
    await waitFor(() => expect(screen.getByText('Đăng nhập')).toBeInTheDocument())
    expect(screen.getByPlaceholderText('Tên đăng nhập')).toBeInTheDocument()
  })

  it('shows an error on failed login', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/api/me')) {
        return Promise.resolve({ ok: false, status: 401, statusText: 'Unauthorized' })
      }
      if (url.includes('/api/login')) {
        return Promise.resolve({
          ok: false,
          status: 401,
          statusText: 'Unauthorized',
          json: async () => ({ detail: 'Invalid credentials' }),
        })
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`))
    })

    render(
      <BrowserRouter>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </BrowserRouter>
    )
    await waitFor(() => screen.getByPlaceholderText('Tên đăng nhập'))
    fireEvent.change(screen.getByPlaceholderText('Tên đăng nhập'), { target: { value: 'x' } })
    fireEvent.change(screen.getByPlaceholderText('Mật khẩu'), { target: { value: 'y' } })
    fireEvent.click(screen.getByText('Đăng nhập'))

    await waitFor(() =>
      expect(screen.getByText('Sai tên đăng nhập hoặc mật khẩu')).toBeInTheDocument()
    )
  })
})
```

Run: `cd frontend && npm run test` — both tests pass.
Run: `cd frontend && npm run build` — still builds clean (TypeScript compiles).

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): auth context, login page, protected routing"
```

---

### Task 4: Orders list page (table, filters, Refresh, link to Printerval login)

**Files:**
- Create: `frontend/src/pages/OrdersListPage.tsx`
- Create: `frontend/src/pages/PrintervalLoginPage.tsx`
- Modify: `frontend/src/App.tsx` (wire the two new routes, replace the Task 3 placeholder)
- Test: `frontend/src/pages/OrdersListPage.test.tsx`

**Interfaces:**
- Consumes: `GET /api/orders?status=&batch_id=`, `POST /api/orders/refresh`,
  `GET /api/printerval-login/status`, `POST /api/printerval-login/start`,
  `POST /api/printerval-login/done` (Task 1).
- Produces: `/orders` and `/printerval-login` routes, used by Task 6's parity check.

- [ ] **Step 1: Orders list page**

Create `frontend/src/pages/OrdersListPage.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch } from '../api/client'
import { useAuth } from '../auth/AuthContext'

type OrderSummary = {
  id: string
  external_order_id: string
  state: string
  batch_id: string | null
  sku: string | null
  thumbnail_url: string | null
  deadline_at_ext: string | null
  created_at: string
}

export function OrdersListPage() {
  const { user } = useAuth()
  const [orders, setOrders] = useState<OrderSummary[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [flash, setFlash] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  async function loadOrders() {
    const params = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : ''
    const data = await apiFetch<{ orders: OrderSummary[] }>(`/orders${params}`)
    setOrders(data.orders)
  }

  useEffect(() => {
    loadOrders()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter])

  async function handleRefresh() {
    setRefreshing(true)
    try {
      const result = await apiFetch<{ flash: string }>('/orders/refresh', { method: 'POST' })
      setFlash(result.flash)
      await loadOrders()
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <div className="p-6">
      <h1 className="text-xl font-bold mb-4">Đơn hàng</h1>
      {flash && <p className="mb-4 font-semibold">{flash}</p>}
      {user?.role === 'admin' && (
        <div className="mb-4 space-x-4">
          <button
            className="bg-blue-600 text-white px-3 py-1 disabled:opacity-50"
            onClick={handleRefresh}
            disabled={refreshing}
          >
            {refreshing ? 'Đang crawl...' : 'Refresh'}
          </button>
          <Link className="underline" to="/printerval-login">
            Đăng nhập Printerval
          </Link>
        </div>
      )}
      <select
        className="border p-1 mb-4"
        value={statusFilter}
        onChange={(e) => setStatusFilter(e.target.value)}
      >
        <option value="">Tất cả</option>
        <option value="DISCOVERED">DISCOVERED</option>
        <option value="CLAIMED_IMPORTED">CLAIMED_IMPORTED</option>
      </select>
      <table className="w-full border-collapse">
        <thead>
          <tr className="text-left border-b">
            <th>Ảnh</th>
            <th>Mã đơn</th>
            <th>SKU</th>
            <th>Trạng thái</th>
            <th>Deadline</th>
          </tr>
        </thead>
        <tbody>
          {orders.length === 0 && (
            <tr>
              <td colSpan={5}>Không có đơn nào.</td>
            </tr>
          )}
          {orders.map((o) => (
            <tr key={o.id} className="border-b">
              <td>{o.thumbnail_url && <img src={o.thumbnail_url} alt="" className="h-10" />}</td>
              <td>
                <Link className="underline" to={`/orders/${o.id}`}>
                  {o.external_order_id}
                </Link>
              </td>
              <td>{o.sku ?? '-'}</td>
              <td>{o.state}</td>
              <td>{o.deadline_at_ext ?? '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

`ponytail: status filter dropdown hard-codes 2 of the 10 OrderState values as a starting
point (parity minimum) — a follow-up sub-project can fetch the full enum from the API if
the dropdown needs to cover every state; not needed for this migration's parity goal.`

- [ ] **Step 2: Printerval login page**

Create `frontend/src/pages/PrintervalLoginPage.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiFetch } from '../api/client'

export function PrintervalLoginPage() {
  const [sessionOpen, setSessionOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    apiFetch<{ session_open: boolean }>('/printerval-login/status')
      .then((r) => setSessionOpen(r.session_open))
      .finally(() => setLoading(false))
  }, [])

  async function handleStart() {
    const r = await apiFetch<{ session_open: boolean }>('/printerval-login/start', {
      method: 'POST',
    })
    setSessionOpen(r.session_open)
  }

  async function handleDone() {
    await apiFetch('/printerval-login/done', { method: 'POST' })
    navigate('/orders')
  }

  if (loading) return <div className="p-6">Đang tải...</div>

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-xl font-bold">Đăng nhập Printerval</h1>
      {sessionOpen ? (
        <button className="bg-green-600 text-white px-3 py-1" onClick={handleDone}>
          Done
        </button>
      ) : (
        <button className="bg-blue-600 text-white px-3 py-1" onClick={handleStart}>
          Mở Chrome để đăng nhập
        </button>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Wire routes**

In `frontend/src/App.tsx`, replace the placeholder `/orders` route element with
`<OrdersListPage />` and add a `/printerval-login` route, both inside `<ProtectedRoute>`:

```tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { LoginPage } from './pages/LoginPage'
import { OrdersListPage } from './pages/OrdersListPage'
import { PrintervalLoginPage } from './pages/PrintervalLoginPage'

function App() {
  return (
    <BrowserRouter basename="/spa">
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/orders"
            element={
              <ProtectedRoute>
                <OrdersListPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/printerval-login"
            element={
              <ProtectedRoute>
                <PrintervalLoginPage />
              </ProtectedRoute>
            }
          />
          <Route path="/" element={<Navigate to="/orders" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
```

- [ ] **Step 4: Test**

Create `frontend/src/pages/OrdersListPage.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { OrdersListPage } from './OrdersListPage'

describe('OrdersListPage', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: '1', role: 'admin', full_name: 'Admin' }),
          })
        }
        if (url.includes('/api/orders')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              orders: [
                {
                  id: 'a1',
                  external_order_id: 'DJ1',
                  state: 'DISCOVERED',
                  batch_id: null,
                  sku: 'SKU1',
                  thumbnail_url: null,
                  deadline_at_ext: null,
                  created_at: '2026-01-01T00:00:00',
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      })
    )
  })

  it('renders orders from the API', async () => {
    render(
      <BrowserRouter>
        <AuthProvider>
          <OrdersListPage />
        </AuthProvider>
      </BrowserRouter>
    )
    await waitFor(() => expect(screen.getByText('DJ1')).toBeInTheDocument())
    expect(screen.getByText('SKU1')).toBeInTheDocument()
  })
})
```

Run: `cd frontend && npm run test` — passes. Run: `cd frontend && npm run build` —
still builds clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): orders list page (filter, refresh, printerval-login link)"
```

---

### Task 5: Order detail page

**Files:**
- Create: `frontend/src/pages/OrderDetailPage.tsx`
- Modify: `frontend/src/App.tsx` (add `/orders/:id` route)
- Test: `frontend/src/pages/OrderDetailPage.test.tsx`

**Interfaces:**
- Consumes: `GET /api/orders/{id}` (Task 1's `OrderDetailResponse` shape).

- [ ] **Step 1: Order detail page**

Create `frontend/src/pages/OrderDetailPage.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiFetch } from '../api/client'

type OrderDetail = {
  id: string
  external_order_id: string
  state: string
  product_name: string | null
  thumbnail_url: string | null
  sku: string | null
  product_category: string | null
  product_variants: { name: string; value: string }[] | null
  has_template: boolean
  multiple_design: boolean
  double_sided: boolean
  deadline_at_ext: string | null
  note_outsource: string
  order_note: string
  custom_config: { original: { key: string; value: string }[] } | null
  design_tool_url: string | null
  created_at: string
}

type WorkflowEvent = { created_at: string; from_state: string | null; to_state: string }

export function OrderDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [order, setOrder] = useState<OrderDetail | null>(null)
  const [history, setHistory] = useState<WorkflowEvent[]>([])

  useEffect(() => {
    if (!id) return
    apiFetch<{ order: OrderDetail; history: WorkflowEvent[] }>(`/orders/${id}`).then((data) => {
      setOrder(data.order)
      setHistory(data.history)
    })
  }, [id])

  if (!order) return <div className="p-6">Đang tải...</div>

  return (
    <div className="p-6">
      <h1 className="text-xl font-bold mb-4">Đơn {order.external_order_id}</h1>
      {order.thumbnail_url && (
        <img src={order.thumbnail_url} alt="" className="max-h-48 mb-4" />
      )}
      <p>Sản phẩm: {order.product_name ?? '-'}</p>
      <p>SKU: {order.sku ?? '-'}</p>
      <p>Category: {order.product_category ?? '-'}</p>
      {order.product_variants && order.product_variants.length > 0 && (
        <ul className="list-disc pl-5">
          {order.product_variants.map((v, i) => (
            <li key={i}>
              {v.name}: {v.value}
            </li>
          ))}
        </ul>
      )}
      <p>Deadline: {order.deadline_at_ext ?? '-'}</p>
      <p>Template: {order.has_template ? 'Đã có' : 'Chưa có'}</p>
      {order.custom_config && order.custom_config.original.length > 0 && (
        <>
          <h2 className="font-bold mt-4">Custom configuration</h2>
          <table className="border-collapse">
            <tbody>
              {order.custom_config.original.map((entry, i) => (
                <tr key={i}>
                  <td className="pr-4">{entry.key}</td>
                  <td>{entry.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {order.design_tool_url && (
        <p className="mt-4">
          <a
            className="underline"
            href={order.design_tool_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Gen design custom
          </a>
        </p>
      )}
      <p>Note outsource: {order.note_outsource || '-'}</p>
      <p>Order note: {order.order_note || '-'}</p>
      <p>Trạng thái hiện tại: <strong>{order.state}</strong></p>

      <h2 className="font-bold mt-6">Lịch sử</h2>
      <table className="border-collapse w-full">
        <thead>
          <tr className="text-left border-b">
            <th>Thời gian</th>
            <th>Từ</th>
            <th>Đến</th>
          </tr>
        </thead>
        <tbody>
          {history.length === 0 && (
            <tr>
              <td colSpan={3}>Chưa có lịch sử.</td>
            </tr>
          )}
          {history.map((e, i) => (
            <tr key={i} className="border-b">
              <td>{e.created_at}</td>
              <td>{e.from_state ?? '-'}</td>
              <td>{e.to_state}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-4">
        <Link className="underline" to="/orders">
          ← Quay lại danh sách
        </Link>
      </p>
    </div>
  )
}
```

- [ ] **Step 2: Wire the route**

In `frontend/src/App.tsx`, add (inside `<Routes>`, wrapped in `<ProtectedRoute>` like
the others):

```tsx
<Route
  path="/orders/:id"
  element={
    <ProtectedRoute>
      <OrderDetailPage />
    </ProtectedRoute>
  }
/>
```

with `import { OrderDetailPage } from './pages/OrderDetailPage'` added at the top.

- [ ] **Step 3: Test**

Create `frontend/src/pages/OrderDetailPage.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { OrderDetailPage } from './OrderDetailPage'

describe('OrderDetailPage', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('/api/orders/')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              order: {
                id: 'a1',
                external_order_id: 'DJ1',
                state: 'DISCOVERED',
                product_name: 'Test Mug',
                thumbnail_url: null,
                sku: 'SKU1',
                product_category: null,
                product_variants: null,
                has_template: false,
                multiple_design: false,
                double_sided: false,
                deadline_at_ext: null,
                note_outsource: '',
                order_note: '',
                custom_config: null,
                design_tool_url: null,
                created_at: '2026-01-01T00:00:00',
              },
              history: [],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      })
    )
  })

  it('renders order fields', async () => {
    render(
      <MemoryRouter initialEntries={['/orders/a1']}>
        <Routes>
          <Route path="/orders/:id" element={<OrderDetailPage />} />
        </Routes>
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByText('Test Mug')).toBeInTheDocument())
    expect(screen.getByText('SKU1')).toBeInTheDocument()
  })
})
```

Run: `cd frontend && npm run test` — passes. Run: `cd frontend && npm run build`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): order detail page"
```

---

### Task 6: Remove Jinja2 UI, promote SPA to `/`

**Files:**
- Delete: `app/api/routes/web.py`
- Delete: `app/api/templates/` (entire directory)
- Delete: `tests/test_web_orders.py`, `tests/test_web_printerval_login.py`
- Modify: `app/api/main.py` (remove `web_routes` registration, move SPA fallback to `/`)
- Modify: `frontend/src/App.tsx` (remove `basename="/spa"`)
- Modify: `RUNME.md` (update run instructions)

**Interfaces:**
- Consumes: nothing new — this task only removes now-redundant code once Task 3-5
  proved parity.

- [ ] **Step 1: Confirm parity manually**

Run: `.venv/bin/uvicorn app.api.main:app --port 8000 &`, then in a separate terminal
`cd frontend && npm run dev`, open `http://localhost:5173`, log in, confirm the orders
list and detail pages show data equivalent to what `tests/test_web_orders.py` exercised
(same order fields, same Refresh behavior triggering a real crawl attempt — this can
fail against the live site same as before, that's expected/unrelated to this task). Kill
both processes after confirming.

- [ ] **Step 2: Delete the old UI**

```bash
git rm -r app/api/templates
git rm app/api/routes/web.py
git rm tests/test_web_orders.py tests/test_web_printerval_login.py
```

- [ ] **Step 3: Update `app/api/main.py`**

```python
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import auth as auth_routes
from app.api.routes import health as health_routes
from app.api.routes import orders_api as orders_api_routes
from app.api.routes import protected_example

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(title="Pinterval Ops Dashboard")
    app.include_router(health_routes.router, prefix="/api")
    app.include_router(auth_routes.router, prefix="/api")
    app.include_router(orders_api_routes.router, prefix="/api")
    app.include_router(protected_example.router, prefix="/api")

    if FRONTEND_DIST.exists():
        app.mount(
            "/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="spa-assets"
        )

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str):
            if full_path.startswith("api"):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
```

`WebAuthRedirect` and its exception handler are removed — the JSON API's
`get_current_user` (401 `HTTPException`) is now the only auth-failure path; the React
`ProtectedRoute` handles the client-side redirect to `/login`.

- [ ] **Step 4: Update `frontend/src/App.tsx`**

Change `<BrowserRouter basename="/spa">` to `<BrowserRouter>` (no basename — the SPA now
owns `/`).

- [ ] **Step 5: Rebuild, run full suite**

```bash
cd frontend && npm run build && cd ..
.venv/bin/pytest tests/ -q
.venv/bin/ruff check app tests
```

Expect: `app/api/deps.py`'s `WebAuthRedirect`/`get_current_user_web` are now unused by
any route — leave them defined (still exported, harmless) unless `ruff` flags them as
dead code, in which case remove `get_current_user_web` and `WebAuthRedirect` from
`app/api/deps.py` too and re-run the suite.

- [ ] **Step 6: Update `RUNME.md`**

Update the sections describing how to run the web UI: replace any Jinja2-era
instructions ("mở http://localhost:8000/orders") with the two-process dev flow
(`uvicorn` on 8000 + `cd frontend && npm run dev` on 5173, open 5173) and the prod flow
(`cd frontend && npm run build` once, then `uvicorn` alone serves everything from `/`).

- [ ] **Step 7: Commit**

```bash
git add app/api/main.py frontend/src/App.tsx RUNME.md
git commit -m "refactor: remove Jinja2 UI, React SPA now serves / directly"
```

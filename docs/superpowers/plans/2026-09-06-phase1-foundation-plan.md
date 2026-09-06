# Phase 1 — Nền tảng và mô hình dữ liệu — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the project skeleton, Postgres schema, deterministic state machine,
idempotency ledger, and basic role-based auth that every later phase (crawl, allocation,
approval, QC) builds on.

**Architecture:** Python/FastAPI project with a strict `domain/` (pure, no framework
deps) → `application/` (orchestrates domain + DB in one transaction) → `adapters/db/`
(SQLAlchemy models) → `api/` (FastAPI routes, auth) layering, backed by PostgreSQL 16.
No web UI pages yet (Phase 4+); this phase only proves the backend primitives and a JSON
auth API work end-to-end.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2 (pydantic-settings), SQLAlchemy 2.0,
Alembic, PostgreSQL 16, `psycopg` v3 driver, `bcrypt`, `itsdangerous` (signed session
cookie), pytest + httpx (TestClient), ruff.

**Spec:** `docs/superpowers/specs/2026-09-06-web-dashboard-design.md` (architecture) and
`claude.md` (invariants, state model, data model — sections 2, 5, 6, 13).

## Global Constraints

- Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16 (claude.md §4).
- `domain/` must not import FastAPI, SQLAlchemy, Playwright, or any adapter (claude.md
  §13) — it contains only the `OrderState` enum and the transition table.
- Every side-effecting operation needs an idempotency key and an audit record
  (claude.md §2.4).
- No overwrite of history: state transitions append a `workflow_events` row, never
  delete/mutate past events (claude.md §2.8).
- No Telegram, no LLM/agent code in V1 (claude.md §12, roadmap.md §8).
- No new dependency or framework beyond what's listed above unless a later task in this
  plan explicitly introduces it.
- Session cookies: httponly, secure (configurable for local dev), signed — no server-side
  session table in V1 (YAGNI; the signed cookie carries `user_id` + `role`).

---

### Task 1: Project scaffold & tooling

**Files:**
- Create: `pyproject.toml`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.gitignore` (append, don't overwrite — one already exists)
- Create: `README.md`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `app.config.Settings` (Pydantic `BaseSettings` with fields
  `database_url: str`, `secret_key: str`, `cookie_secure: bool`,
  `session_max_age_seconds: int`) and `app.config.get_settings() -> Settings`
  (`lru_cache`d factory). All later tasks read config through `get_settings()`.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "pinterval-ops"
version = "0.1.0"
description = "Web dashboard van hanh noi bo - Pinterval outsource team"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "sqlalchemy>=2.0",
  "alembic>=1.13",
  "psycopg[binary]>=3.1",
  "pydantic>=2.7",
  "pydantic-settings>=2.3",
  "bcrypt>=4.1",
  "itsdangerous>=2.2",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2",
  "httpx>=0.27",
  "ruff>=0.5",
]

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["app*"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]
```

- [ ] **Step 2: Create `docker-compose.yml`**

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: pinterval
    ports:
      - "5432:5432"
    volumes:
      - pinterval_db_data:/var/lib/postgresql/data

volumes:
  pinterval_db_data:
```

- [ ] **Step 3: Create `.env.example`**

```
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pinterval
SECRET_KEY=change-me-in-production
COOKIE_SECURE=true
SESSION_MAX_AGE_SECONDS=43200
```

- [ ] **Step 4: Append to `.gitignore`** (the file already exists with secrets/python/
      browser-profile rules — add a build-artifact section, don't remove existing lines)

```
# build artifacts
*.egg-info/
build/
dist/
.pytest_cache/
.ruff_cache/
```

- [ ] **Step 5: Create `README.md`**

```markdown
# Pinterval Ops Dashboard

Web dashboard nội bộ điều phối order 2D outsource — xem `claude.md` và
`docs/superpowers/specs/2026-09-06-web-dashboard-design.md` để hiểu kiến trúc đầy đủ.

## Chạy local

1. `cp .env.example .env` rồi chỉnh nếu cần.
2. `docker compose up -d db` — chạy Postgres 16 local.
3. `pip install -e ".[dev]"`
4. `alembic upgrade head` — tạo schema.
5. `uvicorn app.api.main:app --reload` — chạy API.

## Test

```bash
docker compose up -d db
createdb -h localhost -U postgres pinterval_test 2>/dev/null || true
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pinterval_test \
  pytest -v
```

## Lint

```bash
ruff check .
```
```

- [ ] **Step 6: Create `app/__init__.py`** (empty file, marks `app` as a package)

- [ ] **Step 7: Create `app/config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/pinterval"
    secret_key: str = "dev-secret-change-me"
    cookie_secure: bool = True
    session_max_age_seconds: int = 60 * 60 * 12


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 8: Write the failing test — `tests/test_config.py`**

```python
from app.config import Settings


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.database_url.startswith("postgresql+psycopg://")
    assert s.cookie_secure is True


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "abc123")
    s = Settings(_env_file=None)
    assert s.secret_key == "abc123"
```

- [ ] **Step 9: Install deps and run the test**

Run: `pip install -e ".[dev]" && pytest tests/test_config.py -v`
Expected: both tests PASS (no DB needed for this task).

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml docker-compose.yml .env.example .gitignore README.md app/__init__.py app/config.py tests/test_config.py
git commit -m "chore: project scaffold, config, docker-compose for local Postgres"
```

---

### Task 2: Domain state machine (pure, no DB)

**Files:**
- Create: `app/domain/__init__.py`
- Create: `app/domain/models.py`
- Create: `app/domain/exceptions.py`
- Create: `app/domain/state_machine.py`
- Test: `tests/test_state_machine.py`

**Interfaces:**
- Consumes: nothing (pure domain layer).
- Produces: `app.domain.models.OrderState` (str Enum with 15 members — see below),
  `app.domain.exceptions.InvalidTransitionError(current, target)`,
  `app.domain.state_machine.validate_transition(current: OrderState, target: OrderState) -> None`
  (raises `InvalidTransitionError` if not allowed). Task 4 imports all three names.

- [ ] **Step 1: Create `app/domain/__init__.py`** (empty)

- [ ] **Step 2: Create `app/domain/models.py`**

```python
from enum import Enum


class OrderState(str, Enum):
    DISCOVERED = "DISCOVERED"
    CLAIMED_IMPORTED = "CLAIMED_IMPORTED"
    OPEN_FOR_ALLOCATION = "OPEN_FOR_ALLOCATION"
    ASSIGNMENT_PENDING_APPROVAL = "ASSIGNMENT_PENDING_APPROVAL"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    RESULT_SUBMITTED = "RESULT_SUBMITTED"
    QC_PENDING = "QC_PENDING"
    SUBMITTING_TO_SITE = "SUBMITTING_TO_SITE"
    DONE = "DONE"
    REASSIGNMENT_REQUIRED = "REASSIGNMENT_REQUIRED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    EXCEPTION = "EXCEPTION"
```

- [ ] **Step 3: Create `app/domain/exceptions.py`**

```python
from app.domain.models import OrderState


class InvalidTransitionError(Exception):
    def __init__(self, current: OrderState, target: OrderState):
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current} to {target}")
```

- [ ] **Step 4: Write the failing test — `tests/test_state_machine.py`**

```python
import pytest

from app.domain.exceptions import InvalidTransitionError
from app.domain.models import OrderState
from app.domain.state_machine import validate_transition


def test_valid_transition_does_not_raise():
    validate_transition(OrderState.DISCOVERED, OrderState.CLAIMED_IMPORTED)


def test_invalid_transition_raises():
    with pytest.raises(InvalidTransitionError):
        validate_transition(OrderState.DISCOVERED, OrderState.DONE)


def test_terminal_states_have_no_outgoing_transitions():
    for state in (OrderState.DONE, OrderState.CANCELLED, OrderState.SKIPPED):
        with pytest.raises(InvalidTransitionError):
            validate_transition(state, OrderState.IN_PROGRESS)


def test_qc_pending_allows_all_four_outcomes():
    for target in (
        OrderState.SUBMITTING_TO_SITE,
        OrderState.REVISION_REQUESTED,
        OrderState.SKIPPED,
        OrderState.CANCELLED,
    ):
        validate_transition(OrderState.QC_PENDING, target)


def test_assignment_pending_approval_cancel_path_returns_to_allocation():
    validate_transition(
        OrderState.ASSIGNMENT_PENDING_APPROVAL, OrderState.OPEN_FOR_ALLOCATION
    )


def test_reassignment_required_returns_to_allocation():
    validate_transition(OrderState.REASSIGNMENT_REQUIRED, OrderState.OPEN_FOR_ALLOCATION)
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest tests/test_state_machine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.state_machine'`

- [ ] **Step 6: Create `app/domain/state_machine.py`**

```python
from app.domain.exceptions import InvalidTransitionError
from app.domain.models import OrderState

# Matches claude.md §5. EXCEPTION can be entered from any state and, once there,
# only leaves via an explicit recovery command chosen by the operator — this table
# allows any EXCEPTION -> X transition; the application layer is responsible for
# only ever calling apply_transition() out of EXCEPTION from that explicit recovery
# command, never automatically.
ALLOWED_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.DISCOVERED: {OrderState.CLAIMED_IMPORTED, OrderState.EXCEPTION},
    OrderState.CLAIMED_IMPORTED: {OrderState.OPEN_FOR_ALLOCATION, OrderState.EXCEPTION},
    OrderState.OPEN_FOR_ALLOCATION: {
        OrderState.ASSIGNMENT_PENDING_APPROVAL,
        OrderState.EXCEPTION,
    },
    OrderState.ASSIGNMENT_PENDING_APPROVAL: {
        OrderState.ASSIGNED,
        OrderState.OPEN_FOR_ALLOCATION,
        OrderState.EXCEPTION,
    },
    OrderState.ASSIGNED: {OrderState.IN_PROGRESS, OrderState.EXCEPTION},
    OrderState.IN_PROGRESS: {
        OrderState.RESULT_SUBMITTED,
        OrderState.REASSIGNMENT_REQUIRED,
        OrderState.EXCEPTION,
    },
    OrderState.RESULT_SUBMITTED: {OrderState.QC_PENDING, OrderState.EXCEPTION},
    OrderState.QC_PENDING: {
        OrderState.SUBMITTING_TO_SITE,
        OrderState.REVISION_REQUESTED,
        OrderState.SKIPPED,
        OrderState.CANCELLED,
        OrderState.EXCEPTION,
    },
    OrderState.SUBMITTING_TO_SITE: {OrderState.DONE, OrderState.EXCEPTION},
    OrderState.REVISION_REQUESTED: {OrderState.IN_PROGRESS, OrderState.EXCEPTION},
    OrderState.REASSIGNMENT_REQUIRED: {OrderState.OPEN_FOR_ALLOCATION, OrderState.EXCEPTION},
    OrderState.SKIPPED: set(),
    OrderState.DONE: set(),
    OrderState.CANCELLED: set(),
    OrderState.EXCEPTION: set(OrderState),
}


def validate_transition(current: OrderState, target: OrderState) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransitionError(current, target)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_state_machine.py -v`
Expected: all 6 tests PASS

- [ ] **Step 8: Commit**

```bash
git add app/domain tests/test_state_machine.py
git commit -m "feat: domain state machine (OrderState enum + transition table)"
```

---

### Task 3: DB layer (SQLAlchemy models + Alembic migration)

**Files:**
- Create: `app/adapters/__init__.py`
- Create: `app/adapters/db/__init__.py`
- Create: `app/adapters/db/base.py`
- Create: `app/adapters/db/models.py`
- Create: `app/adapters/db/session.py`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/` (via `alembic revision --autogenerate`)
- Create: `tests/conftest.py`
- Test: `tests/test_migrations.py`

**Interfaces:**
- Consumes: nothing new (models are the ORM leaves of the schema).
- Produces: `app.adapters.db.base.Base` (SQLAlchemy `DeclarativeBase`),
  `app.adapters.db.session.SessionLocal` (sessionmaker bound to `get_settings().database_url`),
  and ORM classes `User`, `Batch`, `Order`, `OrderAsset`, `Assignment`, `ResultVersion`,
  `ApprovalRequest`, `ApprovalDecision`, `ExternalObservation`, `Operation`,
  `WorkflowEvent`, `Outbox`, `DeadLetter` in `app.adapters.db.models`. Also produces
  pytest fixtures `engine` (session-scoped, migrated Postgres) and `db_session`
  (function-scoped) that every later test file depends on.

- [ ] **Step 1: Create `app/adapters/__init__.py`** and **`app/adapters/db/__init__.py`**
      (both empty)

- [ ] **Step 2: Create `app/adapters/db/base.py`**

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

- [ ] **Step 3: Create `app/adapters/db/models.py`**

```python
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.adapters.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'designer')", name="ck_users_role"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    capacity: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    owner: Mapped[str] = mapped_column(String(64), nullable=False, default="ntth")
    count: Mapped[int] = mapped_column(nullable=False, default=0)
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    external_order_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("batches.id"), nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="DISCOVERED")
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    external_observation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __mapper_args__ = {"version_id_col": version}


class OrderAsset(Base):
    __tablename__ = "order_assets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    source_image_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    storage_location: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    designer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    sub_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    replacement_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assignments.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ResultVersion(Base):
    __tablename__ = "result_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    assignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    drive_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    version_marker: Mapped[int] = mapped_column(nullable=False, default=1)
    validated: Mapped[bool] = mapped_column(nullable=False, default=False)
    submitted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint("kind IN ('assignment', 'qc')", name="ck_approval_requests_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    target_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("result_versions.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    approval_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approval_requests.id"), unique=True, nullable=False
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class ExternalObservation(Base):
    __tablename__ = "external_observations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    observed_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class Operation(Base):
    __tablename__ = "operations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    command_name: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class Outbox(Base):
    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)


class DeadLetter(Base):
    __tablename__ = "dead_letters"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    error_class: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_action: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
```

- [ ] **Step 4: Create `app/adapters/db/session.py`**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings

_settings = get_settings()
engine = create_engine(_settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
```

- [ ] **Step 5: Create `alembic.ini`**

```ini
[alembic]
script_location = migrations
prepend_sys_path = .
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 6: Create `migrations/env.py`**

```python
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.adapters.db import models  # noqa: F401  (registers all tables on Base)
from app.adapters.db.base import Base
from app.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("DATABASE_URL") or get_settings().database_url
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 7: Create `migrations/script.py.mako`** (standard Alembic template)

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 8: Start local Postgres and create the test database**

```bash
docker compose up -d db
sleep 2
createdb -h localhost -U postgres pinterval_test
```

(`PGPASSWORD=postgres` may be needed if your `psql`/`createdb` doesn't trust local
connections — e.g. `PGPASSWORD=postgres createdb -h localhost -U postgres pinterval_test`.)

- [ ] **Step 9: Generate the initial migration**

```bash
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pinterval_test \
  alembic revision --autogenerate -m "initial schema"
```

Expected: a new file appears under `migrations/versions/`. Open it and confirm it
contains `op.create_table(...)` calls for all 13 tables listed in the Interfaces section
above, and nothing else (no unrelated drops). This file is generated content — commit it
as-is once verified.

- [ ] **Step 10: Create `tests/conftest.py`**

```python
from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/pinterval_test"
)
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("COOKIE_SECURE", "false")

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_URL = os.environ["DATABASE_URL"]


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DATABASE_URL)
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(alembic_cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture()
def db_session(engine):
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _truncate_tables(engine):
    yield
    with engine.begin() as conn:
        tables = conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename != 'alembic_version'"
            )
        ).scalars().all()
        if tables:
            conn.execute(text(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE"))
```

- [ ] **Step 11: Write the failing test — `tests/test_migrations.py`**

```python
from sqlalchemy import inspect

EXPECTED_TABLES = {
    "users",
    "batches",
    "orders",
    "order_assets",
    "assignments",
    "result_versions",
    "approval_requests",
    "approval_decisions",
    "external_observations",
    "operations",
    "workflow_events",
    "outbox",
    "dead_letters",
    "alembic_version",
}


def test_migration_creates_all_tables(engine):
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert EXPECTED_TABLES.issubset(tables)
```

- [ ] **Step 12: Run test to verify it passes**

Run: `pytest tests/test_migrations.py -v`
Expected: PASS (the `engine` fixture runs `alembic upgrade head` before the assertion)

- [ ] **Step 13: Commit**

```bash
git add app/adapters alembic.ini migrations tests/conftest.py tests/test_migrations.py
git commit -m "feat: SQLAlchemy models for all 13 tables + initial Alembic migration"
```

---

### Task 4: Application layer — state transitions + idempotency ledger

**Files:**
- Create: `app/application/__init__.py`
- Create: `app/application/order_transitions.py`
- Create: `app/application/operations.py`
- Test: `tests/test_order_transitions.py`
- Test: `tests/test_operations.py`

**Interfaces:**
- Consumes: `app.domain.models.OrderState`, `app.domain.state_machine.validate_transition`,
  `app.domain.exceptions.InvalidTransitionError` (Task 2); `app.adapters.db.models.Order`,
  `WorkflowEvent`, `Operation` (Task 3); `db_session` fixture (Task 3's conftest).
- Produces:
  `app.application.order_transitions.apply_transition(session, order: Order, target_state: OrderState, actor_id: uuid.UUID | None, evidence: dict) -> WorkflowEvent`
  and
  `app.application.operations.run_idempotent(session, idempotency_key: str, command_name: str, fn: Callable[[], dict]) -> dict`.
  Later phases (allocation, approval, QC) call both of these for every state-changing
  action.

- [ ] **Step 1: Create `app/application/__init__.py`** (empty)

- [ ] **Step 2: Write the failing tests — `tests/test_order_transitions.py`**

```python
import pytest

from app.adapters.db.models import Order, WorkflowEvent
from app.domain.exceptions import InvalidTransitionError
from app.domain.models import OrderState


def _make_order(db_session, external_id="DJ0000001"):
    order = Order(external_order_id=external_id, state=OrderState.DISCOVERED.value)
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)
    return order


def test_apply_transition_updates_state_and_writes_event(db_session):
    from app.application.order_transitions import apply_transition

    order = _make_order(db_session)
    initial_version = order.version

    event = apply_transition(
        db_session, order, OrderState.CLAIMED_IMPORTED, actor_id=None, evidence={"note": "claimed"}
    )

    assert order.state == OrderState.CLAIMED_IMPORTED.value
    assert order.version > initial_version
    assert event.from_state == OrderState.DISCOVERED.value
    assert event.to_state == OrderState.CLAIMED_IMPORTED.value
    assert event.evidence == {"note": "claimed"}


def test_apply_transition_rejects_invalid_transition(db_session):
    from app.application.order_transitions import apply_transition

    order = _make_order(db_session, external_id="DJ0000002")

    with pytest.raises(InvalidTransitionError):
        apply_transition(db_session, order, OrderState.DONE, actor_id=None, evidence={})

    db_session.refresh(order)
    assert order.state == OrderState.DISCOVERED.value


def test_workflow_events_are_append_only(db_session):
    from app.application.order_transitions import apply_transition

    order = _make_order(db_session, external_id="DJ0000003")
    apply_transition(db_session, order, OrderState.CLAIMED_IMPORTED, actor_id=None, evidence={})
    apply_transition(db_session, order, OrderState.OPEN_FOR_ALLOCATION, actor_id=None, evidence={})

    events = (
        db_session.query(WorkflowEvent)
        .filter_by(order_id=order.id)
        .order_by(WorkflowEvent.created_at)
        .all()
    )
    assert [e.to_state for e in events] == [
        OrderState.CLAIMED_IMPORTED.value,
        OrderState.OPEN_FOR_ALLOCATION.value,
    ]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_order_transitions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.application.order_transitions'`

- [ ] **Step 4: Create `app/application/order_transitions.py`**

```python
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.adapters.db.models import Order, WorkflowEvent
from app.domain.models import OrderState
from app.domain.state_machine import validate_transition


def apply_transition(
    session: Session,
    order: Order,
    target_state: OrderState,
    actor_id: uuid.UUID | None,
    evidence: dict,
) -> WorkflowEvent:
    current_state = OrderState(order.state)
    validate_transition(current_state, target_state)

    event = WorkflowEvent(
        order_id=order.id,
        from_state=current_state.value,
        to_state=target_state.value,
        actor_id=actor_id,
        evidence=evidence,
    )
    order.state = target_state.value
    session.add(event)
    session.add(order)
    session.commit()
    session.refresh(order)
    return event
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_order_transitions.py -v`
Expected: all 3 tests PASS

- [ ] **Step 6: Write the failing tests — `tests/test_operations.py`**

```python
from app.application.operations import run_idempotent


def test_run_idempotent_executes_once_for_same_key(db_session):
    calls = {"count": 0}

    def side_effect():
        calls["count"] += 1
        return {"value": calls["count"]}

    result1 = run_idempotent(db_session, "key-1", "test_command", side_effect)
    result2 = run_idempotent(db_session, "key-1", "test_command", side_effect)

    assert calls["count"] == 1
    assert result1 == {"value": 1}
    assert result2 == {"value": 1}


def test_run_idempotent_executes_again_for_different_key(db_session):
    calls = {"count": 0}

    def side_effect():
        calls["count"] += 1
        return {"value": calls["count"]}

    run_idempotent(db_session, "key-a", "test_command", side_effect)
    run_idempotent(db_session, "key-b", "test_command", side_effect)

    assert calls["count"] == 2
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `pytest tests/test_operations.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.application.operations'`

- [ ] **Step 8: Create `app/application/operations.py`**

```python
from __future__ import annotations

from typing import Callable

from app.adapters.db.models import Operation


class OperationInProgressError(Exception):
    """Raised when the same idempotency key is already being processed."""


def run_idempotent(
    session,
    idempotency_key: str,
    command_name: str,
    fn: Callable[[], dict],
) -> dict:
    existing = (
        session.query(Operation).filter_by(idempotency_key=idempotency_key).one_or_none()
    )
    if existing is not None:
        if existing.status == "completed":
            return existing.result
        if existing.status == "pending":
            raise OperationInProgressError(idempotency_key)
        existing.retry_count += 1
    else:
        existing = Operation(
            idempotency_key=idempotency_key,
            command_name=command_name,
            status="pending",
        )
        session.add(existing)
        session.commit()

    try:
        result = fn()
    except Exception:
        existing.status = "failed"
        session.commit()
        raise

    existing.status = "completed"
    existing.result = result
    session.commit()
    return result
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/test_operations.py -v`
Expected: both tests PASS

- [ ] **Step 10: Commit**

```bash
git add app/application tests/test_order_transitions.py tests/test_operations.py
git commit -m "feat: apply_transition (atomic state change + audit) and idempotency ledger"
```

---

### Task 5: Auth (password hashing, session cookie, role-based routes)

**Files:**
- Create: `app/application/auth.py`
- Create: `app/api/__init__.py`
- Create: `app/api/deps.py`
- Create: `app/api/routes/__init__.py`
- Create: `app/api/routes/health.py`
- Create: `app/api/routes/auth.py`
- Create: `app/api/routes/protected_example.py`
- Create: `app/api/main.py`
- Test: `tests/test_auth.py`
- Test: `tests/test_api_auth.py`

**Interfaces:**
- Consumes: `app.config.get_settings` (Task 1); `app.adapters.db.models.User` (Task 3);
  `SessionLocal` (Task 3).
- Produces: `app.application.auth.hash_password(raw: str) -> str`,
  `verify_password(raw: str, password_hash: str) -> bool`,
  `create_session_token(user_id: str, role: str) -> str`,
  `read_session_token(token: str) -> dict | None`; `app.api.deps.get_db`,
  `get_current_user`, `require_role(role: str)`; `app.api.main.create_app() -> FastAPI`.
  Phase 4+ web routes reuse `get_current_user`/`require_role` for every page.

- [ ] **Step 1: Write the failing test — `tests/test_auth.py`**

```python
from app.application.auth import (
    create_session_token,
    hash_password,
    read_session_token,
    verify_password,
)


def test_hash_and_verify_password_roundtrip():
    hashed = hash_password("s3cret!")
    assert hashed != "s3cret!"
    assert verify_password("s3cret!", hashed)
    assert not verify_password("wrong", hashed)


def test_session_token_roundtrip():
    token = create_session_token("user-123", "admin")
    data = read_session_token(token)
    assert data == {"user_id": "user-123", "role": "admin"}


def test_session_token_rejects_tampered_value():
    token = create_session_token("user-123", "admin")
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    assert read_session_token(tampered) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.application.auth'`

- [ ] **Step 3: Create `app/application/auth.py`**

```python
from __future__ import annotations

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings


def hash_password(raw_password: str) -> str:
    return bcrypt.hashpw(raw_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(raw_password.encode("utf-8"), password_hash.encode("utf-8"))


def _serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    return URLSafeTimedSerializer(settings.secret_key, salt="session-cookie")


def create_session_token(user_id: str, role: str) -> str:
    return _serializer().dumps({"user_id": user_id, "role": role})


def read_session_token(token: str) -> dict | None:
    settings = get_settings()
    try:
        return _serializer().loads(token, max_age=settings.session_max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auth.py -v`
Expected: all 3 tests PASS

- [ ] **Step 5: Create `app/api/__init__.py`** and **`app/api/routes/__init__.py`** (both empty)

- [ ] **Step 6: Create `app/api/deps.py`**

```python
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.adapters.db.session import SessionLocal
from app.application.auth import read_session_token

SESSION_COOKIE_NAME = "session"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    data = read_session_token(token)
    if data is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    user = db.get(User, uuid.UUID(data["user_id"]))
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def require_role(role: str):
    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role != role:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return _check
```

- [ ] **Step 7: Create `app/api/routes/health.py`**

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 8: Create `app/api/routes/auth.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.api.deps import SESSION_COOKIE_NAME, get_current_user, get_db
from app.application.auth import create_session_token, verify_password
from app.config import get_settings

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=payload.username).one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    settings = get_settings()
    token = create_session_token(str(user.id), user.role)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_max_age_seconds,
    )
    return {"id": str(user.id), "role": user.role}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"id": str(user.id), "role": user.role, "full_name": user.full_name}
```

- [ ] **Step 9: Create `app/api/routes/protected_example.py`**

```python
from fastapi import APIRouter, Depends

from app.adapters.db.models import User
from app.api.deps import require_role

router = APIRouter()


@router.get("/admin/ping")
def admin_ping(user: User = Depends(require_role("admin"))):
    return {"ok": True, "role": "admin"}


@router.get("/designer/ping")
def designer_ping(user: User = Depends(require_role("designer"))):
    return {"ok": True, "role": "designer"}
```

- [ ] **Step 10: Create `app/api/main.py`**

```python
from fastapi import FastAPI

from app.api.routes import auth as auth_routes
from app.api.routes import health as health_routes
from app.api.routes import protected_example


def create_app() -> FastAPI:
    app = FastAPI(title="Pinterval Ops Dashboard")
    app.include_router(health_routes.router, prefix="/api")
    app.include_router(auth_routes.router, prefix="/api")
    app.include_router(protected_example.router, prefix="/api")
    return app


app = create_app()
```

- [ ] **Step 11: Write the failing tests — `tests/test_api_auth.py`**

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
        username="admin1",
        full_name="Admin One",
        role="admin",
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture()
def designer_user(db_session):
    user = User(
        username="designer1",
        full_name="Designer One",
        role="designer",
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_login_success_sets_cookie(client, admin_user):
    resp = client.post("/api/login", json={"username": "admin1", "password": "s3cret!"})
    assert resp.status_code == 200
    assert "session" in resp.cookies


def test_login_wrong_password_401(client, admin_user):
    resp = client.post("/api/login", json={"username": "admin1", "password": "wrong"})
    assert resp.status_code == 401


def test_protected_route_without_cookie_401(client):
    resp = client.get("/api/admin/ping")
    assert resp.status_code == 401


def test_admin_route_rejects_designer_403(client, designer_user):
    login = client.post("/api/login", json={"username": "designer1", "password": "s3cret!"})
    assert login.status_code == 200
    resp = client.get("/api/admin/ping")
    assert resp.status_code == 403


def test_admin_route_accepts_admin_200(client, admin_user):
    login = client.post("/api/login", json={"username": "admin1", "password": "s3cret!"})
    assert login.status_code == 200
    resp = client.get("/api/admin/ping")
    assert resp.status_code == 200
```

- [ ] **Step 12: Run tests to verify they fail, then pass**

Run: `pytest tests/test_api_auth.py -v`
Expected first (before Steps 5–10 existed it would fail with import errors — since
those steps are already done by this point in the task, it should PASS immediately);
if any test fails, check that `COOKIE_SECURE=false` is set by `tests/conftest.py`
(Task 3, Step 10) — without it, the test client won't retain the `Secure` cookie
because `TestClient`'s base URL is `http://testserver` (no TLS).

Expected: all 5 tests PASS.

- [ ] **Step 13: Commit**

```bash
git add app/application/auth.py app/api tests/test_auth.py tests/test_api_auth.py
git commit -m "feat: bcrypt password hashing, signed session cookie, role-gated routes"
```

---

### Task 6: Backup / restore scripts + roundtrip test

**Files:**
- Create: `scripts/db_backup.sh`
- Create: `scripts/db_restore.sh`
- Test: `tests/test_backup_restore.py`

**Interfaces:**
- Consumes: `engine`, `db_session` fixtures (Task 3); `app.adapters.db.models.User`,
  `app.application.auth.hash_password` (Tasks 3, 5).
- Produces: two operator-facing shell scripts (`scripts/db_backup.sh <output-file>`,
  `scripts/db_restore.sh <input-file>`, both reading the target DB from `DATABASE_URL`)
  — referenced from `claude.md` §7 deployment/backup requirements and used directly by
  operators in Phase 8 runbooks.

- [ ] **Step 1: Create `scripts/db_backup.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL is required}"
OUT="${1:?usage: db_backup.sh <output-file.dump>}"
pg_dump --format=custom --file="$OUT" --dbname="$DATABASE_URL"
echo "Backup written to $OUT"
```

- [ ] **Step 2: Create `scripts/db_restore.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL is required}"
IN="${1:?usage: db_restore.sh <input-file.dump>}"
pg_restore --clean --if-exists --no-owner --dbname="$DATABASE_URL" "$IN"
echo "Restored from $IN"
```

- [ ] **Step 3: Make both scripts executable**

```bash
chmod +x scripts/db_backup.sh scripts/db_restore.sh
```

- [ ] **Step 4: Write the failing test — `tests/test_backup_restore.py`**

```python
import os
import subprocess
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.skipif(
    subprocess.run(["which", "pg_dump"], capture_output=True).returncode != 0,
    reason="pg_dump/pg_restore not installed",
)


def _pg_env_and_url(sqlalchemy_url: str):
    u = make_url(sqlalchemy_url)
    env = dict(os.environ)
    if u.password:
        env["PGPASSWORD"] = u.password
    return env, u


def test_backup_then_restore_roundtrip(db_session, engine, tmp_path):
    from app.adapters.db.models import User
    from app.application.auth import hash_password

    marker_username = f"backup-test-{uuid.uuid4().hex[:8]}"
    db_session.add(
        User(
            username=marker_username,
            full_name="Backup Marker",
            role="admin",
            password_hash=hash_password("irrelevant"),
        )
    )
    db_session.commit()

    source_url = str(engine.url)
    env, u = _pg_env_and_url(source_url)
    host_args = ["-h", u.host or "localhost", "-p", str(u.port or 5432), "-U", u.username]
    plain_url = source_url.replace("postgresql+psycopg", "postgresql")

    dump_path = tmp_path / "backup.dump"
    subprocess.run(
        ["bash", "scripts/db_backup.sh", str(dump_path)],
        check=True,
        env={**env, "DATABASE_URL": plain_url},
    )
    assert dump_path.exists() and dump_path.stat().st_size > 0

    restore_db = f"pinterval_restore_{uuid.uuid4().hex[:8]}"
    subprocess.run(["createdb", *host_args, restore_db], check=True, env=env)
    try:
        restore_url = plain_url.rsplit("/", 1)[0] + f"/{restore_db}"
        subprocess.run(
            ["bash", "scripts/db_restore.sh", str(dump_path)],
            check=True,
            env={**env, "DATABASE_URL": restore_url},
        )
        restore_engine = create_engine(restore_url.replace("postgresql", "postgresql+psycopg", 1))
        with restore_engine.connect() as conn:
            row = conn.execute(
                text("SELECT username FROM users WHERE username = :u"),
                {"u": marker_username},
            ).one_or_none()
        restore_engine.dispose()
        assert row is not None
    finally:
        subprocess.run(["dropdb", *host_args, "--if-exists", restore_db], env=env)
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest tests/test_backup_restore.py -v`
Expected: FAIL (scripts not yet executable/created before this step in a fresh checkout,
or `createdb`/`dropdb` not found — if `pg_dump` isn't installed locally, the test SKIPS
instead; that's fine, CI in Task 7 has it via the postgres client tools on the runner).

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_backup_restore.py -v`
Expected: PASS (or SKIPPED if `pg_dump` isn't on this machine — verify it passes in CI
in Task 7 instead)

- [ ] **Step 7: Commit**

```bash
git add scripts/db_backup.sh scripts/db_restore.sh tests/test_backup_restore.py
git commit -m "feat: backup/restore scripts + roundtrip test"
```

---

### Task 7: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: everything from Tasks 1–6 (`pyproject.toml` deps, `alembic.ini`/`migrations/`,
  full `tests/` suite, `ruff` config).
- Produces: a GitHub Actions job that every future PR runs against.

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: pinterval_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    env:
      DATABASE_URL: postgresql+psycopg://postgres:postgres@localhost:5432/pinterval_test
      SECRET_KEY: ci-test-secret
      COOKIE_SECURE: "false"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Lint
        run: ruff check .
      - name: Run tests
        run: pytest -v
```

- [ ] **Step 2: Run the full local suite once to confirm everything is green before pushing**

```bash
docker compose up -d db
ruff check .
pytest -v
```

Expected: `ruff check .` reports no issues; all tests from Tasks 1–6 PASS (or SKIP for
`test_backup_restore.py` if `pg_dump` is missing locally).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run ruff + pytest against Postgres 16 service container"
```

- [ ] **Step 4: Push and confirm CI passes**

```bash
git push
```

Open the GitHub Actions run for this push and confirm the `test` job is green.

---

## Self-review notes

- **Spec coverage:** every Phase 1 deliverable/acceptance line in `roadmap.md` §5 Phase 1
  maps to a task above — schema (Task 3), state machine + audit (Task 2 + Task 4),
  idempotency (Task 4), role/auth (Task 5), migration/backup/restore demo (Task 3 +
  Task 6). CI/lint (Task 7).
- **Placeholder scan:** no TODO/TBD; every step has literal file content or a runnable
  command with an expected result.
- **Type consistency:** `apply_transition(session, order, target_state, actor_id, evidence)`
  signature is identical in Task 4's definition and every caller in its own tests;
  `run_idempotent(session, idempotency_key, command_name, fn)` likewise. `OrderState`
  member names match claude.md §5 and roadmap.md §4 exactly (`CLAIMED_IMPORTED`,
  `OPEN_FOR_ALLOCATION`, `SUBMITTING_TO_SITE`, etc.).
- **Scope check:** this plan only covers Phase 1 (foundation). It deliberately does not
  touch Playwright adapters, allocation logic, or any web page — those are Phase 2+ and
  belong in their own plans.

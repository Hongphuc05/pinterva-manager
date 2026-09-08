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
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_URL = os.environ["DATABASE_URL"]

# `setdefault` above means a shell-exported DATABASE_URL wins — and `_truncate_tables`
# wipes every table in whatever it points at. Refuse anything not obviously a test DB.
_resolved_db_name = make_url(TEST_DATABASE_URL).database
assert _resolved_db_name and "test" in _resolved_db_name, (
    f"refusing to run tests against database {_resolved_db_name!r} — "
    "it must contain 'test' in its name (safety guard against wiping a real DB)"
)


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

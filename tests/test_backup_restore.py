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

    source_url = engine.url.render_as_string(hide_password=False)
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

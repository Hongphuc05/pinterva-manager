from app.config import Settings


def test_settings_defaults(monkeypatch):
    # tests/conftest.py sets COOKIE_SECURE=false for the whole session so the
    # test client can run over http; isolate this default-value check from it.
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    s = Settings(_env_file=None)
    assert s.database_url.startswith("postgresql+psycopg://")
    assert s.cookie_secure is True


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "abc123")
    s = Settings(_env_file=None)
    assert s.secret_key == "abc123"

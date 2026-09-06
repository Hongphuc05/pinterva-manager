import pytest

from app.config import DEFAULT_SECRET_KEY, Settings


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


def test_default_secret_rejected_when_cookie_secure(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(_env_file=None, cookie_secure=True)


def test_default_secret_allowed_for_local_dev(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    s = Settings(_env_file=None, cookie_secure=False)
    assert s.secret_key == DEFAULT_SECRET_KEY

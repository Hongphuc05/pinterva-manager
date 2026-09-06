from app.config import Settings


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.database_url.startswith("postgresql+psycopg://")
    assert s.cookie_secure is True


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "abc123")
    s = Settings(_env_file=None)
    assert s.secret_key == "abc123"

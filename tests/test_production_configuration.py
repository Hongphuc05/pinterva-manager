from pathlib import Path

from fastapi.testclient import TestClient

from app.adapters.playwright_support import _profile_path
from app.api.main import create_app
from app.config import get_settings


def test_playwright_profile_root_is_optional_for_local_development(monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_PROFILE_ROOT", raising=False)
    assert _profile_path("chrome-profile-platform") == Path("chrome-profile-platform")


def test_playwright_profile_root_keeps_container_profiles_on_persistent_volume(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_PROFILE_ROOT", "/app/chrome-profiles")
    assert _profile_path("chrome-profile-platform") == Path(
        "/app/chrome-profiles/chrome-profile-platform"
    )


def test_cors_allows_only_configured_production_origin(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://tacahu-ops.vercel.app")
    monkeypatch.delenv("CORS_ORIGIN_REGEX", raising=False)
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        allowed = client.options(
            "/api/health",
            headers={
                "Origin": "https://tacahu-ops.vercel.app",
                "Access-Control-Request-Method": "GET",
            },
        )
        rejected = client.options(
            "/api/health",
            headers={
                "Origin": "https://untrusted.vercel.app",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert allowed.headers["access-control-allow-origin"] == "https://tacahu-ops.vercel.app"
    assert "access-control-allow-origin" not in rejected.headers
    get_settings.cache_clear()

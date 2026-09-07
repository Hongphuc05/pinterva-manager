"""Covers the Task-6 catch-all in app/api/main.py, whose coverage previously depended
on whether `frontend/dist/` happened to exist in the checkout (I-5). Builds a fake
FRONTEND_DIST in a tmp_path and creates a fresh app against it, so these tests run
identically on a clean clone or in CI with no `npm run build`."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.main as main_module


@pytest.fixture()
def fake_dist_client(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html>fake spa shell</html>")
    (tmp_path / "favicon.svg").write_text("<svg>fake favicon</svg>")
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    (assets_dir / "fake.js").write_text("console.log('fake')")

    monkeypatch.setattr(main_module, "FRONTEND_DIST", tmp_path)
    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


def test_unknown_api_path_returns_404_json(fake_dist_client):
    resp = fake_dist_client.get("/api/nope")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


def test_real_api_route_still_works(fake_dist_client):
    resp = fake_dist_client.get("/api/health")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")


def test_spa_route_falls_back_to_index_html(fake_dist_client):
    resp = fake_dist_client.get("/orders")
    assert resp.status_code == 200
    assert "fake spa shell" in resp.text


def test_public_file_at_dist_root_is_served_verbatim(fake_dist_client):
    """Regression test for I-4: a file Vite copies to dist/ root (favicon.svg, from
    frontend/public/) must be served as itself, not shadowed by the SPA index.html
    fallback."""
    resp = fake_dist_client.get("/favicon.svg")
    assert resp.status_code == 200
    assert "fake favicon" in resp.text
    assert "fake spa shell" not in resp.text


def test_asset_is_served_through_static_mount(fake_dist_client):
    resp = fake_dist_client.get("/assets/fake.js")
    assert resp.status_code == 200
    assert "fake" in resp.text

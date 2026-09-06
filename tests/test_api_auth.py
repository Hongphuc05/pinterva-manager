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

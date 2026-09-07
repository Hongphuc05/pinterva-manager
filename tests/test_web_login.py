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
        username="admin1", full_name="Admin One", role="admin",
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_login_page_renders(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "<form" in resp.text


def test_login_success_redirects_and_sets_cookie(client, admin_user):
    resp = client.post(
        "/login", data={"username": "admin1", "password": "s3cret!"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/orders"
    assert "session" in resp.cookies


def test_login_failure_rerenders_with_error_and_no_cookie(client, admin_user):
    resp = client.post("/login", data={"username": "admin1", "password": "wrong"})
    assert resp.status_code == 401
    assert "session" not in resp.cookies
    assert "Sai tên đăng nhập" in resp.text


def test_logout_clears_cookie_and_redirects(client, admin_user):
    client.post("/login", data={"username": "admin1", "password": "s3cret!"})
    resp = client.post("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"

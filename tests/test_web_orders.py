import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import Order, User
from app.api.deps import get_db
from app.api.main import create_app
from app.application.auth import hash_password
from app.domain.models import OrderState


@pytest.fixture()
def client(db_session):
    app = create_app()

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, db_session, role, username="user1"):
    user = User(
        username=username, full_name=username, role=role,
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(user)
    db_session.commit()
    client.post("/login", data={"username": username, "password": "s3cret!"})
    return user


def test_root_redirects_authed_user_to_orders(client, db_session):
    _login(client, db_session, "admin")
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/orders"


def test_orders_requires_login_redirects_to_login(client):
    resp = client.get("/orders", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_orders_list_shows_all_orders_for_admin(client, db_session):
    _login(client, db_session, "admin")
    db_session.add(Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value))
    db_session.add(Order(external_order_id="DJ2", state=OrderState.DISCOVERED.value))
    db_session.commit()

    resp = client.get("/orders")

    assert resp.status_code == 200
    assert "DJ1" in resp.text
    assert "DJ2" in resp.text


def test_orders_list_shows_empty_for_designer_with_no_assignments(client, db_session):
    _login(client, db_session, "designer")
    db_session.add(Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value))
    db_session.commit()

    resp = client.get("/orders")

    assert resp.status_code == 200
    assert "DJ1" not in resp.text


def test_orders_table_partial_returns_only_table_fragment(client, db_session):
    _login(client, db_session, "admin")

    resp = client.get("/orders/table")

    assert resp.status_code == 200
    assert "<table" in resp.text
    assert "<html" not in resp.text

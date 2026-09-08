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
    client.post("/api/login", json={"username": username, "password": "s3cret!"})
    return user


def test_api_orders_list_returns_all_orders_for_admin(client, db_session):
    _login(client, db_session, "admin")
    db_session.add(Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value))
    db_session.commit()

    resp = client.get("/api/orders")

    assert resp.status_code == 200
    ids = [o["external_order_id"] for o in resp.json()["orders"]]
    assert ids == ["DJ1"]


def test_api_orders_list_requires_auth(client):
    resp = client.get("/api/orders")
    assert resp.status_code == 401


def test_api_orders_list_filters_by_status(client, db_session):
    _login(client, db_session, "admin")
    db_session.add(Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value))
    db_session.add(Order(external_order_id="DJ2", state=OrderState.CLAIMED_IMPORTED.value))
    db_session.commit()

    resp = client.get("/api/orders", params={"status": OrderState.DISCOVERED.value})

    ids = [o["external_order_id"] for o in resp.json()["orders"]]
    assert ids == ["DJ1"]


def test_api_order_detail_returns_404_for_missing_order(client, db_session):
    _login(client, db_session, "admin")
    resp = client.get("/api/orders/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_api_order_detail_returns_order_and_history(client, db_session):
    _login(client, db_session, "admin")
    order = Order(
        external_order_id="DJ1", state=OrderState.DISCOVERED.value, product_name="Test Mug"
    )
    db_session.add(order)
    db_session.commit()

    resp = client.get(f"/api/orders/{order.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["order"]["product_name"] == "Test Mug"
    assert body["history"] == []


def test_api_orders_refresh_requires_admin(client, db_session):
    _login(client, db_session, "designer")
    resp = client.post("/api/orders/refresh")
    assert resp.status_code == 403


def test_api_printerval_login_status_requires_admin(client, db_session):
    _login(client, db_session, "designer")
    resp = client.get("/api/printerval-login/status")
    assert resp.status_code == 403


def test_api_printerval_login_status_defaults_closed(client, db_session):
    _login(client, db_session, "admin")
    resp = client.get("/api/printerval-login/status")
    assert resp.status_code == 200
    assert resp.json() == {"session_open": False}


def test_api_bulk_assign_orders(client, db_session):
    admin = _login(client, db_session, "admin", "bulk_admin")
    designer = User(
        username="des1", full_name="Linh Designer", role="designer", password_hash="hash"
    )
    order1 = Order(external_order_id="B1", state=OrderState.DISCOVERED.value)
    order2 = Order(external_order_id="B2", state=OrderState.DISCOVERED.value)
    db_session.add_all([designer, order1, order2])
    db_session.commit()

    resp = client.post(
        "/api/orders/bulk-assign",
        json={"order_ids": [str(order1.id), str(order2.id)], "designer_id": str(designer.id)},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["assigned_count"] == 2


def test_api_sync_status_defaults_to_not_running_when_never_synced(client, db_session):
    _login(client, db_session, "admin")
    resp = client.get("/api/orders/sync-status")
    assert resp.status_code == 200
    assert resp.json()["is_running"] is False
    assert resp.json()["last_finished_at"] is None


def test_api_sync_status_run_requires_admin(client, db_session):
    _login(client, db_session, "designer")
    resp = client.post("/api/orders/sync-status/run")
    assert resp.status_code == 403


def test_api_sync_status_run_dispatches_the_background_task(client, db_session, monkeypatch):
    from app.workers import status_sync_tasks

    calls = []
    monkeypatch.setattr(status_sync_tasks.sync_order_statuses, "delay", lambda: calls.append(1))
    _login(client, db_session, "admin")

    resp = client.post("/api/orders/sync-status/run")

    assert resp.status_code == 200
    assert calls == [1]


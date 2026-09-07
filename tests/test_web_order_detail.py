import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import Order, User, WorkflowEvent
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


def test_order_detail_admin_sees_any_order_with_history(client, db_session):
    _login(client, db_session, "admin")
    order = Order(external_order_id="DJ1", state=OrderState.CLAIMED_IMPORTED.value)
    db_session.add(order)
    db_session.commit()
    db_session.add(
        WorkflowEvent(order_id=order.id, from_state="DISCOVERED", to_state="CLAIMED_IMPORTED")
    )
    db_session.commit()

    resp = client.get(f"/orders/{order.id}")

    assert resp.status_code == 200
    assert "DJ1" in resp.text
    assert "CLAIMED_IMPORTED" in resp.text


def test_order_detail_designer_without_assignment_gets_404(client, db_session):
    _login(client, db_session, "designer")
    order = Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value)
    db_session.add(order)
    db_session.commit()

    resp = client.get(f"/orders/{order.id}")

    assert resp.status_code == 404


def test_order_detail_invalid_id_returns_404(client, db_session):
    _login(client, db_session, "admin")

    resp = client.get("/orders/not-a-real-uuid")

    assert resp.status_code == 404


def test_order_detail_requires_login_redirects_to_login(client, db_session):
    order = Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value)
    db_session.add(order)
    db_session.commit()

    resp = client.get(f"/orders/{order.id}", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"

import pytest
import uuid
from fastapi.testclient import TestClient

from app.adapters.db.models import Platform, User, Order
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


def _login(client, db_session, role="admin", username="testadmin_plat"):
    user = db_session.query(User).filter_by(username=username).one_or_none()
    if user is None:
        user = User(
            username=username,
            full_name=f"Test {role.title()}",
            role=role,
            password_hash=hash_password("pass123"),
            active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

    resp = client.post("/api/login", json={"username": username, "password": "pass123"})
    assert resp.status_code == 200
    token = resp.json().get("access_token")
    return user, token


def test_list_and_create_platforms(client, db_session):
    admin_user, token = _login(client, db_session, "admin", "admin_plat1")
    
    # List existing platforms
    resp = client.get("/api/platforms", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    platforms = resp.json()
    assert isinstance(platforms, list)

    # Create new platform
    create_resp = client.post(
        "/api/platforms",
        json={"name": "Acc Me Platform B", "account_username": "seller_b@printerval.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["name"] == "Acc Me Platform B"
    assert created["account_username"] == "seller_b@printerval.com"


def test_platform_scoped_orders(client, db_session):
    admin_user, token = _login(client, db_session, "admin", "admin_plat2")

    # Create 2 platforms
    p1 = Platform(name="P1", account_username="acc1@printerval.com")
    p2 = Platform(name="P2", account_username="acc2@printerval.com")
    db_session.add_all([p1, p2])
    db_session.commit()

    # Create order in P1 and order in P2
    o1 = Order(external_order_id="DJ_P1_001", platform_id=p1.id, state="DISCOVERED")
    o2 = Order(external_order_id="DJ_P2_001", platform_id=p2.id, state="DISCOVERED")
    db_session.add_all([o1, o2])
    db_session.commit()

    # Query with P1 header
    r1 = client.get("/api/orders", headers={"Authorization": f"Bearer {token}", "X-Platform-Id": str(p1.id)})
    assert r1.status_code == 200
    orders_p1 = r1.json()["orders"]
    assert len(orders_p1) == 1
    assert orders_p1[0]["external_order_id"] == "DJ_P1_001"

    # Query with P2 header
    r2 = client.get("/api/orders", headers={"Authorization": f"Bearer {token}", "X-Platform-Id": str(p2.id)})
    assert r2.status_code == 200
    orders_p2 = r2.json()["orders"]
    assert len(orders_p2) == 1
    assert orders_p2[0]["external_order_id"] == "DJ_P2_001"

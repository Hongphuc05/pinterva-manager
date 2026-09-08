import os

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


def test_printerval_credentials_persist_team_outsource_per_platform_not_env(client, db_session, monkeypatch):
    """Regression test: switching to a second mother account must not clobber the
    first account's team_outsource via process-wide os.environ — each Platform row
    keeps its own value (root cause of "crawl thất bại" after switching acc mẹ)."""
    from app.adapters.printerval.api_client import PrintervalApiClient

    monkeypatch.delenv("PRINTERVAL_TEAM_OUTSOURCE", raising=False)
    # Saving credentials now verifies them against the real site first (a real
    # incident: a wrong password sat silently in the DB with no verification) — stub
    # that out here, it's covered by its own dedicated tests below.
    monkeypatch.setattr(PrintervalApiClient, "login", lambda self: None)
    monkeypatch.setattr(PrintervalApiClient, "discover_waiting_page", lambda self, **k: None)
    monkeypatch.setattr(PrintervalApiClient, "close", lambda self: None)
    _, token = _login(client, db_session, "admin", "admin_plat3")
    headers = {"Authorization": f"Bearer {token}"}

    r1 = client.post(
        "/api/orders/printerval-credentials",
        json={"username": "acc1@printerval.com", "password": "pw1", "team_outsource": "team-a"},
        headers=headers,
    )
    assert r1.status_code == 200
    r2 = client.post(
        "/api/orders/printerval-credentials",
        json={"username": "acc2@printerval.com", "password": "pw2", "team_outsource": "team-b"},
        headers=headers,
    )
    assert r2.status_code == 200

    p1 = db_session.query(Platform).filter_by(account_username="acc1@printerval.com").one()
    p2 = db_session.query(Platform).filter_by(account_username="acc2@printerval.com").one()
    assert p1.team_outsource == "team-a"
    assert p2.team_outsource == "team-b"
    # The whole point: logging into account 2 must not have overwritten account 1's
    # persisted value via a shared global.
    assert "PRINTERVAL_TEAM_OUTSOURCE" not in os.environ


def test_printerval_credentials_rejects_a_login_that_fails_against_the_real_site(client, db_session, monkeypatch):
    """Regression test: a wrong password used to save silently — nothing verified it
    could actually log in — and only surfaced as a mysterious "crawl thất bại" during
    an unrelated crawl attempt much later."""
    from app.adapters.printerval.api_client import PrintervalApiClient, PrintervalApiError
    from app.adapters.errors import ErrorClass

    def _fail_login(self):
        raise PrintervalApiError(ErrorClass.AUTH, "Printerval did not accept the supplied login")

    monkeypatch.setattr(PrintervalApiClient, "login", _fail_login)
    monkeypatch.setattr(PrintervalApiClient, "close", lambda self: None)
    _, token = _login(client, db_session, "admin", "admin_plat4")

    resp = client.post(
        "/api/orders/printerval-credentials",
        json={"username": "bad@printerval.com", "password": "wrong", "team_outsource": "team-a"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 400
    assert db_session.query(Platform).filter_by(account_username="bad@printerval.com").first() is None


def test_printerval_credentials_rejects_a_team_outsource_the_find_endpoint_errors_on(
    client, db_session, monkeypatch
):
    from app.adapters.printerval.api_client import PrintervalApiClient, PrintervalApiError
    from app.adapters.errors import ErrorClass

    monkeypatch.setattr(PrintervalApiClient, "login", lambda self: None)
    monkeypatch.setattr(PrintervalApiClient, "close", lambda self: None)

    def _fail_discover(self, **kwargs):
        raise PrintervalApiError(ErrorClass.EXTERNAL_CHANGED, "Waiting queue response changed or was rejected")

    monkeypatch.setattr(PrintervalApiClient, "discover_waiting_page", _fail_discover)
    _, token = _login(client, db_session, "admin", "admin_plat5")

    resp = client.post(
        "/api/orders/printerval-credentials",
        json={"username": "acc3@printerval.com", "password": "pw3", "team_outsource": "wrong-team"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 400
    assert db_session.query(Platform).filter_by(account_username="acc3@printerval.com").first() is None

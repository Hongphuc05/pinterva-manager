import pytest
from fastapi.testclient import TestClient

from datetime import UTC, datetime

from app.adapters.db.models import DeadLetter, Order, User
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


def _login(client, db_session, role, username):
    user = db_session.query(User).filter_by(username=username).one_or_none()
    if user is None:
        user = User(username=username, full_name=username, role=role, password_hash=hash_password("x"))
        db_session.add(user)
    else:
        user.password_hash = hash_password("x")
        user.role = role
    db_session.commit()
    resp = client.post("/api/login", json={"username": username, "password": "x"})
    assert resp.status_code == 200
    return user


def test_kanban_is_admin_only_and_groups_cards_with_alerts(client, db_session):
    _login(client, db_session, "designer", "designer")
    assert client.get("/api/kanban").status_code == 403

    _login(client, db_session, "admin", "admin")
    order = Order(external_order_id="KAN-1", state=OrderState.EXCEPTION.value)
    db_session.add(order)
    db_session.flush()
    db_session.add(
        DeadLetter(
            source="crawl.download_asset",
            payload={"order_id": "KAN-1", "stage": "download_asset"},
            error_class="NETWORK",
            recovery_action="Thử quét lại đơn.",
        )
    )
    db_session.commit()

    response = client.get("/api/kanban")

    assert response.status_code == 200
    attention = next(column for column in response.json()["columns"] if column["id"] == "attention")
    assert attention["cards"][0]["external_order_id"] == "KAN-1"
    alerts = attention["cards"][0]["alerts"]
    assert alerts[0]["label"] == "Có lỗi xử lý"
    assert "crawl.download_asset" in alerts[0]["detail"]
    assert "NETWORK" in alerts[0]["detail"]
    assert alerts[1]["label"] == "Ngoại lệ"


def test_kanban_hides_resolved_dead_letter_alerts(client, db_session):
    _login(client, db_session, "admin", "admin")
    order = Order(external_order_id="KAN-RESOLVED", state=OrderState.OPEN.value)
    db_session.add(order)
    db_session.flush()
    db_session.add(
        DeadLetter(
            source="crawl.retry_failed_claims",
            payload={"order_id": "KAN-RESOLVED"},
            error_class="VALIDATION",
            resolved_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    response = client.get("/api/kanban")

    assert response.status_code == 200
    open_column = next(column for column in response.json()["columns"] if column["id"] == "open")
    card = next(card for card in open_column["cards"] if card["external_order_id"] == "KAN-RESOLVED")
    assert card["alerts"] == []

import uuid

import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import Assignment, Order, Platform, User, WorkflowEvent
from app.api.deps import get_current_platform_id, get_db
from app.api.main import create_app
from app.application.auth import hash_password


@pytest.fixture()
def client(db_session):
    app = create_app()

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login(client, db_session, role: str, username: str) -> tuple[User, dict[str, str]]:
    user = User(
        username=username,
        full_name=username,
        role=role,
        password_hash=hash_password("pass123"),
        active=True,
    )
    db_session.add(user)
    db_session.commit()
    response = client.post("/api/login", json={"username": username, "password": "pass123"})
    assert response.status_code == 200
    return user, {"Authorization": f"Bearer {response.json()['access_token']}"}


def _platform(db_session, name: str = "Duplicate board platform") -> Platform:
    platform = Platform(name=name, account_username=f"{uuid.uuid4()}@example.com")
    db_session.add(platform)
    db_session.commit()
    return platform


def test_admin_can_put_orders_in_duplicate_domain_and_board_shows_missing_form(
    client, db_session
):
    platform = _platform(db_session)
    admin, headers = _login(client, db_session, "admin", "duplicate-domain-admin")
    trello_designer = User(
        username="trello-designer-a",
        full_name="Trello A",
        role="designer-trello",
        password_hash="hash",
        platform_id=platform.id,
    )
    regular_designer = User(
        username="regular-designer-a",
        full_name="Regular A",
        role="designer",
        password_hash="hash",
        platform_id=platform.id,
    )
    order = Order(external_order_id="DUP-1", platform_id=platform.id, work_domain="standard")
    db_session.add_all([trello_designer, regular_designer, order])
    db_session.flush()
    active_assignment = Assignment(order_id=order.id, designer_id=regular_designer.id, status="approved")
    db_session.add(active_assignment)
    db_session.commit()
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id

    try:
        response = client.post(
            "/api/orders/duplicate-domain",
            json={"order_ids": [str(order.id)], "work_domain": "duplicate"},
            headers=headers,
        )
        board = client.get("/api/duplicate-board", headers=headers)
    finally:
        del client.app.dependency_overrides[get_current_platform_id]

    assert response.status_code == 200
    assert response.json() == {"changed_count": 1, "work_domain": "duplicate"}
    db_session.refresh(order)
    db_session.refresh(active_assignment)
    assert order.work_domain == "duplicate"
    assert active_assignment.status == "cancelled"
    assert db_session.query(WorkflowEvent).filter_by(order_id=order.id).count() == 1
    assert board.status_code == 200
    assert [column["title"] for column in board.json()["columns"]] == ["Thiếu form", "Trello A"]
    assert board.json()["columns"][0]["cards"][0]["id"] == str(order.id)


def test_trello_designer_can_claim_self_but_cannot_assign_another_user(client, db_session):
    platform = _platform(db_session)
    actor, headers = _login(client, db_session, "designer-trello", "trello-actor")
    actor.platform_id = platform.id
    other = User(
        username="trello-other",
        full_name="Trello Other",
        role="designer-trello",
        password_hash="hash",
        platform_id=platform.id,
    )
    order = Order(external_order_id="DUP-2", platform_id=platform.id, work_domain="duplicate")
    db_session.add_all([other, order])
    db_session.commit()
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id

    try:
        claim = client.post(
            "/api/duplicate-board/move",
            json={"order_id": str(order.id), "target_designer_id": str(actor.id)},
            headers=headers,
        )
        forbidden = client.post(
            "/api/duplicate-board/move",
            json={"order_id": str(order.id), "target_designer_id": str(other.id)},
            headers=headers,
        )
        release = client.post(
            "/api/duplicate-board/move",
            json={"order_id": str(order.id), "target_designer_id": None},
            headers=headers,
        )
    finally:
        del client.app.dependency_overrides[get_current_platform_id]

    assert claim.status_code == 200
    assert claim.json()["assignee_id"] == str(actor.id)
    assert forbidden.status_code == 400
    assert release.status_code == 200
    assert release.json()["assignee_id"] is None
    assert db_session.query(Assignment).filter_by(order_id=order.id, status="approved").count() == 0


def test_regular_designer_cannot_read_duplicate_board(client, db_session):
    platform = _platform(db_session)
    _, headers = _login(client, db_session, "designer", "regular-cannot-board")
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id
    try:
        response = client.get("/api/duplicate-board", headers=headers)
    finally:
        del client.app.dependency_overrides[get_current_platform_id]
    assert response.status_code == 403

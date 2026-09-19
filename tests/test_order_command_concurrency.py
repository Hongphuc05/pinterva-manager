import uuid

from app.adapters.db.models import Order, Platform, User
from app.application.auth import hash_password
from app.domain.models import OrderState


def _login(client, db_session, username: str, role: str, platform_id: uuid.UUID) -> User:
    user = User(
        username=username,
        full_name=username,
        role=role,
        platform_id=platform_id,
        password_hash=hash_password("s3cret!"),
        active=True,
    )
    db_session.add(user)
    db_session.commit()
    response = client.post("/api/login", json={"username": username, "password": "s3cret!"})
    assert response.status_code == 200
    return user


def _platform(db_session) -> Platform:
    platform = Platform(
        id=uuid.uuid4(),
        name="Concurrency command platform",
        account_username="concurrency@example.com",
        is_active=True,
    )
    db_session.add(platform)
    db_session.commit()
    return platform


def test_legacy_state_command_rejects_a_stale_order_revision(client, db_session):
    platform = _platform(db_session)
    _login(client, db_session, "state-concurrency-admin", "admin", platform.id)
    order = Order(
        platform_id=platform.id,
        external_order_id="DJ-STATE-CONFLICT",
        state=OrderState.IN_PROGRESS.value,
    )
    db_session.add(order)
    db_session.commit()

    response = client.patch(
        f"/api/orders/{order.id}/state",
        json={"state": "Review", "expected_version": order.version + 1},
        headers={"X-Platform-Id": str(platform.id)},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ORDER_VERSION_CONFLICT"
    db_session.refresh(order)
    assert order.state == OrderState.IN_PROGRESS.value


def test_assignment_command_rejects_a_stale_order_revision(client, db_session):
    platform = _platform(db_session)
    _login(client, db_session, "assignment-concurrency-admin", "admin", platform.id)
    designer = _login(client, db_session, "assignment-concurrency-designer", "designer", platform.id)
    client.post(
        "/api/login",
        json={"username": "assignment-concurrency-admin", "password": "s3cret!"},
    )
    order = Order(
        platform_id=platform.id,
        external_order_id="DJ-ASSIGN-CONFLICT",
        state=OrderState.WAITING.value,
    )
    db_session.add(order)
    db_session.commit()

    response = client.post(
        "/api/assignments",
        json={
            "order_ids": [str(order.id)],
            "designer_id": str(designer.id),
            "printerval_status": "Doing",
            "expected_versions": {str(order.id): order.version + 1},
        },
        headers={"X-Platform-Id": str(platform.id)},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ORDER_VERSION_CONFLICT"
    db_session.refresh(order)
    assert order.state == OrderState.WAITING.value


def test_designer_note_rejects_a_stale_order_revision(client, db_session):
    platform = _platform(db_session)
    _login(client, db_session, "note-concurrency-admin", "admin", platform.id)
    order = Order(platform_id=platform.id, external_order_id="DJ-NOTE-CONFLICT")
    db_session.add(order)
    db_session.commit()

    response = client.put(
        f"/api/orders/{order.id}/designer-note",
        json={"designer_note": "Ghi chú mới", "expected_version": order.version + 1},
        headers={"X-Platform-Id": str(platform.id)},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ORDER_VERSION_CONFLICT"
    db_session.refresh(order)
    assert order.designer_note == ""

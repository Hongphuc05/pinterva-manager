"""Support's "Lấy": a duplicate order goes to the in-house designer (des1) and leaves the board."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import Assignment, Order, Platform, User
from app.api.deps import get_current_platform_id, get_db
from app.api.main import create_app
from app.application.auth import create_session_token, hash_password


@pytest.fixture()
def client(db_session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: (yield db_session)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _user(db_session, role, username, platform_id):
    user = User(
        username=username, full_name=username, role=role, password_hash=hash_password("pass123"),
        active=True, platform_id=platform_id if role != "admin" else None,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _headers(user, platform_id):
    return {"Authorization": f"Bearer {create_session_token(str(user.id), user.role)}", "X-Platform-Id": str(platform_id)}


@pytest.fixture()
def setup(db_session, client, monkeypatch):
    # No Celery / Telegram side effects: the command only has to record what it queued.
    from app.workers import assignment_sync_tasks, telegram_tasks

    monkeypatch.setattr(assignment_sync_tasks.sync_printerval_assignment_request, "delay", lambda *_: None)
    monkeypatch.setattr(telegram_tasks, "safe_dispatch_telegram_task", lambda *a, **k: None)
    platform = Platform(id=uuid.uuid4(), name="Take platform", account_username=f"{uuid.uuid4()}@example.com")
    db_session.add(platform)
    db_session.commit()
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id
    ctx = type("Ctx", (), {})()
    ctx.platform = platform
    ctx.support = _user(db_session, "support", "take-support", platform.id)
    ctx.admin = _user(db_session, "admin", "take-admin", platform.id)
    ctx.des1 = _user(db_session, "designer", "des1", platform.id)
    yield ctx
    client.app.dependency_overrides.pop(get_current_platform_id, None)


def _duplicate_order(db_session, platform, code, **overrides):
    order = Order(
        external_order_id=code, platform_id=platform.id, state="IN_PROGRESS",
        duplicate_check_status="duplicate", work_domain="duplicate", **overrides,
    )
    db_session.add(order)
    db_session.commit()
    return order


def _board_cards(client, ctx):
    board = client.get("/api/duplicate-board", headers=_headers(ctx.admin, ctx.platform.id)).json()
    return {card["id"] for column in board["columns"] for card in column["cards"]}


def test_taking_a_duplicate_assigns_it_to_des1_and_removes_it_from_the_board(client, db_session, setup):
    order = _duplicate_order(db_session, setup.platform, "DJ-TAKE-1")
    assert str(order.id) in _board_cards(client, setup)

    res = client.post("/api/orders/support-take", json={"order_ids": [str(order.id)]}, headers=_headers(setup.support, setup.platform.id))

    assert res.status_code == 200 and res.json() == {"taken_count": 1}
    db_session.refresh(order)
    assert order.work_domain == "standard"  # off the duplicate board, visible to a normal designer
    assert order.duplicate_check_status == "duplicate"  # keeps the tag
    assert order.state == "IN_PROGRESS"
    assignment = db_session.query(Assignment).filter_by(order_id=order.id, status="approved").one()
    assert assignment.designer_id == setup.des1.id
    assert str(order.id) not in _board_cards(client, setup)


def test_revoking_the_assignment_puts_the_tagged_order_back_on_the_board(client, db_session, setup):
    order = _duplicate_order(db_session, setup.platform, "DJ-TAKE-2")
    client.post("/api/orders/support-take", json={"order_ids": [str(order.id)]}, headers=_headers(setup.support, setup.platform.id))

    res = client.post("/api/assignments/revoke", json={"order_ids": [str(order.id)]}, headers=_headers(setup.admin, setup.platform.id))

    assert res.status_code == 200
    db_session.refresh(order)
    assert order.work_domain == "duplicate" and order.state == "IN_PROGRESS"
    assert db_session.query(Assignment).filter_by(order_id=order.id, status="approved").count() == 0
    assert str(order.id) in _board_cards(client, setup)


def test_revoking_an_ordinary_order_still_returns_it_to_waiting(client, db_session, setup):
    order = Order(external_order_id="DJ-PLAIN", platform_id=setup.platform.id, state="IN_PROGRESS", work_domain="standard", duplicate_check_status="non_duplicate")
    db_session.add(order)
    db_session.flush()
    db_session.add(Assignment(order_id=order.id, designer_id=setup.des1.id, status="approved"))
    db_session.commit()

    client.post("/api/assignments/revoke", json={"order_ids": [str(order.id)]}, headers=_headers(setup.admin, setup.platform.id))

    db_session.refresh(order)
    assert order.state == "WAITING" and order.work_domain == "standard"


def test_only_free_duplicate_cards_can_be_taken(client, db_session, setup):
    headers = _headers(setup.support, setup.platform.id)
    not_duplicate = Order(external_order_id="DJ-NOTDUP", platform_id=setup.platform.id, state="WAITING", duplicate_check_status="uncheck", work_domain="standard")
    with_trello = _duplicate_order(db_session, setup.platform, "DJ-TRELLO")
    trello = _user(db_session, "designer-trello", "take-trello", setup.platform.id)
    db_session.add_all([not_duplicate, Assignment(order_id=with_trello.id, designer_id=trello.id, status="approved")])
    db_session.commit()

    for order in (not_duplicate, with_trello):
        res = client.post("/api/orders/support-take", json={"order_ids": [str(order.id)]}, headers=headers)
        assert res.status_code == 400, order.external_order_id
    db_session.refresh(with_trello)
    assert with_trello.work_domain == "duplicate"


def test_a_plain_designer_cannot_take_and_a_missing_des1_is_reported(client, db_session, setup):
    order = _duplicate_order(db_session, setup.platform, "DJ-TAKE-3")
    designer = _user(db_session, "designer", "take-plain", setup.platform.id)
    assert client.post("/api/orders/support-take", json={"order_ids": [str(order.id)]}, headers=_headers(designer, setup.platform.id)).status_code == 403

    setup.des1.active = False
    db_session.commit()
    res = client.post("/api/orders/support-take", json={"order_ids": [str(order.id)]}, headers=_headers(setup.support, setup.platform.id))
    assert res.status_code == 400 and "des1" in res.json()["detail"]

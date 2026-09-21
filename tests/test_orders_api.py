from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import (
    Assignment,
    Order,
    Platform,
    PrintervalAssignmentRequest,
    TelegramActionLog,
    User,
    WorkflowEvent,
)
from app.api.deps import DEFAULT_PLATFORM_ID, get_current_platform_id, get_db
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


def _login(client, db_session, role, username="user1", platform_id=None):
    existing = db_session.query(User).filter(User.username == username).first()
    if not existing:
        if role != "admin" and platform_id is None:
            plat = db_session.query(Platform).first()
            if not plat:
                plat = _seed_platform(db_session)
            platform_id = plat.id

        user = User(
            username=username, full_name=username, role=role,
            password_hash=hash_password("s3cret!"),
            platform_id=platform_id if role != "admin" else None,
        )
        db_session.add(user)
        db_session.commit()
        existing = user
    client.post("/api/login", json={"username": username, "password": "s3cret!"})
    return existing


def _seed_platform(db_session):
    platform = Platform(
        id=DEFAULT_PLATFORM_ID,
        name="Default Platform",
        account_username="admin",
        is_active=True,
    )
    db_session.merge(platform)
    db_session.commit()
    return platform


def test_api_orders_list_returns_all_orders_for_admin(client, db_session):
    _seed_platform(db_session)
    _login(client, db_session, "admin", "admin_orders_list")
    db_session.add(Order(external_order_id="DJ1", platform_id=DEFAULT_PLATFORM_ID, state=OrderState.OPEN.value))
    db_session.commit()

    resp = client.get("/api/orders")

    assert resp.status_code == 200
    ids = [o["external_order_id"] for o in resp.json()["orders"]]
    assert ids == ["DJ1"]


def test_api_orders_list_requires_auth(client):
    resp = client.get("/api/orders")
    assert resp.status_code == 401


def test_api_orders_list_filters_by_status(client, db_session):
    _seed_platform(db_session)
    _login(client, db_session, "admin", "admin_orders_filter")
    db_session.add(Order(external_order_id="DJ1", platform_id=DEFAULT_PLATFORM_ID, state=OrderState.OPEN.value))
    db_session.add(Order(external_order_id="DJ2", platform_id=DEFAULT_PLATFORM_ID, state=OrderState.IN_PROGRESS.value))
    db_session.commit()

    resp = client.get("/api/orders", params={"status": OrderState.OPEN.value})

    ids = [o["external_order_id"] for o in resp.json()["orders"]]
    assert ids == ["DJ1"]


def test_admin_can_reopen_paid_done_order_without_removing_payment_marker(client, db_session):
    _seed_platform(db_session)
    _login(client, db_session, "admin", "reopen-paid-done-admin")
    paid_at = datetime.now(UTC)
    order = Order(
        external_order_id="DJ-PAID-REOPEN",
        platform_id=DEFAULT_PLATFORM_ID,
        state=OrderState.DONE.value,
        is_paid=True,
        paid_at=paid_at,
    )
    db_session.add(order)
    db_session.commit()

    response = client.patch(f"/api/orders/{order.id}/state", json={"state": "FIX"})

    assert response.status_code == 200
    db_session.refresh(order)
    assert order.state == OrderState.REVISION.value
    assert order.is_paid is True
    assert order.paid_at == paid_at


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
    _login(client, db_session, "admin", "bulk_admin")
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


def test_api_bulk_delete_removes_telegram_fix_callback_logs(client, db_session):
    """A Fix order creates Telegram callback logs that must not block permanent deletion."""
    _seed_platform(db_session)
    _login(client, db_session, "admin", "delete_fix_admin")
    order = Order(
        external_order_id="DJ4006431",
        platform_id=DEFAULT_PLATFORM_ID,
        state=OrderState.REVISION.value,
    )
    db_session.add(order)
    db_session.flush()
    callback = TelegramActionLog(
        order_id=order.id,
        action_type="APPROVE_FIX_USE_OUTSOURCE",
        callback_token="delete_fix_callback_token",
    )
    db_session.add(callback)
    db_session.commit()

    resp = client.post("/api/orders/bulk-delete", json={"order_ids": [str(order.id)]})

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "deleted_count": 1}
    assert db_session.get(Order, order.id) is None
    assert db_session.get(TelegramActionLog, callback.id) is None


def test_api_assign_order_skips_printerval_sync_when_designer_not_registered(client, db_session, monkeypatch):
    """Designer has no printerval_designer_option -> must not enqueue anything, and
    say so plainly rather than silently doing nothing."""
    from app.workers import assignment_sync_tasks

    calls = []
    monkeypatch.setattr(assignment_sync_tasks.sync_assignment_to_printerval_task, "delay", lambda *a: calls.append(a))
    _login(client, db_session, "admin", "assign_admin1")
    designer = User(username="des2", full_name="Chưa Đăng Ký", role="designer", password_hash="hash")
    order = Order(external_order_id="A1", state=OrderState.DISCOVERED.value)
    db_session.add_all([designer, order])
    db_session.commit()

    resp = client.post(f"/api/orders/{order.id}/assign", json={"designer_id": str(designer.id)})

    assert resp.status_code == 200
    assert calls == []
    assert "CHƯA có tên đăng ký trên Printerval" in resp.json()["printerval_sync_message"]


def test_api_assign_order_enqueues_printerval_sync_when_designer_registered(client, db_session, monkeypatch):
    from app.workers import assignment_sync_tasks

    calls = []
    monkeypatch.setattr(assignment_sync_tasks.sync_assignment_to_printerval_task, "delay", lambda *a: calls.append(a))
    _login(client, db_session, "admin", "assign_admin2")
    designer = User(
        username="des3", full_name="Linh Designer", role="designer", password_hash="hash",
        printerval_designer_option="Linh Designer - 2D Prin",
    )
    order = Order(external_order_id="A2", state=OrderState.DISCOVERED.value)
    db_session.add_all([designer, order])
    db_session.commit()

    resp = client.post(f"/api/orders/{order.id}/assign", json={"designer_id": str(designer.id)})

    assert resp.status_code == 200
    assert calls == [(str(order.id), str(designer.id))]
    assert "đang đồng bộ sang Printerval" in resp.json()["printerval_sync_message"]


def test_api_bulk_assign_orders_enqueues_printerval_sync_per_order_when_registered(client, db_session, monkeypatch):
    from app.workers import assignment_sync_tasks

    calls = []
    monkeypatch.setattr(assignment_sync_tasks.sync_assignment_to_printerval_task, "delay", lambda *a: calls.append(a))
    _login(client, db_session, "admin", "bulk_admin2")
    designer = User(
        username="des4", full_name="Linh Designer", role="designer", password_hash="hash",
        printerval_designer_option="Linh Designer - 2D Prin",
    )
    order1 = Order(external_order_id="C1", state=OrderState.DISCOVERED.value)
    order2 = Order(external_order_id="C2", state=OrderState.DISCOVERED.value)
    db_session.add_all([designer, order1, order2])
    db_session.commit()

    resp = client.post(
        "/api/orders/bulk-assign",
        json={"order_ids": [str(order1.id), str(order2.id)], "designer_id": str(designer.id)},
    )

    assert resp.status_code == 200
    assert len(calls) == 2
    assert {c[0] for c in calls} == {str(order1.id), str(order2.id)}
    assert "đồng bộ sang Printerval" in resp.json()["message"]


def test_api_bulk_printerval_assignment_records_one_request_per_order(client, db_session, monkeypatch):
    from app.workers import assignment_sync_tasks

    calls = []
    monkeypatch.setattr(
        assignment_sync_tasks.sync_printerval_assignment_request,
        "delay",
        lambda *args: calls.append(args),
    )
    platform = Platform(
        name="P1",
        account_username="mother@example.com",
        account_password="stored-secret",
    )
    designer = User(username="des-bulk-new", full_name="Linh", role="designer", password_hash="hash")
    db_session.add_all([platform, designer])
    db_session.flush()
    order1 = Order(external_order_id="PA1", platform_id=platform.id)
    order2 = Order(external_order_id="PA2", platform_id=platform.id)
    db_session.add_all([order1, order2])
    db_session.commit()
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id
    _login(client, db_session, "admin", "bulk_printerval_admin")

    try:
        response = client.post(
            "/api/orders/bulk-printerval-assignment",
            json={
                "order_ids": [str(order1.id), str(order2.id)],
                "designer_id": str(designer.id),
                "printerval_designer": "Nguyễn Thị Thuý Hường - 2D Prin",
                "printerval_status": "Doing",
            },
        )
    finally:
        del client.app.dependency_overrides[get_current_platform_id]

    assert response.status_code == 200
    assert response.json()["queued_count"] == 2
    assert len(calls) == 2
    assert db_session.query(PrintervalAssignmentRequest).count() == 2
    assert db_session.query(Assignment).filter_by(status="approved").count() == 2


def test_api_assignments_replaces_the_bulk_printerval_assignment_contract(client, db_session, monkeypatch):
    from app.workers import assignment_sync_tasks

    calls = []
    monkeypatch.setattr(
        assignment_sync_tasks.sync_printerval_assignment_request,
        "delay",
        lambda *args: calls.append(args),
    )
    platform = Platform(name="P1 command", account_username="command@example.com")
    designer = User(username="des-command", full_name="Mai", role="designer", password_hash="hash")
    db_session.add_all([platform, designer])
    db_session.flush()
    order1 = Order(external_order_id="CMD1", platform_id=platform.id)
    order2 = Order(external_order_id="CMD2", platform_id=platform.id)
    db_session.add_all([order1, order2])
    db_session.commit()
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id
    _login(client, db_session, "admin", "assignments_command_admin")

    try:
        response = client.post(
            "/api/assignments",
            json={
                "order_ids": [str(order1.id), str(order2.id)],
                "designer_id": str(designer.id),
                "printerval_designer": "Nguyễn Thị Thuý Hường - 2D Prin",
                "printerval_status": "Doing",
            },
        )
    finally:
        del client.app.dependency_overrides[get_current_platform_id]

    assert response.status_code == 202
    assert response.json()["queued_count"] == 2
    assert len(response.json()["request_ids"]) == 2
    assert len(calls) == 2


def test_api_assignments_queues_status_only_requests(client, db_session, monkeypatch):
    from app.workers import assignment_sync_tasks

    calls = []
    monkeypatch.setattr(
        assignment_sync_tasks.sync_printerval_assignment_request,
        "delay",
        lambda *args: calls.append(args),
    )
    platform = Platform(name="P1 status only", account_username="status-only@example.com")
    db_session.add(platform)
    db_session.flush()
    entered_review_at = datetime.now(UTC) - timedelta(days=1)
    order1 = Order(
        external_order_id="STATUS1",
        platform_id=platform.id,
        state=OrderState.QC_PENDING.value,
        status_changed_at=entered_review_at,
        review_submitted_at=entered_review_at,
    )
    order2 = Order(
        external_order_id="STATUS2",
        platform_id=platform.id,
        state=OrderState.QC_PENDING.value,
        status_changed_at=entered_review_at,
        review_submitted_at=entered_review_at,
    )
    db_session.add_all([order1, order2])
    db_session.commit()
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id
    _login(client, db_session, "admin", "status_only_admin")

    try:
        response = client.post(
            "/api/assignments",
            json={
                "order_ids": [str(order1.id), str(order2.id)],
                "printerval_status": "Review",
            },
        )
    finally:
        del client.app.dependency_overrides[get_current_platform_id]

    assert response.status_code == 202
    assert response.json()["queued_count"] == 2
    requests = db_session.query(PrintervalAssignmentRequest).order_by(
        PrintervalAssignmentRequest.order_id
    ).all()
    assert len(requests) == 2
    assert {request.designer_option for request in requests} == {""}
    assert {request.target_status for request in requests} == {"Review"}
    assert {call[0] for call in calls} == {str(request.id) for request in requests}
    db_session.refresh(order1)
    db_session.refresh(order2)
    for order in (order1, order2):
        assert order.state == OrderState.QC_PENDING.value
        assert order.status_changed_at == entered_review_at
        assert order.review_submitted_at == entered_review_at


def test_api_assignments_accepts_lowercase_status_and_legacy_platform_fields(
    client, db_session, monkeypatch
):
    from app.workers import assignment_sync_tasks

    monkeypatch.setattr(assignment_sync_tasks.sync_printerval_assignment_request, "delay", lambda *_: None)
    platform = Platform(name="P1 normalized status", account_username="normalized@example.com")
    designer = User(
        username="normalized-designer",
        full_name="Normalized Designer",
        role="designer",
        password_hash="hash",
    )
    db_session.add_all([platform, designer])
    db_session.flush()
    order = Order(external_order_id="NORMALIZED1", platform_id=platform.id)
    db_session.add(order)
    db_session.commit()
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id
    _login(client, db_session, "admin", "normalized_status_admin")

    try:
        response = client.post(
            "/api/assignments",
            json={
                "order_ids": [str(order.id)],
                "designer_id": str(designer.id),
                "platform_designer": "Nguyễn Thị Thuý Hường - 2D Prin",
                "platform_status": " waiting ",
            },
        )
    finally:
        del client.app.dependency_overrides[get_current_platform_id]

    assert response.status_code == 202
    request = (
        db_session.query(PrintervalAssignmentRequest)
        .filter(PrintervalAssignmentRequest.order_id == order.id)
        .one()
    )
    assert request.target_status == "Waiting"


def test_finance_rates_payment_and_workload_include_duplicate_trello_orders(client, db_session):
    platform = Platform(name="Finance platform", account_username="finance@example.com")
    trello_designer = User(
        username="finance-trello",
        full_name="Finance Trello",
        role="designer-trello",
        password_hash=hash_password("s3cret!"),
        platform_id=None,
    )
    db_session.add(platform)
    db_session.flush()
    duplicate_order = Order(
        external_order_id="DUP-FINANCE-1",
        platform_id=platform.id,
        state=OrderState.QC_PENDING.value,
        work_domain="duplicate",
    )
    db_session.add_all([trello_designer, duplicate_order])
    db_session.flush()
    db_session.add(
        Assignment(
            order_id=duplicate_order.id,
            designer_id=trello_designer.id,
            status="approved",
        )
    )
    db_session.commit()
    _login(client, db_session, "admin", "finance-rates-admin")
    headers = {"X-Platform-Id": str(platform.id)}

    rates = client.get("/api/finance/rates", headers=headers)
    assert rates.status_code == 200
    assert rates.json() == {"standard_rate": 40000, "duplicate_rate": 40000}

    updated = client.put(
        "/api/finance/rates",
        headers=headers,
        json={"standard_rate": 50000, "duplicate_rate": 45000},
    )
    assert updated.status_code == 200
    assert updated.json() == {"standard_rate": 50000, "duplicate_rate": 45000}
    db_session.refresh(platform)
    assert platform.standard_order_rate == 50000
    assert platform.duplicate_order_rate == 45000

    workload = client.get("/api/designers/workload", headers=headers)
    assert workload.status_code == 200
    designer_workload = next(item for item in workload.json() if item["id"] == str(trello_designer.id))
    assert designer_workload["total_orders"] == 1
    assert designer_workload["orders"][0]["work_domain"] == "duplicate"

    paid = client.post(
        "/api/finance/mark-paid",
        json={"order_ids": [str(duplicate_order.id)]},
    )
    assert paid.status_code == 200
    db_session.refresh(duplicate_order)
    assert duplicate_order.is_paid is True
    assert duplicate_order.state == OrderState.DONE.value
    assert duplicate_order.status_changed_at is not None
    event = db_session.query(WorkflowEvent).filter(WorkflowEvent.order_id == duplicate_order.id).one()
    assert event.from_state == OrderState.QC_PENDING.value
    assert event.to_state == OrderState.DONE.value

    board = client.get("/api/duplicate-board", headers=headers)
    assert board.status_code == 200
    done_column = next(column for column in board.json()["columns"] if column["id"] == "done")
    done_cards = done_column["cards"]
    assert any(card["id"] == str(duplicate_order.id) and card["is_paid"] for card in done_cards)


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


def test_api_sync_status_serializes_a_real_sync_state_row(client, db_session, monkeypatch):
    """Regression test: SyncStatusResponse.model_validate(state) needs
    from_attributes=True to read off the ORM object — the other sync-status tests all
    happen to hit the `state is None` branch (constructed from kwargs instead), which
    let this 500 slip through undetected."""
    from datetime import UTC, datetime

    from app.adapters.db.models import Platform, PlatformSyncState
    from app.api.deps import get_current_platform_id

    platform = Platform(name="P1", account_username="acc1@printerval.com")
    db_session.add(platform)
    db_session.flush()
    db_session.add(
        PlatformSyncState(
            platform_id=platform.id,
            is_running=False,
            last_started_at=datetime.now(UTC),
            last_finished_at=datetime.now(UTC),
            last_result={"checked": 2, "updated": 1},
        )
    )
    db_session.commit()

    app = client.app
    app.dependency_overrides[get_current_platform_id] = lambda: platform.id
    _login(client, db_session, "admin")

    try:
        resp = client.get("/api/orders/sync-status")
    finally:
        del app.dependency_overrides[get_current_platform_id]

    assert resp.status_code == 200
    body = resp.json()
    assert body["is_running"] is False
    assert body["last_result"] == {"checked": 2, "updated": 1}


def test_api_update_order_state_flow(client, db_session):
    from app.adapters.db.models import Assignment, Order, Platform
    from app.api.deps import get_current_platform_id

    platform = Platform(name="P1", account_username="acc1@printerval.com")
    db_session.add(platform)
    db_session.flush()

    order = Order(external_order_id="DJ1001", platform_id=platform.id, state="OPEN")
    db_session.add(order)
    db_session.commit()

    app = client.app
    app.dependency_overrides[get_current_platform_id] = lambda: platform.id

    # 1. Admin converts OPEN -> DOING
    _login(client, db_session, "admin", username="admin_flow")
    resp = client.patch(f"/api/orders/{order.id}/state", json={"state": "Doing"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "IN_PROGRESS"

    # 2. Designer converts DOING -> REVIEW
    des = _login(client, db_session, "designer", username="des_flow")
    db_session.add(Assignment(order_id=order.id, designer_id=des.id, status="approved"))
    db_session.commit()

    resp = client.patch(f"/api/orders/{order.id}/state", json={"state": "Review"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "QC_PENDING"

    # 3. Designer attempts to convert to DONE (forbidden!)
    resp = client.patch(f"/api/orders/{order.id}/state", json={"state": "Done"})
    assert resp.status_code == 403

    # 4. Admin reviews and requests FIX (REVISION)
    client.post("/api/login", json={"username": "admin_flow", "password": "s3cret!"})
    resp = client.patch(f"/api/orders/{order.id}/state", json={"state": "Fix"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "REVISION"

    # 5. Admin explicitly releases the Fix back to the assigned designer.
    resp = client.post(
        f"/api/orders/{order.id}/approve-fix",
        json={"designer_id": str(des.id), "designer_note": "Sửa theo góp ý QC"},
    )
    assert resp.status_code == 200
    assert resp.json()["fix_approved_by_admin"] is True

    # 6. Designer re-submits to REVIEW
    client.post("/api/login", json={"username": "des_flow", "password": "s3cret!"})
    resp = client.patch(f"/api/orders/{order.id}/state", json={"state": "Review"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "QC_PENDING"

    # 7. Admin marks DONE
    client.post("/api/login", json={"username": "admin_flow", "password": "s3cret!"})
    resp = client.patch(f"/api/orders/{order.id}/state", json={"state": "Done"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "DONE"

    # 8. Check workload API
    resp = client.get("/api/designers/workload")
    assert resp.status_code == 200
    workload = resp.json()
    assert len(workload) >= 1
    des_stat = next(item for item in workload if item["id"] == str(des.id))
    assert des_stat["done_count"] == 1
    assert des_stat["total_orders"] == 1

    # 9. Check orders history API
    resp = client.get("/api/orders-history")
    assert resp.status_code == 200
    hist_data = resp.json()
    assert hist_data["total"] >= 1
    assert len(hist_data["items"]) >= 1
    # Check that events have descriptions
    assert any("Admin" in (item.get("description") or "") or "Designer" in (item.get("description") or "") for item in hist_data["items"])

    # 9. Check single order history API
    resp = client.get(f"/api/orders/{order.id}/history")
    assert resp.status_code == 200
    single_hist = resp.json()
    assert len(single_hist) >= 4


def test_resolve_missing_template_returns_assigned_order_to_doing(client, db_session):
    import uuid
    platform = Platform(id=uuid.uuid4(), name="Missing template platform", account_username="missing@example.com")
    designer = User(
        username="missing-designer",
        full_name="Missing Designer",
        role="designer",
        password_hash=hash_password("s3cret!"),
        platform_id=platform.id,
    )
    db_session.add_all([platform, designer])
    db_session.flush()
    order = Order(
        external_order_id="MISSING-TEMPLATE-1",
        platform_id=platform.id,
        state=OrderState.IN_PROGRESS.value,
        template_missing=True,
        note_outsource="Printerval QC outsource note",
    )
    db_session.add(order)
    db_session.flush()
    assignment = Assignment(order_id=order.id, designer_id=designer.id, status="approved", sub_status="waiting_template")
    db_session.add(assignment)
    db_session.commit()
    _login(client, db_session, "admin", username="missing-template-admin")

    response = client.post(
        f"/api/orders/{order.id}/resolve-missing-template",
        json={"designer_note": "Temp: https://example.com/template"},
    )

    assert response.status_code == 200
    assert response.json()["state"] == OrderState.IN_PROGRESS.value
    db_session.refresh(order)
    db_session.refresh(assignment)
    assert order.template_missing is False
    assert order.designer_note == "Temp: https://example.com/template"
    assert order.suppress_note_outsource_for_designer is True
    assert assignment.sub_status == "todo"

    # The resolved template note is explicitly released to the assigned
    # Designer, while the upstream source note remains private.
    _login(client, db_session, "designer", username="missing-designer")
    detail_res = client.get(f"/api/orders/{order.id}")
    assert detail_res.status_code == 200
    detail_data = detail_res.json()["order"]
    assert detail_data["note_outsource"] == ""
    assert detail_data["designer_note"] == "Temp: https://example.com/template"

    list_res = client.get("/api/orders")
    assert list_res.status_code == 200
    matching = [o for o in list_res.json()["orders"] if o["id"] == str(order.id)]
    assert len(matching) == 1
    assert matching[0]["note_outsource"] == ""
    assert matching[0]["designer_note"] == "Temp: https://example.com/template"

    my_tasks_res = client.get("/api/my-tasks")
    assert my_tasks_res.status_code == 200
    designer_task = next(task for task in my_tasks_res.json()["tasks"] if task["order"]["id"] == str(order.id))
    assert designer_task["order"]["note_outsource"] == ""
    assert designer_task["order"]["designer_note"] == "Temp: https://example.com/template"

    # Verify Admin view: note_outsource is preserved
    _login(client, db_session, "admin", username="missing-template-admin-2")
    admin_detail_res = client.get(f"/api/orders/{order.id}")
    assert admin_detail_res.status_code == 200
    assert admin_detail_res.json()["order"]["note_outsource"] == "Printerval QC outsource note"
    assert admin_detail_res.json()["order"]["designer_note"] == "Temp: https://example.com/template"


def test_api_approve_and_reject_fix_flow(client, db_session, monkeypatch):
    import uuid

    from app.adapters.db.models import Assignment, Order, Platform
    from app.api.deps import get_current_platform_id
    from app.domain.models import OrderState

    platform = Platform(
        id=uuid.uuid4(),
        name="Test Fix Platform",
        account_username="fix_test@example.com",
        account_password="password123",
        team_outsource="2D",
    )
    db_session.add(platform)
    db_session.flush()

    app = client.app
    app.dependency_overrides[get_current_platform_id] = lambda: platform.id

    from app.workers import assignment_sync_tasks

    sync_calls: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        assignment_sync_tasks.sync_order_review_to_printerval_task,
        "delay",
        lambda *args, **kwargs: sync_calls.append((args, kwargs)),
    )

    _login(client, db_session, "admin", username="admin_fix_test")
    des = _login(client, db_session, "designer", username="des_fix_test")

    order = Order(
        id=uuid.uuid4(),
        platform_id=platform.id,
        external_order_id="DJ_FIX_001",
        state=OrderState.IN_PROGRESS.value,
        note_outsource="",
    )
    db_session.add(order)
    db_session.flush()

    asgn = Assignment(
        id=uuid.uuid4(),
        order_id=order.id,
        designer_id=des.id,
        status="approved",
    )
    db_session.add(asgn)
    db_session.commit()

    # 1. Designer submits with drive_url -> Review
    client.post("/api/login", json={"username": "des_fix_test", "password": "s3cret!"})
    resp = client.patch(
        f"/api/orders/{order.id}/state",
        json={"state": "Review", "drive_url": "https://drive.google.com/test_fix_v1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "QC_PENDING"
    assert data["note_outsource"] == "https://drive.google.com/test_fix_v1"

    # 2. Printerval returns Fix with new note outsource
    db_session.refresh(order)
    order.state = OrderState.REVISION.value
    order.note_outsource = "fix https://prnt.sc/test1234 lech mau áo"
    order.fix_approved_by_admin = False
    db_session.commit()

    # 3. Admin approves fix for designer
    sync_count_before_approval = len(sync_calls)
    client.post("/api/login", json={"username": "admin_fix_test", "password": "s3cret!"})
    resp = client.post(
        f"/api/orders/{order.id}/approve-fix",
        json={
            "note_outsource": "fix https://prnt.sc/test1234 lech mau áo - admin verified",
            "designer_note": "Sửa lại màu áo theo góp ý đã được Admin kiểm tra.",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["fix_approved_by_admin"] is True
    assert "admin verified" in data["note_outsource"]
    # Printerval has already set Fix. Admin approval only releases the local
    # assignment; it must not overwrite the source status again.
    assert len(sync_calls) == sync_count_before_approval

    # 4. Check TODO filter returns this order
    resp = client.get("/api/orders?status=TODO")
    assert resp.status_code == 200
    todo_orders = resp.json()["orders"]
    assert any(o["id"] == str(order.id) for o in todo_orders)

    # 5. Admin rejects fix to review
    resp = client.post(
        f"/api/orders/{order.id}/reject-fix-to-review",
        json={"note_outsource": "https://drive.google.com/test_fix_v1 - mau da dung voi mockup"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "QC_PENDING"
    assert data["fix_rejected_by_admin"] is True
    assert "mau da dung voi mockup" in data["note_outsource"]

    db_session.refresh(order)
    assert order.state == OrderState.QC_PENDING.value
    assert order.fix_approved_by_admin is False
    assert order.fix_rejected_by_admin is True

    review_orders = client.get("/api/orders?status=REVIEW").json()["orders"]
    fix_orders = client.get("/api/orders?status=FIX").json()["orders"]
    assert any(item["id"] == str(order.id) for item in review_orders)
    assert all(item["id"] != str(order.id) for item in fix_orders)


def test_approve_fix_uses_admin_approved_outsource_note_when_admin_note_is_empty(client, db_session):
    platform = _seed_platform(db_session)
    _login(client, db_session, "admin", "fallback-fix-admin")
    designer = _login(client, db_session, "designer", "fallback-fix-designer", platform.id)
    order = Order(
        external_order_id="DJ-FIX-FALLBACK",
        platform_id=platform.id,
        state=OrderState.REVISION.value,
        note_outsource="QC source note must remain private",
    )
    db_session.add(order)
    db_session.flush()
    db_session.add(Assignment(order_id=order.id, designer_id=designer.id, status="approved"))
    db_session.commit()

    response = client.post(
        f"/api/orders/{order.id}/approve-fix",
        json={"note_outsource": "Admin approved instruction copied for Designer"},
    )

    assert response.status_code == 200
    db_session.refresh(order)
    assert order.designer_note == "Admin approved instruction copied for Designer"
    assert order.note_outsource == "Admin approved instruction copied for Designer"
    assert order.designer_note_released_for_fix is True


def test_api_orders_list_returns_active_assignment_id_for_designer(client, db_session):
    _seed_platform(db_session)
    designer = _login(client, db_session, "designer", "designer_orders_assignment")
    order = Order(
        external_order_id="DJ-ASSIGNMENT-ID",
        platform_id=DEFAULT_PLATFORM_ID,
        state=OrderState.WAITING.value,
    )
    db_session.add(order)
    db_session.flush()
    assignment = Assignment(order_id=order.id, designer_id=designer.id, status="approved")
    db_session.add(assignment)
    db_session.commit()

    response = client.get("/api/orders")

    assert response.status_code == 200
    assert response.json()["orders"] == [
        {
            **response.json()["orders"][0],
            "id": str(order.id),
            "assignment_id": str(assignment.id),
        }
    ]


def test_designer_cannot_list_view_or_update_an_unreleased_fix(client, db_session):
    _seed_platform(db_session)
    designer = _login(client, db_session, "designer", "unreleased_fix_orders_designer")
    order = Order(
        external_order_id="DJ-UNRELEASED-FIX",
        platform_id=DEFAULT_PLATFORM_ID,
        state=OrderState.REVISION.value,
        fix_approved_by_admin=False,
    )
    db_session.add(order)
    db_session.flush()
    db_session.add(Assignment(order_id=order.id, designer_id=designer.id, status="approved"))
    db_session.commit()

    assert client.get("/api/orders").json()["orders"] == []
    assert client.get(f"/api/orders/{order.id}").status_code == 404
    assert client.get(f"/api/orders/{order.id}/history").status_code == 404
    assert client.get("/api/orders-history", params={"order_id": str(order.id)}).json()["items"] == []
    response = client.patch(
        f"/api/orders/{order.id}/state",
        json={"state": "QC_PENDING", "drive_url": "https://drive.google.com/file/d/unreleased/view"},
    )
    assert response.status_code == 409

    order.fix_approved_by_admin = True
    db_session.commit()

    assert [item["id"] for item in client.get("/api/orders").json()["orders"]] == [str(order.id)]


def test_designer_submit_review_does_not_notify_admin_telegram(client, db_session, monkeypatch):
    _seed_platform(db_session)
    designer = _login(client, db_session, "designer", "submit_review_no_telegram_admin")
    order = Order(
        external_order_id="DJ-SUBMIT-NO-TELE-ADMIN",
        platform_id=DEFAULT_PLATFORM_ID,
        state=OrderState.IN_PROGRESS.value,
        product_name="T-Shirt 2D",
    )
    db_session.add(order)
    db_session.flush()
    db_session.add(Assignment(order_id=order.id, designer_id=designer.id, status="approved"))
    db_session.commit()

    # Track any calls to async_notify_admin_review_submitted
    from app.workers import telegram_tasks
    admin_review_calls = []
    monkeypatch.setattr(
        telegram_tasks.async_notify_admin_review_submitted,
        "delay",
        lambda *args: admin_review_calls.append(args),
    )

    response = client.patch(
        f"/api/orders/{order.id}/state",
        json={"state": "QC_PENDING", "drive_url": "https://drive.google.com/file/d/submitted/view"},
    )
    assert response.status_code == 200
    db_session.refresh(order)
    assert order.state == OrderState.QC_PENDING.value
    # Must NOT dispatch any notification to admin for submitted review
    assert len(admin_review_calls) == 0

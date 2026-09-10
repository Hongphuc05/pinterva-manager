import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import Assignment, Order, Platform, PrintervalAssignmentRequest, User
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


def _login(client, db_session, role, username="user1"):
    user = User(
        username=username, full_name=username, role=role,
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(user)
    db_session.commit()
    client.post("/api/login", json={"username": username, "password": "s3cret!"})
    return user


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

    # 5. Designer re-submits to REVIEW
    client.post("/api/login", json={"username": "des_flow", "password": "s3cret!"})
    resp = client.patch(f"/api/orders/{order.id}/state", json={"state": "Review"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "QC_PENDING"

    # 6. Admin marks DONE
    client.post("/api/login", json={"username": "admin_flow", "password": "s3cret!"})
    resp = client.patch(f"/api/orders/{order.id}/state", json={"state": "Done"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "DONE"

    # 7. Check workload API
    resp = client.get("/api/designers/workload")
    assert resp.status_code == 200
    workload = resp.json()
    assert len(workload) >= 1
    des_stat = next(item for item in workload if item["id"] == str(des.id))
    assert des_stat["done_count"] == 1
    assert des_stat["total_orders"] == 1

    # 8. Check orders history API
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


def test_api_approve_and_reject_fix_flow(client, db_session):
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
    client.post("/api/login", json={"username": "admin_fix_test", "password": "s3cret!"})
    resp = client.post(
        f"/api/orders/{order.id}/approve-fix",
        json={"note_outsource": "fix https://prnt.sc/test1234 lech mau áo - admin verified"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["fix_approved_by_admin"] is True
    assert "admin verified" in data["note_outsource"]

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
    assert "mau da dung voi mockup" in data["note_outsource"]

    db_session.refresh(order)
    assert order.state == OrderState.QC_PENDING.value
    assert order.fix_approved_by_admin is False

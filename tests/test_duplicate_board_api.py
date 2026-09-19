import uuid

import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import (
    Assignment,
    Order,
    Platform,
    PrintervalAssignmentRequest,
    User,
    WorkflowEvent,
)
from app.api.deps import get_current_platform_id, get_db
from app.api.main import create_app
from app.application.auth import create_session_token, hash_password


@pytest.fixture()
def client(db_session):
    app = create_app()

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login(client, db_session, role: str, username: str, platform_id: uuid.UUID | None = None) -> tuple[User, dict[str, str]]:
    user = User(
        username=username,
        full_name=username,
        role=role,
        password_hash=hash_password("pass123"),
        active=True,
        platform_id=platform_id if role not in ("admin", "support") else None,
    )
    db_session.add(user)
    db_session.commit()
    token = create_session_token(str(user.id), role)
    client.cookies.set("tacahu_session", token)
    headers = {"Authorization": f"Bearer {token}"}
    if platform_id:
        headers["X-Platform-Id"] = str(platform_id)
    return user, headers


def _platform(db_session, name: str = "Duplicate board platform") -> Platform:
    platform = Platform(id=uuid.uuid4(), name=name, account_username=f"{uuid.uuid4()}@example.com")
    db_session.add(platform)
    db_session.commit()
    return platform


def test_admin_can_put_orders_in_duplicate_domain_and_board_shows_missing_form(
    client, db_session, monkeypatch
):
    platform = _platform(db_session)
    admin, headers = _login(client, db_session, "admin", "duplicate-domain-admin", platform.id)
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
    delayed_requests: list[str] = []
    from app.workers import assignment_sync_tasks

    monkeypatch.setattr(
        assignment_sync_tasks.sync_printerval_assignment_request,
        "delay",
        lambda request_id: delayed_requests.append(request_id),
    )

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
    assert order.state == "IN_PROGRESS"
    request = db_session.query(PrintervalAssignmentRequest).filter_by(order_id=order.id).one()
    assert request.target_status == "Doing"
    assert request.designer_option == ""
    assert request.internal_designer_id == admin.id
    assert delayed_requests == [str(request.id)]
    assert active_assignment.status == "cancelled"
    assert db_session.query(WorkflowEvent).filter_by(order_id=order.id).count() == 1
    assert board.status_code == 200
    assert [column["title"] for column in board.json()["columns"]] == ["Đơn hàng", "Thiếu form", "Trello A", "Done"]
    # New duplicate order starts in the shared board's Doing queue.
    assert board.json()["columns"][0]["cards"][0]["id"] == str(order.id)
    assert board.json()["columns"][0]["metrics"] == {
        "total": 1,
        "doing": 1,
        "review": 0,
        "fix": 0,
        "done": 0,
    }
    assert board.json()["cross_designer_drag_enabled"] is True


def test_duplicate_domain_rejects_a_stale_order_revision(client, db_session):
    platform = _platform(db_session)
    _admin, headers = _login(client, db_session, "admin", "duplicate-version-admin", platform.id)
    order = Order(external_order_id="DUP-VERSION", platform_id=platform.id)
    db_session.add(order)
    db_session.commit()
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id

    try:
        response = client.post(
            "/api/orders/duplicate-domain",
            json={
                "order_ids": [str(order.id)],
                "work_domain": "duplicate",
                "expected_versions": {str(order.id): order.version + 1},
            },
            headers=headers,
        )
    finally:
        del client.app.dependency_overrides[get_current_platform_id]

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ORDER_VERSION_CONFLICT"
    db_session.refresh(order)
    assert order.work_domain == "standard"


def test_move_card_between_orders_missing_form_designer_and_done(client, db_session):
    platform = _platform(db_session)
    admin, headers = _login(client, db_session, "admin", "admin-move-tester", platform.id)
    trello_designer = User(
        username="trello-des-b",
        full_name="Trello B",
        role="designer-trello",
        password_hash="hash",
        platform_id=platform.id,
    )
    order = Order(external_order_id="DUP-FLOW", platform_id=platform.id, work_domain="duplicate")
    db_session.add_all([trello_designer, order])
    db_session.commit()
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id

    try:
        # 1. Move to "missing_form"
        res_mf = client.post(
            "/api/duplicate-board/move",
            json={"order_id": str(order.id), "target_column_id": "missing_form"},
            headers=headers,
        )
        assert res_mf.status_code == 200
        assert res_mf.json()["template_missing"] is True

        board1 = client.get("/api/duplicate-board", headers=headers).json()
        assert len(board1["columns"][1]["cards"]) == 1
        assert board1["columns"][1]["cards"][0]["id"] == str(order.id)

        # 2. Claim to Trello B designer
        res_des = client.post(
            "/api/duplicate-board/move",
            json={"order_id": str(order.id), "target_designer_id": str(trello_designer.id)},
            headers=headers,
        )
        assert res_des.status_code == 200
        assert res_des.json()["assignee_id"] == str(trello_designer.id)
        assert res_des.json()["template_missing"] is False

        board2 = client.get("/api/duplicate-board", headers=headers).json()
        assert len(board2["columns"][2]["cards"]) == 1
        assert board2["columns"][2]["cards"][0]["id"] == str(order.id)

        # 3. Move to Done
        res_done = client.post(
            "/api/duplicate-board/move",
            json={"order_id": str(order.id), "target_column_id": "done"},
            headers=headers,
        )
        assert res_done.status_code == 200
        assert res_done.json()["state"] == "DONE"
        assert res_done.json()["assignee_id"] == str(trello_designer.id)

        board3 = client.get("/api/duplicate-board", headers=headers).json()
        assert len(board3["columns"][3]["cards"]) == 1
        assert board3["columns"][3]["cards"][0]["id"] == str(order.id)

        # 4. If order gets FIX from Printerval sync, it should jump back to Trello B's column
        db_session.refresh(order)
        order.state = "REVISION"
        order.note_outsource = "Cần sửa logo"
        db_session.commit()

        board4 = client.get("/api/duplicate-board", headers=headers).json()
        # Done column is now empty
        assert len(board4["columns"][3]["cards"]) == 0
        # Designer column has the order in FIX state!
        assert len(board4["columns"][2]["cards"]) == 1
        assert board4["columns"][2]["cards"][0]["state"] == "REVISION"
        assert board4["columns"][2]["cards"][0]["note_outsource"] == "Cần sửa logo"

    finally:
        del client.app.dependency_overrides[get_current_platform_id]


def test_admin_can_reorder_cards_within_the_same_designer_column(client, db_session):
    platform = _platform(db_session)
    _admin, headers = _login(client, db_session, "admin", "admin-reorder-designer", platform.id)
    designer = User(
        username="trello-reorder-designer",
        full_name="Trello Reorder",
        role="designer-trello",
        password_hash="hash",
        platform_id=platform.id,
    )
    first = Order(external_order_id="DUP-REORDER-1", platform_id=platform.id, work_domain="duplicate", state="IN_PROGRESS", duplicate_board_position=0)
    second = Order(external_order_id="DUP-REORDER-2", platform_id=platform.id, work_domain="duplicate", state="IN_PROGRESS", duplicate_board_position=1)
    third = Order(external_order_id="DUP-REORDER-3", platform_id=platform.id, work_domain="duplicate", state="IN_PROGRESS", duplicate_board_position=2)
    db_session.add_all([designer, first, second, third])
    db_session.flush()
    db_session.add_all([
        Assignment(order_id=first.id, designer_id=designer.id, status="approved"),
        Assignment(order_id=second.id, designer_id=designer.id, status="approved"),
        Assignment(order_id=third.id, designer_id=designer.id, status="approved"),
    ])
    db_session.commit()
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id

    try:
        response = client.post(
            "/api/duplicate-board/move",
            json={
                "order_id": str(third.id),
                "target_designer_id": str(designer.id),
                "before_order_id": str(first.id),
                "reorder": True,
            },
            headers=headers,
        )
        board = client.get("/api/duplicate-board", headers=headers)
    finally:
        del client.app.dependency_overrides[get_current_platform_id]

    assert response.status_code == 200
    assert board.status_code == 200
    designer_column = next(column for column in board.json()["columns"] if column["id"] == str(designer.id))
    assert [card["id"] for card in designer_column["cards"]] == [str(third.id), str(first.id), str(second.id)]


def test_trello_designer_can_claim_self_but_cannot_assign_another_user(client, db_session):
    platform = _platform(db_session)
    actor, headers = _login(client, db_session, "designer-trello", "trello-actor", platform.id)
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
    platform.duplicate_board_cross_designer_drag_enabled = False
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


def test_trello_designer_can_move_between_any_columns_when_admin_enables_cross_drag(client, db_session):
    platform = _platform(db_session)
    actor, headers = _login(client, db_session, "designer-trello", "trello-cross-actor", platform.id)
    actor.platform_id = platform.id
    other = User(
        username="trello-cross-other",
        full_name="Trello Cross Other",
        role="designer-trello",
        password_hash="hash",
        platform_id=platform.id,
    )
    order = Order(external_order_id="DUP-3", platform_id=platform.id, work_domain="duplicate")
    db_session.add_all([other, order])
    db_session.commit()
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id

    try:
        moved = client.post(
            "/api/duplicate-board/move",
            json={"order_id": str(order.id), "target_designer_id": str(other.id)},
            headers=headers,
        )
    finally:
        del client.app.dependency_overrides[get_current_platform_id]

    assert moved.status_code == 200
    assert moved.json()["assignee_id"] == str(other.id)


def test_admin_can_toggle_cross_designer_drag(client, db_session):
    platform = _platform(db_session)
    _, headers = _login(client, db_session, "admin", "duplicate-domain-settings-admin", platform.id)
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id

    try:
        response = client.put(
            "/api/duplicate-board/settings",
            json={"cross_designer_drag_enabled": False},
            headers=headers,
        )
    finally:
        del client.app.dependency_overrides[get_current_platform_id]

    assert response.status_code == 200
    assert response.json() == {"cross_designer_drag_enabled": False}
    db_session.refresh(platform)
    assert platform.duplicate_board_cross_designer_drag_enabled is False


def test_regular_designer_cannot_read_duplicate_board(client, db_session):
    platform = _platform(db_session)
    _, headers = _login(client, db_session, "designer", "regular-cannot-board", platform.id)
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id
    try:
        response = client.get("/api/duplicate-board", headers=headers)
    finally:
        del client.app.dependency_overrides[get_current_platform_id]
    assert response.status_code == 403


def test_regular_designer_cannot_see_duplicate_order_via_legacy_printerval_match(client, db_session):
    platform = _platform(db_session)
    designer, headers = _login(client, db_session, "designer", "regular-duplicate-hidden", platform.id)
    designer.platform_id = platform.id
    designer.full_name = "Regular External Name"
    order = Order(
        external_order_id="DUP-HIDDEN",
        platform_id=platform.id,
        work_domain="duplicate",
        printerval_designer="Regular External Name",
    )
    db_session.add(order)
    db_session.commit()
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id
    try:
        response = client.get("/api/orders", headers=headers)
    finally:
        del client.app.dependency_overrides[get_current_platform_id]

    assert response.status_code == 200
    assert response.json()["orders"] == []


def test_trello_designer_cannot_see_or_move_an_unreleased_fix(client, db_session):
    platform = _platform(db_session)
    designer, headers = _login(client, db_session, "designer-trello", "trello-unreleased-fix", platform.id)
    order = Order(
        external_order_id="DUP-UNRELEASED-FIX",
        platform_id=platform.id,
        work_domain="duplicate",
        state="REVISION",
        fix_approved_by_admin=False,
    )
    db_session.add(order)
    db_session.flush()
    db_session.add(Assignment(order_id=order.id, designer_id=designer.id, status="approved"))
    db_session.commit()
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id
    try:
        board = client.get("/api/duplicate-board", headers=headers)
        move = client.post(
            "/api/duplicate-board/move",
            json={"order_id": str(order.id), "target_column_id": "done"},
            headers=headers,
        )
    finally:
        del client.app.dependency_overrides[get_current_platform_id]

    assert board.status_code == 200
    assert all(
        card["id"] != str(order.id)
        for column in board.json()["columns"]
        for card in column["cards"]
    )
    assert move.status_code == 400
    db_session.refresh(order)
    assert order.state == "REVISION"


def test_support_can_set_duplicate_check_status_and_reversible(client, db_session, monkeypatch):
    platform = _platform(db_session)
    support, headers = _login(client, db_session, "support", "support-duplicate-check-user", platform.id)

    order = Order(
        external_order_id="ORD-CHK-1",
        platform_id=platform.id,
        work_domain="standard",
        duplicate_check_status="uncheck",
        state="WAITING",
    )
    db_session.add(order)
    db_session.commit()
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id
    delayed_requests: list[str] = []
    from app.workers import assignment_sync_tasks

    monkeypatch.setattr(
        assignment_sync_tasks.sync_printerval_assignment_request,
        "delay",
        lambda request_id: delayed_requests.append(request_id),
    )

    try:
        # 1. Support marks order as duplicate
        res1 = client.post(
            "/api/orders/duplicate-check-status",
            json={"order_ids": [str(order.id)], "status": "duplicate"},
            headers=headers,
        )
        assert res1.status_code == 200
        assert res1.json()["changed_count"] == 1
        db_session.refresh(order)
        assert order.work_domain == "duplicate"
        assert order.duplicate_check_status == "duplicate"
        assert order.state == "IN_PROGRESS"
        request = db_session.query(PrintervalAssignmentRequest).filter_by(order_id=order.id).one()
        assert request.target_status == "Doing"
        assert request.designer_option == ""
        assert request.internal_designer_id == support.id
        assert delayed_requests == [str(request.id)]
        board = client.get("/api/duplicate-board", headers=headers).json()
        assert any(card["id"] == str(order.id) and card["state"] == "IN_PROGRESS" for card in board["columns"][0]["cards"])
        assert board["columns"][0]["metrics"]["doing"] == 1

        # 2. Support marks order as non_duplicate (reversible flow)
        res2 = client.post(
            "/api/orders/duplicate-check-status",
            json={"order_ids": [str(order.id)], "status": "non_duplicate"},
            headers=headers,
        )
        assert res2.status_code == 200
        assert res2.json()["changed_count"] == 1
        db_session.refresh(order)
        assert order.work_domain == "standard"
        assert order.duplicate_check_status == "non_duplicate"
        assert order.state == "WAITING"

        # 3. Support resets order to uncheck
        res3 = client.post(
            "/api/orders/duplicate-check-status",
            json={"order_ids": [str(order.id)], "status": "uncheck"},
            headers=headers,
        )
        assert res3.status_code == 200
        db_session.refresh(order)
        assert order.duplicate_check_status == "uncheck"
        assert order.work_domain == "standard"

        # Entering the duplicate board again after a reversible move queues one
        # more source-status update.
        res4 = client.post(
            "/api/orders/duplicate-check-status",
            json={"order_ids": [str(order.id)], "status": "duplicate"},
            headers=headers,
        )
        assert res4.status_code == 200
        assert len(delayed_requests) == 2

        # Repeating the same duplicate action while it is already on the board
        # must not emit another external write.
        res5 = client.post(
            "/api/orders/duplicate-check-status",
            json={"order_ids": [str(order.id)], "status": "duplicate"},
            headers=headers,
        )
        assert res5.status_code == 200
        assert len(delayed_requests) == 2

    finally:
        del client.app.dependency_overrides[get_current_platform_id]


def test_admin_can_revoke_assignment(client, db_session):
    platform = _platform(db_session)
    admin, headers = _login(client, db_session, "admin", "admin-revoker", platform.id)
    designer = User(
        username="assigned-des-1",
        full_name="Assigned Des",
        role="designer",
        password_hash="hash",
        platform_id=platform.id,
    )
    order = Order(
        external_order_id="ORD-REVOKE-1",
        platform_id=platform.id,
        work_domain="standard",
        state="IN_PROGRESS",
        printerval_designer="Assigned Des",
    )
    db_session.add_all([designer, order])
    db_session.flush()
    assignment = Assignment(order_id=order.id, designer_id=designer.id, status="approved")
    db_session.add(assignment)
    db_session.commit()
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id

    try:
        # Admin revokes assignment
        res = client.post(
            "/api/assignments/revoke",
            json={"order_ids": [str(order.id)]},
            headers=headers,
        )
        assert res.status_code == 200
        assert res.json()["revoked_count"] == 1

        db_session.refresh(order)
        db_session.refresh(assignment)
        assert order.state == "WAITING"
        assert order.printerval_designer is None
        assert assignment.status == "cancelled"

        # Test single order endpoint as well
        order.state = "IN_PROGRESS"
        order.printerval_designer = "Assigned Des"
        assignment2 = Assignment(order_id=order.id, designer_id=designer.id, status="approved")
        db_session.add(assignment2)
        db_session.commit()

        res_single = client.post(
            f"/api/orders/{order.id}/revoke-assignment",
            headers=headers,
        )
        assert res_single.status_code == 200
        db_session.refresh(order)
        assert order.state == "WAITING"
        assert order.printerval_designer is None

    finally:
        del client.app.dependency_overrides[get_current_platform_id]


def test_move_card_to_designer_enqueues_printerval_doing_sync(client, db_session, monkeypatch):
    platform = _platform(db_session)
    admin, headers = _login(client, db_session, "admin", "admin-sync-tester", platform.id)
    trello_designer = User(
        username="trello-des-sync",
        full_name="Trello Des Sync",
        role="designer-trello",
        password_hash="hash",
        platform_id=platform.id,
        printerval_designer_option="nguyễn thị thúy hường 2d prin",
    )
    order = Order(
        external_order_id="DUP-SYNC-1",
        platform_id=platform.id,
        work_domain="duplicate",
        state="WAITING",
    )
    db_session.add_all([trello_designer, order])
    db_session.commit()
    client.app.dependency_overrides[get_current_platform_id] = lambda: platform.id

    delayed_requests: list[str] = []
    from app.workers import assignment_sync_tasks

    monkeypatch.setattr(
        assignment_sync_tasks.sync_printerval_assignment_request,
        "delay",
        lambda req_id: delayed_requests.append(req_id),
    )

    try:
        # Move order from orders column to trello designer column
        res = client.post(
            "/api/duplicate-board/move",
            json={"order_id": str(order.id), "target_designer_id": str(trello_designer.id)},
            headers=headers,
        )
        assert res.status_code == 200
        assert res.json()["state"] == "IN_PROGRESS"
        assert res.json()["assignee_id"] == str(trello_designer.id)

        # Database state should be IN_PROGRESS (Doing)
        db_session.refresh(order)
        assert order.state == "IN_PROGRESS"

        # PrintervalAssignmentRequest should have been created with Doing status
        req = (
            db_session.query(PrintervalAssignmentRequest)
            .filter(PrintervalAssignmentRequest.order_id == order.id)
            .first()
        )
        assert req is not None
        assert req.target_status == "Doing"
        assert req.designer_option == "nguyễn thị thúy hường 2d prin"
        assert req.internal_designer_id == trello_designer.id

        # Celery task should have been triggered
        assert len(delayed_requests) == 1
        assert delayed_requests[0] == str(req.id)
    finally:
        del client.app.dependency_overrides[get_current_platform_id]

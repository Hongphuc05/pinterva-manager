import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import ApprovalRequest, Assignment, Batch, Order, User
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
    client.post("/api/login", json={"username": username, "password": "s3cret!"})
    return user


def _seed_open_batch(db_session, n=3, prefix="DJ"):
    batch = Batch(source="printerval_crawl", owner="ntth", count=n)
    db_session.add(batch)
    db_session.flush()
    for i in range(n):
        db_session.add(
            Order(
                external_order_id=f"{prefix}{i:07d}", batch_id=batch.id,
                state=OrderState.OPEN_FOR_ALLOCATION.value,
            )
        )
    db_session.commit()
    return batch


def test_offer_requires_designer_role(client, db_session):
    _login(client, db_session, "admin")
    batch = _seed_open_batch(db_session)
    resp = client.post(
        "/api/allocation/offer",
        json={"batch_id": str(batch.id), "quantity": 1, "request_id": "r1"},
    )
    assert resp.status_code == 403


def test_offer_grants_orders_to_a_designer(client, db_session):
    _login(client, db_session, "designer")
    batch = _seed_open_batch(db_session)
    resp = client.post(
        "/api/allocation/offer",
        json={"batch_id": str(batch.id), "quantity": 2, "request_id": "r1"},
    )
    assert resp.status_code == 200
    assert resp.json()["granted_order_ids"] == ["DJ0000000", "DJ0000001"]


def test_offer_rejects_non_positive_quantity(client, db_session):
    _login(client, db_session, "designer")
    batch = _seed_open_batch(db_session)
    resp = client.post(
        "/api/allocation/offer",
        json={"batch_id": str(batch.id), "quantity": -1, "request_id": "r1"},
    )
    assert resp.status_code == 422


def test_offer_double_submit_with_same_request_id_grants_only_once(client, db_session):
    """C2: retrying the exact same click (same request_id) must be a true no-op,
    not a second grant."""
    _login(client, db_session, "designer")
    batch = _seed_open_batch(db_session)
    payload = {"batch_id": str(batch.id), "quantity": 3, "request_id": "same-click"}

    resp1 = client.post("/api/allocation/offer", json=payload)
    resp2 = client.post("/api/allocation/offer", json=payload)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json() == resp2.json()
    assert db_session.query(Assignment).count() == 3  # not 6


def test_assign_requires_admin_role(client, db_session):
    _login(client, db_session, "designer")
    batch = _seed_open_batch(db_session)
    order = db_session.query(Order).filter_by(batch_id=batch.id).first()
    resp = client.post(
        "/api/allocation/assign",
        json={
            "order_id": order.external_order_id,
            "designer_id": str(order.id),
            "request_id": "r1",
        },
    )
    assert resp.status_code == 403


def test_board_lists_unassigned_orders_and_designers(client, db_session):
    _login(client, db_session, "admin")
    batch = _seed_open_batch(db_session)

    resp = client.get("/api/allocation/board", params={"batch_id": str(batch.id)})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["unassigned"]) == 3
    assert body["designers"] == []  # no designer users seeded in this test


def test_board_get_does_not_block_a_concurrent_writer(client, db_session, engine):
    """I2: the board is a read-only view — it must not hold FOR UPDATE on every
    unassigned order, or a board left open blocks every offer/assign forever."""
    from sqlalchemy import text

    _login(client, db_session, "admin")
    batch = _seed_open_batch(db_session, n=2)

    resp = client.get("/api/allocation/board", params={"batch_id": str(batch.id)})
    assert resp.status_code == 200

    # The client's db_session is still holding whatever transaction the request
    # left open; a second, independent connection must be able to lock the same
    # rows without waiting.
    with engine.connect() as conn, conn.begin():
        conn.execute(text("SET LOCAL lock_timeout = '2s'"))
        locked = conn.execute(
            text("SELECT id FROM orders WHERE batch_id = :b FOR UPDATE"),
            {"b": str(batch.id)},
        ).fetchall()
    assert len(locked) == 2


def test_pending_approvals_are_scoped_to_the_requested_batch(client, db_session):
    """I6: a draft assignment from another batch must not leak onto this board."""
    from app.adapters.allocation.reference import ReferenceAllocationTool
    from app.application.allocation import request_quantity

    _login(client, db_session, "admin")
    batch_a = _seed_open_batch(db_session, n=1, prefix="AA")
    batch_b = _seed_open_batch(db_session, n=1, prefix="BB")
    designer = User(
        username="d1", full_name="D1", role="designer", password_hash=hash_password("s3cret!")
    )
    db_session.add(designer)
    db_session.commit()

    tool = ReferenceAllocationTool()
    request_quantity(db_session, tool, designer.id, batch_a.id, 1, "req-a")
    request_quantity(db_session, tool, designer.id, batch_b.id, 1, "req-b")

    resp = client.get("/api/allocation/board", params={"batch_id": str(batch_a.id)})

    assert resp.status_code == 200
    designers = resp.json()["designers"]
    assert len(designers) == 1
    assert len(designers[0]["pending_approvals"]) == 1  # only batch_a's draft, not batch_b's


def test_decide_second_admin_sees_it_was_already_decided(client, db_session):
    _login(client, db_session, "admin", username="admin1")
    batch = _seed_open_batch(db_session)
    designer = User(
        username="d1", full_name="D1", role="designer", password_hash=hash_password("s3cret!")
    )
    db_session.add(designer)
    db_session.commit()

    from app.adapters.allocation.reference import ReferenceAllocationTool
    from app.application.allocation import request_quantity

    request_quantity(db_session, ReferenceAllocationTool(), designer.id, batch.id, 1, "seed-req")
    order = db_session.query(Order).filter_by(external_order_id="DJ0000000").one()
    assignment = db_session.query(Assignment).filter_by(order_id=order.id).one()
    approval = db_session.query(ApprovalRequest).filter_by(target_id=assignment.id).one()

    resp1 = client.post(f"/api/approvals/{approval.id}/decide", json={"decision": "approve"})
    assert resp1.json()["decided_by_me"] is True
    assert resp1.json()["decided_by_name"] == "admin1"
    assert resp1.json()["decided_at"]

    # switches `client`'s own session to a 2nd admin
    _login(client, db_session, "admin", username="admin2")
    resp2 = client.post(
        f"/api/approvals/{approval.id}/decide", json={"decision": "cancel", "reason": "x"}
    )
    assert resp2.status_code == 200
    assert resp2.json()["decided_by_me"] is False
    assert resp2.json()["decision"] == "approve"  # admin1's original decision, unchanged
    # I5: the "already decided" info must name who decided and when.
    assert resp2.json()["decided_by_name"] == "admin1"
    assert resp2.json()["decided_at"]


def test_decide_returns_409_when_another_admin_is_genuinely_mid_decision(client, db_session):
    """I4: the truly-concurrent case (a `pending`, unexpired Operation row already
    exists for this approval) must surface as 409, not an unhandled 500."""
    from app.adapters.db.models import Operation

    _login(client, db_session, "admin")
    batch = _seed_open_batch(db_session)
    designer = User(
        username="d1", full_name="D1", role="designer", password_hash=hash_password("s3cret!")
    )
    db_session.add(designer)
    db_session.commit()

    from app.adapters.allocation.reference import ReferenceAllocationTool
    from app.application.allocation import request_quantity

    request_quantity(db_session, ReferenceAllocationTool(), designer.id, batch.id, 1, "seed-req")
    order = db_session.query(Order).filter_by(external_order_id="DJ0000000").one()
    assignment = db_session.query(Assignment).filter_by(order_id=order.id).one()
    approval = db_session.query(ApprovalRequest).filter_by(target_id=assignment.id).one()

    # Simulate another request already in flight on this exact approval.
    db_session.add(
        Operation(
            idempotency_key=f"decide_assignment:{approval.id}",
            command_name="decide_assignment",
            status="pending",
        )
    )
    db_session.commit()

    resp = client.post(f"/api/approvals/{approval.id}/decide", json={"decision": "approve"})

    assert resp.status_code == 409

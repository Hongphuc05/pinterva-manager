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


def _seed_open_batch(db_session, n=3):
    batch = Batch(source="printerval_crawl", owner="ntth", count=n)
    db_session.add(batch)
    db_session.flush()
    for i in range(n):
        db_session.add(
            Order(
                external_order_id=f"DJ{i:07d}", batch_id=batch.id,
                state=OrderState.OPEN_FOR_ALLOCATION.value,
            )
        )
    db_session.commit()
    return batch


def test_offer_requires_designer_role(client, db_session):
    _login(client, db_session, "admin")
    batch = _seed_open_batch(db_session)
    resp = client.post("/api/allocation/offer", json={"batch_id": str(batch.id), "quantity": 1})
    assert resp.status_code == 403


def test_offer_grants_orders_to_a_designer(client, db_session):
    _login(client, db_session, "designer")
    batch = _seed_open_batch(db_session)
    resp = client.post("/api/allocation/offer", json={"batch_id": str(batch.id), "quantity": 2})
    assert resp.status_code == 200
    assert resp.json()["granted_order_ids"] == ["DJ0000000", "DJ0000001"]


def test_assign_requires_admin_role(client, db_session):
    _login(client, db_session, "designer")
    batch = _seed_open_batch(db_session)
    order = db_session.query(Order).filter_by(batch_id=batch.id).first()
    resp = client.post(
        "/api/allocation/assign",
        json={"order_id": order.external_order_id, "designer_id": str(order.id)},
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

    # switches `client`'s own session to a 2nd admin
    _login(client, db_session, "admin", username="admin2")
    resp2 = client.post(
        f"/api/approvals/{approval.id}/decide", json={"decision": "cancel", "reason": "x"}
    )
    assert resp2.status_code == 200
    assert resp2.json()["decided_by_me"] is False
    assert resp2.json()["decision"] == "approve"  # admin1's original decision, unchanged

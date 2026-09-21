from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import Assignment, Batch, Order, User
from app.adapters.google.fake_drive_adapter import FakeDriveAdapter
from app.api.deps import get_db
from app.api.main import create_app
from app.api.routes.designer_tasks_api import get_drive_adapter
from app.application.auth import hash_password
from app.domain.models import OrderState


@pytest.fixture()
def client(db_session):
    app = create_app()

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_drive_adapter] = lambda: FakeDriveAdapter({"known-file"})
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, db_session, role: str, username: str):
    user = User(
        username=username, full_name=username, role=role,
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(user)
    db_session.commit()
    client.post("/api/login", json={"username": username, "password": "s3cret!"})
    return user


def _seed_owned_task(db_session, designer, state=OrderState.IN_PROGRESS.value):
    batch = Batch(source="printerval_crawl", owner="ntth", count=1)
    db_session.add(batch)
    db_session.flush()
    order = Order(
        external_order_id=f"HTTP-{uuid.uuid4()}", batch_id=batch.id, state=state,
    )
    db_session.add(order)
    db_session.flush()
    assignment = Assignment(order_id=order.id, designer_id=designer.id, status="approved")
    db_session.add(assignment)
    db_session.commit()
    return assignment, order


def test_my_tasks_requires_designer_and_scopes_to_current_designer(client, db_session):
    _login(client, db_session, "admin", "admin")
    assert client.get("/api/my-tasks").status_code == 403

    designer = _login(client, db_session, "designer", "designer")
    assignment, order = _seed_owned_task(db_session, designer)

    response = client.get("/api/my-tasks")

    assert response.status_code == 200
    task = response.json()["tasks"][0]
    assert task["assignment_id"] == str(assignment.id)
    assert task["order"]["external_order_id"] == order.external_order_id


def test_my_tasks_accepts_trello_designer(client, db_session):
    trello_designer = _login(client, db_session, "designer-trello", "trello-tasks")
    assignment, order = _seed_owned_task(db_session, trello_designer)
    order.work_domain = "duplicate"
    db_session.commit()

    response = client.get("/api/my-tasks")

    assert response.status_code == 200
    assert response.json()["tasks"][0]["assignment_id"] == str(assignment.id)


def test_unapproved_fix_is_hidden_and_cannot_be_submitted_by_designer(client, db_session):
    designer = _login(client, db_session, "designer", "unapproved-fix-designer")
    assignment, order = _seed_owned_task(db_session, designer, OrderState.REVISION.value)
    order.fix_approved_by_admin = False
    db_session.commit()

    assert client.get("/api/my-tasks").json()["tasks"] == []
    response = client.post(
        f"/api/assignments/{assignment.id}/results",
        json={
            "drive_url": "https://drive.google.com/file/d/known-file/view",
            "request_id": "unapproved-fix-submit",
        },
    )
    assert response.status_code == 404


def test_trello_designer_can_submit_result_for_owned_duplicate_order(client, db_session, monkeypatch):
    trello_designer = _login(client, db_session, "designer-trello", "trello-submitter")
    assignment, order = _seed_owned_task(db_session, trello_designer, OrderState.IN_PROGRESS.value)
    order.work_domain = "duplicate"
    db_session.commit()
    from app.workers import assignment_sync_tasks

    monkeypatch.setattr(assignment_sync_tasks.sync_order_review_to_printerval_task, "delay", lambda *_args, **_kwargs: None)

    response = client.post(
        f"/api/assignments/{assignment.id}/results",
        json={
            "drive_url": "https://drive.google.com/file/d/known-file/view",
            "request_id": "trello-submit-1",
        },
    )

    assert response.status_code == 200
    assert response.json()["state"] == OrderState.QC_PENDING.value


def test_regular_designer_submission_ignores_stale_parent_order_version(client, db_session, monkeypatch):
    """A background/Admin order update must not block the normal Designer's work."""
    designer = _login(client, db_session, "designer", "regular-stale-version")
    assignment, order = _seed_owned_task(db_session, designer)
    stale_version = order.version
    order.designer_note = "Admin cập nhật hướng dẫn trong khi Designer đang làm"
    db_session.commit()
    assert order.version != stale_version

    from app.workers import assignment_sync_tasks

    monkeypatch.setattr(assignment_sync_tasks.sync_order_review_to_printerval_task, "delay", lambda *_args, **_kwargs: None)
    response = client.post(
        f"/api/assignments/{assignment.id}/results",
        json={
            "drive_url": "https://drive.google.com/file/d/known-file/view",
            "request_id": "regular-stale-submit",
            "expected_version": stale_version,
        },
    )

    assert response.status_code == 200
    assert response.json()["state"] == OrderState.QC_PENDING.value


def test_trello_designer_submission_keeps_optimistic_version_check(client, db_session):
    trello_designer = _login(client, db_session, "designer-trello", "trello-stale-version")
    assignment, order = _seed_owned_task(db_session, trello_designer)
    order.work_domain = "duplicate"
    db_session.commit()

    response = client.post(
        f"/api/assignments/{assignment.id}/results",
        json={
            "drive_url": "https://drive.google.com/file/d/known-file/view",
            "request_id": "trello-stale-submit",
            "expected_version": order.version + 1,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ORDER_VERSION_CONFLICT"


def test_result_api_verifies_drive_enters_qc_queue_and_queues_printerval_review(client, db_session, monkeypatch):
    designer = _login(client, db_session, "designer", "submitter")
    assignment, order = _seed_owned_task(db_session, designer, OrderState.IN_PROGRESS.value)
    queued: list[tuple] = []
    from app.workers import assignment_sync_tasks

    monkeypatch.setattr(
        assignment_sync_tasks.sync_order_review_to_printerval_task,
        "delay",
        lambda *args, **kwargs: queued.append((args, kwargs)),
    )
    payload = {
        "drive_url": "https://drive.google.com/file/d/known-file/view",
        "request_id": "submit-1",
    }

    first = client.post(f"/api/assignments/{assignment.id}/results", json=payload)
    replay = client.post(f"/api/assignments/{assignment.id}/results", json=payload)

    assert first.status_code == 200
    assert first.json()["state"] == OrderState.QC_PENDING.value
    assert replay.status_code == 200
    assert replay.json() == first.json()
    # Replaying the same submission safely queues the idempotent external
    # status write again, which also lets a client retry a transient broker loss.
    assert queued == [
        ((str(order.id), "https://drive.google.com/file/d/known-file/view", "Review"), {
            "expected_state": OrderState.QC_PENDING.value,
            "expected_fix_approved": False,
        }),
        ((str(order.id), "https://drive.google.com/file/d/known-file/view", "Review"), {
            "expected_state": OrderState.QC_PENDING.value,
            "expected_fix_approved": False,
        }),
    ]


def test_fix_resubmission_queues_printerval_review_sync(client, db_session, monkeypatch):
    designer = _login(client, db_session, "designer", "fix-resubmitter")
    assignment, order = _seed_owned_task(db_session, designer, OrderState.REVISION.value)
    order.fix_approved_by_admin = True
    db_session.commit()
    queued: list[tuple] = []
    from app.workers import assignment_sync_tasks

    monkeypatch.setattr(
        assignment_sync_tasks.sync_order_review_to_printerval_task,
        "delay",
        lambda *args, **kwargs: queued.append((args, kwargs)),
    )

    response = client.post(
        f"/api/assignments/{assignment.id}/results",
        json={
            "drive_url": "https://drive.google.com/file/d/known-file/view",
            "request_id": "fix-resubmit-1",
        },
    )

    assert response.status_code == 200
    assert response.json()["state"] == OrderState.QC_PENDING.value
    assert queued == [
        ((str(order.id), None, "Review"), {
            "expected_state": OrderState.QC_PENDING.value,
            "expected_fix_approved": True,
        })
    ]


def test_paid_fix_resubmission_returns_done_and_syncs_printerval_review(client, db_session, monkeypatch):
    designer = _login(client, db_session, "designer", "paid-fix-resubmitter")
    assignment, order = _seed_owned_task(db_session, designer, OrderState.REVISION.value)
    order.is_paid = True
    order.fix_approved_by_admin = True
    order.fix_return_count = 1
    db_session.commit()
    queued: list[tuple] = []
    from app.workers import assignment_sync_tasks

    monkeypatch.setattr(
        assignment_sync_tasks.sync_order_review_to_printerval_task,
        "delay",
        lambda *args, **kwargs: queued.append((args, kwargs)),
    )

    response = client.post(
        f"/api/assignments/{assignment.id}/results",
        json={
            "drive_url": "https://drive.google.com/file/d/known-file/view",
            "request_id": "paid-fix-resubmit-1",
        },
    )

    assert response.status_code == 200
    assert response.json()["state"] == OrderState.DONE.value
    assert queued == [
        ((str(order.id), None, "Review"), {
            "expected_state": OrderState.DONE.value,
            "expected_fix_approved": True,
        })
    ]


def test_my_tasks_suppresses_note_outsource_when_flagged(client, db_session):
    designer = _login(client, db_session, "designer", "suppressed-note-designer")
    assignment, order = _seed_owned_task(db_session, designer)
    order.note_outsource = "Secret Printerval outsource note"
    order.designer_note = "Admin added template: https://example.com/template"
    order.suppress_note_outsource_for_designer = True
    db_session.commit()

    response = client.get("/api/my-tasks")
    assert response.status_code == 200
    task_order = response.json()["tasks"][0]["order"]
    assert task_order["note_outsource"] == ""
    assert task_order["designer_note"] == "Admin added template: https://example.com/template"

from __future__ import annotations

import uuid

import pytest

from app.adapters.db.models import ApprovalRequest, Assignment, Batch, Order, ResultVersion, User
from app.adapters.google.fake_drive_adapter import FakeDriveAdapter
from app.application.auth import hash_password
from app.application.designer_tasks import (
    DriveValidationError,
    TaskNotFoundError,
    list_my_tasks,
    start_task,
    submit_result,
    update_sub_status,
)
from app.domain.models import OrderState


def _seed_task(db_session, *, state=OrderState.ASSIGNED.value):
    batch = Batch(source="printerval_crawl", owner="ntth", count=1)
    designer = User(
        username=f"designer-{uuid.uuid4()}", full_name="Designer", role="designer",
        password_hash=hash_password("s3cret!"),
    )
    db_session.add_all([batch, designer])
    db_session.flush()
    order = Order(
        external_order_id=f"TASK-{uuid.uuid4()}", batch_id=batch.id, state=state,
        product_name="A product", order_note="Make it blue",
    )
    db_session.add(order)
    db_session.flush()
    assignment = Assignment(order_id=order.id, designer_id=designer.id, status="approved")
    db_session.add(assignment)
    db_session.commit()
    return designer, assignment, order


def test_list_my_tasks_only_returns_active_tasks_owned_by_designer(db_session):
    designer, assignment, order = _seed_task(db_session)
    other, _, _ = _seed_task(db_session)
    cancelled = Assignment(order_id=order.id, designer_id=other.id, status="cancelled")
    db_session.add(cancelled)
    db_session.commit()

    tasks = list_my_tasks(db_session, designer.id)

    assert [task["assignment_id"] for task in tasks] == [str(assignment.id)]
    assert tasks[0]["order"]["external_order_id"] == order.external_order_id


def test_start_task_transitions_state_and_keeps_sub_status_display_separate(db_session):
    designer, assignment, order = _seed_task(db_session)

    result = start_task(db_session, assignment.id, designer.id, "start:1", str(assignment.id))

    assert result["state"] == OrderState.IN_PROGRESS.value
    db_session.refresh(order)
    db_session.refresh(assignment)
    assert order.state == OrderState.IN_PROGRESS.value
    assert assignment.sub_status == "doing"

    update_sub_status(
        db_session, assignment.id, designer.id, "fixing", "sub-status:1", f"{assignment.id}:fixing"
    )
    db_session.refresh(order)
    db_session.refresh(assignment)
    assert order.state == OrderState.IN_PROGRESS.value
    assert assignment.sub_status == "fixing"


def test_submit_result_verifies_drive_creates_version_and_qc_request_idempotently(db_session):
    designer, assignment, order = _seed_task(db_session, state=OrderState.IN_PROGRESS.value)
    drive = FakeDriveAdapter({"known-file"})
    url = "https://drive.google.com/file/d/known-file/view"

    first = submit_result(
        db_session, drive, assignment.id, designer.id, url, "submit:1", f"{assignment.id}:{url}"
    )
    replay = submit_result(
        db_session, drive, assignment.id, designer.id, url, "submit:1", f"{assignment.id}:{url}"
    )

    assert replay == first
    assert first["version_marker"] == 1
    db_session.refresh(order)
    db_session.refresh(assignment)
    assert order.state == OrderState.QC_PENDING.value
    assert assignment.sub_status == "done"
    version = db_session.query(ResultVersion).filter_by(assignment_id=assignment.id).one()
    assert version.validated is True
    qc_request = db_session.query(ApprovalRequest).filter_by(target_version_id=version.id).one()
    assert qc_request.kind == "qc"
    assert qc_request.target_id == order.id


def test_submit_result_rejects_unverified_drive_without_state_change(db_session):
    designer, assignment, order = _seed_task(db_session, state=OrderState.IN_PROGRESS.value)

    with pytest.raises(DriveValidationError):
        submit_result(
            db_session, FakeDriveAdapter(set()), assignment.id, designer.id,
            "https://drive.google.com/file/d/missing/view", "submit:missing", "missing",
        )

    db_session.refresh(order)
    assert order.state == OrderState.IN_PROGRESS.value
    assert db_session.query(ResultVersion).count() == 0


def test_designer_cannot_mutate_another_designers_task(db_session):
    designer, assignment, _ = _seed_task(db_session)
    other = User(
        username=f"other-{uuid.uuid4()}", full_name="Other", role="designer",
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(other)
    db_session.commit()

    with pytest.raises(TaskNotFoundError):
        start_task(db_session, assignment.id, other.id, "start:other", str(assignment.id))

    assert list_my_tasks(db_session, other.id) == []

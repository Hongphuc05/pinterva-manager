"""Support puts a classified order back into Chưa kiểm tra (only while no designer has it)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.adapters.db.models import (
    Assignment,
    Order,
    Platform,
    PrintervalAssignmentRequest,
    SupportCompareItem,
    SupportCompareRun,
    TelegramActionLog,
    User,
    WorkflowEvent,
)
from app.application.auth import create_session_token, hash_password
from app.application.support_compare import (
    count_support_unchecked_orders,
    create_support_compare_job,
)


@pytest.fixture()
def ctx(db_session, monkeypatch):
    monkeypatch.setattr("app.application.duplicate_board._dispatch_printerval_requests", lambda ids: None)
    monkeypatch.setattr("app.application.support_return._dispatch_printerval_requests", lambda ids: None)
    platform = Platform(name="Plat return", account_username="ret@print.com", is_active=True)
    db_session.add(platform)
    db_session.flush()
    support = User(username="sup-ret", full_name="Sup", role="support", password_hash=hash_password("p"), active=True, platform_id=platform.id)
    designer = User(username="des-ret", full_name="Des", role="designer", password_hash=hash_password("p"), active=True, platform_id=platform.id)
    run = SupportCompareRun(
        id=uuid.uuid4(), source_kind="support_unchecked", platform_id=platform.id, model_version="m",
        embedding_dim=3, classifier_version="c", started_at=datetime.now(UTC),
    )
    db_session.add_all([support, designer, run])
    db_session.commit()
    return SimpleNamespace(platform=platform, support=support, designer=designer, run=run)


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_session_token(str(user.id), user.role)}"}


def _order(db_session, ctx, code: str, *, check: str, domain: str = "standard", state: str = "WAITING", printerval: str | None = None) -> Order:
    order = Order(
        external_order_id=code, platform_id=ctx.platform.id, state=state, duplicate_check_status=check,
        work_domain=domain, printerval_status=printerval, thumbnail_url=f"https://example.test/{code}.png",
        support_classified_by_id=ctx.support.id if check == "duplicate" else None,
        support_classified_at=datetime.now(UTC) if check == "duplicate" else None,
        duplicate_board_position=3 if domain == "duplicate" else None,
    )
    db_session.add(order)
    db_session.commit()
    return order


def _compared(db_session, ctx, order: Order, review_status: str = "no_match") -> SupportCompareItem:
    now = datetime.now(UTC)
    item = SupportCompareItem(
        id=uuid.uuid4(), run_id=ctx.run.id, platform_id=ctx.platform.id, order_id=order.id,
        external_order_id=order.external_order_id, image_url="https://example.test/x.png",
        image_url_sha256=uuid.uuid4().hex + uuid.uuid4().hex, model_version="m", processing_status="completed",
        review_status=review_status, created_at=now, updated_at=now,
    )
    db_session.add(item)
    db_session.commit()
    return item


def _return(client, user: User, *orders: Order, versions: bool = False):
    body = {"order_ids": [str(o.id) for o in orders]}
    if versions:
        body["expected_versions"] = {str(o.id): o.version for o in orders}
    return client.post("/api/orders/return-to-unchecked", json=body, headers=_headers(user))


def test_a_non_duplicate_order_goes_back_to_unchecked_and_can_be_checked_again(client, db_session, ctx):
    order = _order(db_session, ctx, "DJ-ND", check="non_duplicate")
    item = _compared(db_session, ctx, order)
    action = TelegramActionLog(order_id=order.id, action_type="SUPPORT_COMPARE_CONFIRM_DUPLICATE", callback_token="tok1", status="pending")
    db_session.add(action)
    db_session.commit()
    assert count_support_unchecked_orders(db_session, platform_id=ctx.platform.id) == 0  # compared before

    res = _return(client, ctx.support, order, versions=True)

    assert res.status_code == 200 and res.json() == {"changed_count": 1}
    db_session.expire_all()
    assert order.duplicate_check_status == "uncheck" and order.state == "WAITING"
    assert (item.processing_status, item.review_status) == ("skipped", None)  # the old result is retired
    assert action.status == "superseded"  # a late Telegram press can no longer re-tag it
    # It is a normal unchecked order again: /check counts it and queues it in a new job.
    assert count_support_unchecked_orders(db_session, platform_id=ctx.platform.id) == 1
    job = create_support_compare_job(db_session, platform_id=ctx.platform.id, requested_by_id=ctx.support.id, chat_id="1")
    assert job is not None and job.order_ids == [str(order.id)]
    event = db_session.query(WorkflowEvent).filter(WorkflowEvent.order_id == order.id).one()
    assert event.evidence["action"] == "returned_to_unchecked" and event.actor_id == ctx.support.id


def test_a_duplicate_order_leaves_the_board_and_printerval_goes_back_to_waiting(client, db_session, ctx):
    order = _order(db_session, ctx, "DJ-DUP", check="duplicate", domain="duplicate", state="IN_PROGRESS", printerval="doing")
    _compared(db_session, ctx, order, "selected_duplicate")

    res = _return(client, ctx.support, order)

    assert res.status_code == 200
    db_session.expire_all()
    assert (order.duplicate_check_status, order.work_domain, order.state) == ("uncheck", "standard", "WAITING")
    assert order.duplicate_board_position is None
    assert order.support_classified_by_id is None and order.support_classified_at is None  # no longer counted as Support work
    request = db_session.query(PrintervalAssignmentRequest).filter(PrintervalAssignmentRequest.order_id == order.id).one()
    assert request.target_status == "Waiting"
    assert count_support_unchecked_orders(db_session, platform_id=ctx.platform.id) == 1


def test_an_order_a_designer_took_cannot_be_returned(client, db_session, ctx):
    order = _order(db_session, ctx, "DJ-TAKEN", check="duplicate", domain="duplicate", state="IN_PROGRESS")
    db_session.add(Assignment(order_id=order.id, designer_id=ctx.designer.id, status="approved"))
    db_session.commit()

    res = _return(client, ctx.support, order)

    assert res.status_code == 400 and "đã có designer đảm nhận" in res.json()["detail"]
    db_session.expire_all()
    assert order.duplicate_check_status == "duplicate" and order.work_domain == "duplicate"


@pytest.mark.parametrize("state", ["QC_PENDING", "DONE"])
def test_an_order_that_moved_on_cannot_be_returned(client, db_session, ctx, state):
    order = _order(db_session, ctx, f"DJ-{state}", check="duplicate", domain="duplicate", state=state)
    assert _return(client, ctx.support, order).status_code == 400


def test_an_unchecked_order_is_refused(client, db_session, ctx):
    order = _order(db_session, ctx, "DJ-UNC", check="uncheck")
    res = _return(client, ctx.support, order)
    assert res.status_code == 400 and "Chưa xử lý" in res.json()["detail"]


def test_one_refused_order_changes_nothing(client, db_session, ctx):
    fine = _order(db_session, ctx, "DJ-FINE", check="non_duplicate")
    taken = _order(db_session, ctx, "DJ-TAKEN2", check="duplicate", domain="duplicate", state="IN_PROGRESS")
    db_session.add(Assignment(order_id=taken.id, designer_id=ctx.designer.id, status="approved"))
    db_session.commit()
    assert _return(client, ctx.support, fine, taken).status_code == 400
    db_session.expire_all()
    assert fine.duplicate_check_status == "non_duplicate"


def test_only_support_or_admin_of_the_platform_can_return_orders(client, db_session, ctx):
    order = _order(db_session, ctx, "DJ-AUTH", check="non_duplicate")
    assert client.post("/api/orders/return-to-unchecked", json={"order_ids": [str(order.id)]}).status_code == 401
    assert _return(client, ctx.designer, order).status_code == 403
    other = Platform(name="Other", account_username="o@print.com", is_active=True)
    db_session.add(other)
    db_session.flush()
    outsider = User(username="sup-out", full_name="O", role="support", password_hash=hash_password("p"), active=True, platform_id=other.id)
    db_session.add(outsider)
    db_session.commit()
    assert _return(client, outsider, order).status_code == 400  # not in that platform


def test_a_stale_order_revision_is_refused(client, db_session, ctx):
    order = _order(db_session, ctx, "DJ-STALE", check="non_duplicate")
    body = {"order_ids": [str(order.id)], "expected_versions": {str(order.id): order.version + 5}}
    assert client.post("/api/orders/return-to-unchecked", json=body, headers=_headers(ctx.support)).status_code == 409

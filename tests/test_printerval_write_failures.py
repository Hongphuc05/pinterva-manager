"""A write to Printerval that fails must be retried when it may succeed later, and otherwise end in
a DeadLetter shown to Admin as a web toast with what to do by hand (no Telegram) (incident 2026-10-14: a slow
Printerval made the Review push of DJ4141056 fail silently)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import httpx
import pytest

from app.adapters.db.models import DeadLetter, Order, Platform, PrintervalAssignmentRequest, User
from app.adapters.errors import ErrorClass
from app.adapters.printerval.api_client import PrintervalApiClient, PrintervalApiError
from app.domain.models import OrderState
from app.workers import assignment_sync_tasks as tasks

REVIEW = tasks.sync_order_review_to_printerval_task


class _KeepOpen:
    """The task closes its session; the test still needs it."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


class FakeClient:
    def __init__(self, *, login_error=None, status_ok=True, row=None, refusal="", refusal_body=None):
        self.last_status_error = refusal
        self.last_status_refusal = refusal_body or {}
        self.extras: list = []
        self.login_error = login_error
        self.status_ok = status_ok
        self.row = row
        self.find_calls: list[tuple] = []
        self.status_calls: list[tuple] = []

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def login(self):
        if self.login_error:
            raise self.login_error

    def find_order(self, code, statuses=()):
        self.find_calls.append((code, statuses))
        return self.row

    def update_order_note_outsource(self, row_id, note):
        return True

    def fetch_chat_messages(self, job_id, after_id=0):
        return {"messages": [], "chat": {}}

    def update_order_status(self, row_id, status, locale, extra=None):
        self.status_calls.append((row_id, status, locale))
        self.extras.append(extra)
        return self.status_ok


@pytest.fixture()
def world(db_session, monkeypatch):
    platform = Platform(name="P write", account_username="w@print.com", session_cookie="laravel_session=x",
                        team_outsource="team", is_active=True)
    db_session.add(platform)
    db_session.flush()
    admin = User(username=f"adm-{uuid.uuid4().hex[:5]}", full_name="Admin", role="admin", password_hash="x",
                 active=True, platform_id=platform.id, telegram_chat_id="5550001")
    order = Order(external_order_id="DJ4141056", platform_id=platform.id, state=OrderState.QC_PENDING.value,
                  printerval_status="doing", duplicate_check_status="uncheck", work_domain="standard")
    db_session.add_all([admin, order])
    db_session.commit()
    monkeypatch.setattr(tasks, "SessionLocal", lambda: _KeepOpen(db_session))
    return type("W", (), {"platform": platform, "order": order, "session": db_session})


def _run(order, retries: int = 0):
    REVIEW.push_request(retries=retries)
    try:
        return REVIEW.run(str(order.id), None, "Review", expected_state=OrderState.QC_PENDING.value)
    finally:
        REVIEW.pop_request()


def test_a_slow_cookie_check_is_reported_as_transient_not_as_an_expired_cookie():
    def slow(_request):
        raise httpx.ReadTimeout("timed out")

    client = PrintervalApiClient(
        base_url="https://printerval.test", username=None, password=None, team_outsource="team",
        session_cookie="laravel_session=abc", client=httpx.Client(transport=httpx.MockTransport(slow),
                                                                base_url="https://printerval.test"),
    )
    with pytest.raises(PrintervalApiError) as caught:
        client.login()
    assert caught.value.error_class == ErrorClass.TRANSIENT_NETWORK and caught.value.retryable
    assert "hết hạn" not in str(caught.value)


def test_review_push_uses_one_lookup_for_the_locale_and_saves_the_status(world, monkeypatch):
    fake = FakeClient(row={"id": "4141056", "local_code": "uk"})
    monkeypatch.setattr(tasks, "PrintervalApiClient", fake)

    _run(world.order)

    assert fake.find_calls == [("DJ4141056", ("doing",))]  # one queue, not every status
    assert fake.kwargs["timeout"] == tasks.REVIEW_SYNC_TIMEOUT_SECONDS
    assert fake.status_calls == [(4141056, "review", "uk")]
    world.session.refresh(world.order)
    assert world.order.printerval_status == "review"


def test_a_failed_locale_lookup_does_not_block_the_review_push(world, monkeypatch):
    fake = FakeClient()
    fake.find_order = lambda *_a, **_k: (_ for _ in ()).throw(httpx.ReadTimeout("slow"))
    monkeypatch.setattr(tasks, "PrintervalApiClient", fake)

    _run(world.order)

    assert fake.status_calls == [(4141056, "review", "en")]


ALERT = "printerval.write_failed"


def _alerts(session):
    return session.query(DeadLetter).filter_by(source=ALERT).all()


def test_a_transient_failure_is_retried_later_without_alerting_admin(world, monkeypatch):
    slow = PrintervalApiError(ErrorClass.TRANSIENT_NETWORK, "Printerval phản hồi quá chậm", retryable=True)
    monkeypatch.setattr(tasks, "PrintervalApiClient", FakeClient(login_error=slow))
    retried: dict = {}

    class Retry(Exception):
        pass

    def fake_retry(*, countdown, exc, kwargs=None):
        retried["countdown"] = countdown
        retried["kwargs"] = kwargs
        return Retry()

    monkeypatch.setattr(REVIEW, "retry", fake_retry)
    with pytest.raises(Retry):
        _run(world.order)

    assert retried["countdown"] == tasks.REVIEW_SYNC_RETRY_DELAYS[0]
    assert _alerts(world.session) == []


def test_when_retries_run_out_admin_is_asked_to_change_the_status_by_hand(world, monkeypatch):
    slow = PrintervalApiError(ErrorClass.TRANSIENT_NETWORK, "Printerval phản hồi quá chậm", retryable=True)
    monkeypatch.setattr(tasks, "PrintervalApiClient", FakeClient(login_error=slow))

    with patch("app.application.telegram_service.send_message") as telegram:
        _run(world.order, retries=len(tasks.REVIEW_SYNC_RETRY_DELAYS))

    telegram.assert_not_called()  # web toast only
    [alert] = _alerts(world.session)
    assert alert.error_class == "TRANSIENT_NETWORK"
    assert alert.payload["order_code"] == "DJ4141056" and alert.payload["platform_id"] == str(world.platform.id)
    assert "Review" in alert.payload["action"] and "DJ4141056" in alert.recovery_action


def test_a_rejected_status_change_is_not_silently_marked_done(world, monkeypatch):
    monkeypatch.setattr(tasks, "PrintervalApiClient", FakeClient(status_ok=False))

    _run(world.order, retries=len(tasks.REVIEW_SYNC_RETRY_DELAYS))

    world.session.refresh(world.order)
    assert world.order.printerval_status == "doing"
    assert len(_alerts(world.session)) == 1


def test_the_alert_carries_printervals_own_reason_for_refusing_a_status(world, monkeypatch):
    refusal = "HTTP 422: Không thể chuyển từ Done sang Review"
    monkeypatch.setattr(tasks, "PrintervalApiClient", FakeClient(status_ok=False, refusal=refusal))

    _run(world.order, retries=len(tasks.REVIEW_SYNC_RETRY_DELAYS))

    [alert] = _alerts(world.session)
    assert refusal in alert.payload["error"]


def test_the_client_keeps_what_printerval_said_when_it_refuses_a_status():
    def refuse(request):
        if request.method == "PATCH":
            return httpx.Response(422, json={"status": "failed", "message": "Không thể chuyển từ Done sang Review"})
        return httpx.Response(200, json={"status": "successful"})

    client = PrintervalApiClient(
        base_url="https://printerval.test", username=None, password=None, team_outsource="team",
        session_cookie="laravel_session=abc",
        client=httpx.Client(transport=httpx.MockTransport(refuse), base_url="https://printerval.test"),
    )
    assert client.update_order_status(4141056, "review", "uk") is False
    assert client.last_status_error == "HTTP 422: Không thể chuyển từ Done sang Review"


def test_an_expired_session_is_not_retried_and_alerts_at_once(world, monkeypatch):
    expired = PrintervalApiError(ErrorClass.AUTH, "Session Cookie Printerval không hợp lệ")
    monkeypatch.setattr(tasks, "PrintervalApiClient", FakeClient(login_error=expired))
    monkeypatch.setattr(REVIEW, "retry", lambda **_k: pytest.fail("an expired session must not be retried"))

    _run(world.order)

    assert [a.error_class for a in _alerts(world.session)] == ["AUTH"]


def test_a_failed_designer_or_status_request_alerts_admin(world, monkeypatch):
    designer = User(username=f"des-{uuid.uuid4().hex[:5]}", full_name="Linh", role="designer", password_hash="x",
                    active=True, platform_id=world.platform.id)
    world.session.add(designer)
    world.session.flush()
    request = PrintervalAssignmentRequest(
        order_id=world.order.id, platform_id=world.platform.id, internal_designer_id=designer.id,
        designer_option="Linh - 2D Prin", target_status="Doing", lifecycle="pending",
    )
    world.session.add(request)
    world.session.commit()

    def failing_execute(session, adapter, req):
        req.lifecycle = "failed"
        req.error_class = "TRANSIENT_NETWORK"
        req.error_message = "Không gán được Designer Linh - 2D Prin trên Printerval"
        session.commit()

    monkeypatch.setattr(tasks, "execute_request", failing_execute)
    monkeypatch.setattr(tasks, "PrintervalApiClient", FakeClient())
    tasks.sync_printerval_assignment_request(str(request.id))

    [alert] = _alerts(world.session)
    assert "Linh - 2D Prin" in alert.payload["action"] and "Doing" in alert.payload["action"]
    assert "Không gán được Designer" in alert.payload["error"] and "DJ4141056" in alert.recovery_action


def test_admin_web_reads_only_its_platforms_new_alerts(client, world):
    from datetime import UTC, datetime, timedelta

    from app.application.auth import create_session_token
    from app.application.printerval_alerts import record_write_failure

    other = Platform(name="Other", account_username="o@print.com", is_active=True)
    world.session.add(other)
    world.session.flush()
    stranger = Order(external_order_id="DJ-OTHER", platform_id=other.id, state=OrderState.QC_PENDING.value,
                     duplicate_check_status="uncheck", work_domain="standard")
    world.session.add(stranger)
    world.session.commit()
    record_write_failure(world.session, world.order, action="đổi trạng thái sang Review", error="chậm",
                         manual="vào Printerval chuyển đơn DJ4141056 sang Review")
    record_write_failure(world.session, stranger, action="x", error="y", manual="z")
    admin = world.session.query(User).filter_by(role="admin", platform_id=world.platform.id).first()
    headers = {"Authorization": f"Bearer {create_session_token(str(admin.id), admin.role)}"}

    items = client.get("/api/printerval-alerts", headers=headers).json()["items"]
    assert [i["order_code"] for i in items] == ["DJ4141056"]
    assert items[0]["manual"] == "vào Printerval chuyển đơn DJ4141056 sang Review"

    later = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
    assert client.get("/api/printerval-alerts", params={"since": later}, headers=headers).json()["items"] == []

    designer = User(username=f"d-{uuid.uuid4().hex[:5]}", full_name="D", role="designer", password_hash="x", active=True,
                    platform_id=world.platform.id)
    world.session.add(designer)
    world.session.commit()
    denied = client.get("/api/printerval-alerts",
                        headers={"Authorization": f"Bearer {create_session_token(str(designer.id), designer.role)}"})
    assert denied.status_code == 403


def test_a_status_sync_saving_the_order_meanwhile_does_not_break_the_review_push(world, monkeypatch):
    from sqlalchemy import text

    fake = FakeClient()
    real_update = fake.update_order_status

    def update_then_sync_saves(row_id, status, locale, extra=None):
        ok = real_update(row_id, status, locale)
        with world.session.get_bind().begin() as conn:  # the status sync saved the order meanwhile
            conn.execute(text("UPDATE orders SET version = version + 1 WHERE id = :id"), {"id": world.order.id})
        return ok

    fake.update_order_status = update_then_sync_saves
    monkeypatch.setattr(tasks, "PrintervalApiClient", fake)

    _run(world.order)

    world.session.refresh(world.order)
    assert world.order.printerval_status == "review"
    assert _alerts(world.session) == []


def test_a_crashing_request_is_ended_failed_not_left_pending(world, monkeypatch):
    designer = User(username=f"des-{uuid.uuid4().hex[:5]}", full_name="Linh", role="designer", password_hash="x",
                    active=True, platform_id=world.platform.id)
    world.session.add(designer)
    world.session.flush()
    request = PrintervalAssignmentRequest(
        order_id=world.order.id, platform_id=world.platform.id, internal_designer_id=designer.id,
        designer_option="Linh - 2D Prin", target_status="Doing", lifecycle="pending",
    )
    world.session.add(request)
    world.session.commit()

    def crash(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(tasks, "execute_request", crash)
    monkeypatch.setattr(tasks, "PrintervalApiClient", FakeClient())
    tasks.sync_printerval_assignment_request(str(request.id))

    world.session.refresh(request)
    assert request.lifecycle == "failed" and "boom" in request.error_message
    assert len(_alerts(world.session)) == 1


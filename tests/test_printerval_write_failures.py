"""A write to Printerval that fails must be retried when it may succeed later, and otherwise end in
a DeadLetter plus a Telegram alert asking Admin to do it by hand (incident 2026-10-14: a slow
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
    def __init__(self, *, login_error=None, status_ok=True, row=None):
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

    def update_order_status(self, row_id, status, locale):
        self.status_calls.append((row_id, status, locale))
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


def test_a_transient_failure_is_retried_later_without_alerting_admin(world, monkeypatch):
    slow = PrintervalApiError(ErrorClass.TRANSIENT_NETWORK, "Printerval phản hồi quá chậm", retryable=True)
    monkeypatch.setattr(tasks, "PrintervalApiClient", FakeClient(login_error=slow))
    retried: dict = {}

    class Retry(Exception):
        pass

    def fake_retry(*, countdown, exc):
        retried["countdown"] = countdown
        return Retry()

    monkeypatch.setattr(REVIEW, "retry", fake_retry)
    with patch("app.application.telegram_service.send_message") as send, pytest.raises(Retry):
        _run(world.order)

    assert retried["countdown"] == tasks.REVIEW_SYNC_RETRY_DELAYS[0]
    send.assert_not_called()
    assert world.session.query(DeadLetter).filter_by(source="printerval.review_sync").count() == 0


def test_when_retries_run_out_admin_is_asked_to_change_the_status_by_hand(world, monkeypatch):
    slow = PrintervalApiError(ErrorClass.TRANSIENT_NETWORK, "Printerval phản hồi quá chậm", retryable=True)
    monkeypatch.setattr(tasks, "PrintervalApiClient", FakeClient(login_error=slow))

    with patch("app.application.telegram_service.send_message", return_value={"message_id": 1}) as send:
        _run(world.order, retries=len(tasks.REVIEW_SYNC_RETRY_DELAYS))

    letter = world.session.query(DeadLetter).filter_by(source="printerval.review_sync").one()
    assert letter.error_class == "TRANSIENT_NETWORK" and "DJ4141056" in letter.recovery_action
    chat, text = send.call_args.args
    assert chat == "5550001"
    assert "DJ4141056" in text and "Review" in text and "Cần làm tay" in text


def test_a_rejected_status_change_is_not_silently_marked_done(world, monkeypatch):
    monkeypatch.setattr(tasks, "PrintervalApiClient", FakeClient(status_ok=False))

    with patch("app.application.telegram_service.send_message", return_value={"message_id": 1}):
        _run(world.order, retries=len(tasks.REVIEW_SYNC_RETRY_DELAYS))

    world.session.refresh(world.order)
    assert world.order.printerval_status == "doing"
    assert world.session.query(DeadLetter).filter_by(source="printerval.review_sync").count() == 1


def test_an_expired_session_is_not_retried_and_alerts_at_once(world, monkeypatch):
    expired = PrintervalApiError(ErrorClass.AUTH, "Session Cookie Printerval không hợp lệ")
    monkeypatch.setattr(tasks, "PrintervalApiClient", FakeClient(login_error=expired))
    monkeypatch.setattr(REVIEW, "retry", lambda **_k: pytest.fail("an expired session must not be retried"))

    with patch("app.application.telegram_service.send_message", return_value={"message_id": 1}) as send:
        _run(world.order)

    assert send.called
    assert world.session.query(DeadLetter).filter_by(source="printerval.review_sync").one().error_class == "AUTH"


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
        req.error_message = "Printerval phản hồi quá chậm"
        session.commit()

    monkeypatch.setattr(tasks, "execute_request", failing_execute)
    monkeypatch.setattr(tasks, "PrintervalApiClient", FakeClient())
    with patch("app.application.telegram_service.send_message", return_value={"message_id": 1}) as send:
        tasks.sync_printerval_assignment_request(str(request.id))

    text = send.call_args.args[1]
    assert "DJ4141056" in text and "Linh - 2D Prin" in text and "Doing" in text and "Cần làm tay" in text

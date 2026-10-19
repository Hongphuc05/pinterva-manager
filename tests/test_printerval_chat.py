"""Printerval's per-order chat: read on demand for Admin, never mirrored wholesale, never shown to others."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

import app.application.status_sync as status_sync_module
from app.adapters.db.models import ExternalObservation, Order, Platform, User
from app.application import printerval_chat as chat
from app.application.auth import create_session_token
from app.application.telegram_service import notify_admin_new_fix
from app.config import get_settings
from app.domain.models import OrderState
from app.workers import printerval_chat_tasks as tasks

FIX_OPEN = {
    "id": 11, "fix_round": 1, "type": "fix_open", "sender_type": "staff", "sender_name": "QC An", "mine": False,
    "content": "Sửa lại phần tay áo", "image_urls": ["https://img.test/a.png", "javascript:alert(1)"],
    "fix_reason_label": "Sai màu", "created_at": "2026-10-19 14:05:10",
}
REPLY = {
    "id": 12, "fix_round": 1, "type": "message", "sender_type": "outsource", "sender_name": "Admin", "mine": True,
    "content": "Đã nhận", "image_urls": [], "fix_reason_label": "", "created_at": "2026-10-19 14:06:00",
}


class FakeChat:
    """Stands in for ``printerval_client_for``: one object that is its own client and context manager."""

    def __init__(self, messages=(), unread_ids=(), counts=None, fail=False):
        self.messages = list(messages)
        self.unread_ids = list(unread_ids)
        self.counts = counts or {}
        self.fail = fail
        self.calls: list[tuple] = []

    def __call__(self, _platform):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def login(self):
        if self.fail:
            raise RuntimeError("Printerval is slow")

    def fetch_chat_messages(self, job_id, after_id=0):
        self.calls.append(("messages", int(job_id), after_id))
        return {"messages": [m for m in self.messages if m["id"] > after_id], "chat": {}}

    def fetch_chat_unread(self, ids):
        self.calls.append(("unread", list(ids)))
        return {"job_ids": self.unread_ids, "unread": {str(i): self.counts.get(i, 1) for i in ids}}


@pytest.fixture()
def world(db_session):
    platform = Platform(name="P chat", account_username="c@print.com", session_cookie="x", team_outsource="team",
                        is_active=True)
    db_session.add(platform)
    db_session.flush()
    admin = User(username=f"adm-{uuid.uuid4().hex[:5]}", full_name="Admin", role="admin", password_hash="x",
                 active=True, platform_id=platform.id, telegram_chat_id="5550002")
    order = Order(external_order_id="DJ4160071", platform_id=platform.id, state=OrderState.REVISION.value,
                  printerval_status="fix", duplicate_check_status="uncheck", work_domain="standard",
                  note_outsource="https://drive.google.com/file/d/ours")
    db_session.add_all([admin, order])
    db_session.commit()
    chat._unread_cache.clear()
    return type("W", (), {"platform": platform, "admin": admin, "order": order, "session": db_session})


def test_capture_stores_only_the_messages_new_since_the_last_snapshot(world):
    fake = FakeChat([FIX_OPEN])
    first = chat.capture_chat(world.session, world.order, "fix", client_factory=fake)
    world.session.commit()

    assert first.evidence["last_message_id"] == 11 and first.evidence["trigger_status"] == "fix"
    [message] = first.evidence["messages"]
    assert message["image_urls"] == ["https://img.test/a.png"]  # only http(s) links survive
    assert message["sent_at"] == "2026-10-19T07:05:10+00:00"  # Printerval's Vietnam time, stored as UTC

    assert chat.capture_chat(world.session, world.order, "done", client_factory=fake) is None  # nothing new

    fake.messages.append(REPLY)
    second = chat.capture_chat(world.session, world.order, "done", client_factory=fake)
    assert [m["id"] for m in second.evidence["messages"]] == [12]
    assert fake.calls[-1] == ("messages", 4160071, 11)  # asked only for what came after the snapshot
    assert world.session.query(ExternalObservation).filter_by(order_id=world.order.id).count() == 2


def test_the_fix_reason_is_qcs_message_not_ours(world):
    assert chat.latest_fix_reason(world.session, world.order) is None
    chat.capture_chat(world.session, world.order, "fix", client_factory=FakeChat([FIX_OPEN, REPLY]))
    world.session.commit()
    assert chat.latest_fix_reason(world.session, world.order) == "Sai màu — Sửa lại phần tay áo"


def _card(world):
    with patch("app.application.telegram_service.send_telegram_request") as send:
        send.return_value = {"ok": True}
        assert notify_admin_new_fix(world.session, world.order.id) is True
    payload = send.call_args.args[1]
    return payload.get("caption") or payload["text"]


def test_the_telegram_fix_card_quotes_the_chat_and_never_the_pushed_link(world):
    assert "khung chat" in _card(world)  # nothing captured yet: it points to the chat on Tacahu
    chat.capture_chat(world.session, world.order, "fix", client_factory=FakeChat([FIX_OPEN]))
    world.session.commit()
    card = _card(world)
    assert "Sửa lại phần tay áo" in card and "drive.google.com" not in card


def test_unread_orders_lists_this_platforms_active_orders_and_is_cached(world):
    other = Order(external_order_id="DJ4160072", platform_id=world.platform.id, state=OrderState.DONE.value,
                  duplicate_check_status="uncheck", work_domain="standard")
    world.session.add(other)
    world.session.commit()
    fake = FakeChat(unread_ids=[4160071, 4160072, 999], counts={4160071: 3})

    items = chat.unread_orders(world.session, world.platform, client_factory=fake)

    assert items == [{"order_id": str(world.order.id), "order_code": "DJ4160071", "count": 3}]
    assert chat.unread_orders(world.session, world.platform, client_factory=fake) == items
    assert [c[0] for c in fake.calls] == ["unread", "unread"]  # the second poll hit the cache


def test_a_slow_printerval_is_not_asked_again_for_30_seconds(world):
    clock = [1000.0]
    now = lambda: clock[0]  # noqa: E731
    good = FakeChat(unread_ids=[4160071])
    first = chat.unread_orders(world.session, world.platform, client_factory=good, now=now)

    clock[0] += 61
    slow = FakeChat(fail=True)
    with pytest.raises(RuntimeError):
        chat.unread_orders(world.session, world.platform, client_factory=slow, now=now)
    clock[0] += 10
    assert chat.unread_orders(world.session, world.platform, client_factory=slow, now=now) == first
    assert slow.calls == []  # cooling down: no new request


def test_a_status_change_to_fix_confirm_or_done_reads_the_chat_once(world, monkeypatch):
    queued: list[tuple] = []
    monkeypatch.setattr(tasks, "dispatch_chat_capture", lambda order_id, status, notify=False: queued.append(
        (order_id, status, notify)))
    order = world.order

    order.printerval_status = "done"
    status_sync_module._dispatch_chat_read(order, "review")
    status_sync_module._dispatch_chat_read(order, "done")  # unchanged
    order.printerval_status = "doing"
    status_sync_module._dispatch_chat_read(order, "review")  # not a watched status
    order.printerval_status = "confirm"
    status_sync_module._dispatch_chat_read(order, "review")

    assert queued == [(order.id, "done", False), (order.id, "confirm", False)]


def test_a_new_fix_reads_the_chat_then_notifies_unless_chat_reads_are_off(world, monkeypatch):
    queued: list[tuple] = []
    monkeypatch.setattr(tasks, "dispatch_chat_capture", lambda order_id, status, notify=False: queued.append(
        (status, notify)))
    legacy: list[str] = []
    monkeypatch.setattr("app.workers.telegram_tasks.safe_dispatch_telegram_task",
                        lambda _task, order_id, *_a: legacy.append(order_id))

    monkeypatch.setattr(get_settings(), "order_chat_enabled", True)
    status_sync_module._dispatch_admin_fix_notifications(world.session, world.order)
    assert queued == [("fix", True)] and legacy == []

    monkeypatch.setattr(get_settings(), "order_chat_enabled", False)
    status_sync_module._dispatch_admin_fix_notifications(world.session, world.order)
    assert queued == [("fix", True)] and legacy == [str(world.order.id)]  # the card still goes out, as before


class _KeepOpen:
    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


def _run_capture(order, status="fix", retries=0, notify=True):
    task = tasks.capture_order_chat
    task.push_request(retries=retries)
    try:
        return task.run(str(order.id), status, notify)
    finally:
        task.pop_request()


def test_the_fix_card_goes_out_even_when_the_chat_cannot_be_read_and_the_read_is_retried(world, monkeypatch):
    monkeypatch.setattr(tasks, "SessionLocal", lambda: _KeepOpen(world.session))
    monkeypatch.setattr(tasks, "capture_chat", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("slow")))
    monkeypatch.setattr(tasks, "is_telegram_configured", lambda: True)
    cards: list = []
    monkeypatch.setattr(tasks, "notify_admin_new_fix", lambda _s, order_id: cards.append(order_id))
    retried: dict = {}

    class Retry(Exception):
        pass

    def fake_retry(*, countdown, kwargs):
        retried.update(countdown=countdown, kwargs=kwargs)
        return Retry()

    monkeypatch.setattr(tasks.capture_order_chat, "retry", fake_retry)
    with pytest.raises(Retry):
        _run_capture(world.order)

    assert cards == [world.order.id]
    assert retried == {"countdown": tasks.CAPTURE_RETRY_DELAYS[0], "kwargs": {"notify": False}}


def test_only_a_fix_sends_a_card_and_the_retry_never_repeats_it(world, monkeypatch):
    monkeypatch.setattr(tasks, "SessionLocal", lambda: _KeepOpen(world.session))
    monkeypatch.setattr(tasks, "capture_chat", lambda *_a, **_k: None)
    monkeypatch.setattr(tasks, "is_telegram_configured", lambda: True)
    cards: list = []
    monkeypatch.setattr(tasks, "notify_admin_new_fix", lambda _s, order_id: cards.append(order_id))

    _run_capture(world.order, status="done")
    _run_capture(world.order, status="fix", notify=False)
    assert cards == []
    _run_capture(world.order, status="fix", notify=True)
    assert cards == [world.order.id]


def _headers(user):
    return {"Authorization": f"Bearer {create_session_token(str(user.id), user.role)}"}


def test_admin_opens_an_orders_chat_and_nobody_else_can(client, world, monkeypatch):
    monkeypatch.setattr("app.api.routes.printerval_chat_api.fetch_messages",
                        lambda *_a, **_k: [chat.parse_message(FIX_OPEN)])
    url = f"/api/orders/{world.order.id}/printerval-chat"

    ok = client.get(url, headers=_headers(world.admin))
    assert ok.status_code == 200 and ok.json()["messages"][0]["content"] == "Sửa lại phần tay áo"

    for role in ("designer", "designer-trello", "support", "accountant"):
        user = User(username=f"{role}-{uuid.uuid4().hex[:5]}", full_name=role, role=role, password_hash="x",
                    active=True, platform_id=world.platform.id)
        world.session.add(user)
        world.session.commit()
        assert client.get(url, headers=_headers(user)).status_code == 403, role


def test_an_admin_of_another_platform_gets_404_and_a_printerval_failure_gets_502(client, world, monkeypatch):
    other = Platform(name="Other chat", account_username="o@print.com", is_active=True)
    world.session.add(other)
    world.session.flush()
    stranger = User(username=f"adm-{uuid.uuid4().hex[:5]}", full_name="Other", role="admin", password_hash="x",
                    active=True, platform_id=other.id)
    world.session.add(stranger)
    world.session.commit()
    url = f"/api/orders/{world.order.id}/printerval-chat"
    assert client.get(url, headers=_headers(stranger)).status_code == 404

    monkeypatch.setattr("app.api.routes.printerval_chat_api.fetch_messages",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("slow")))
    assert client.get(url, headers=_headers(world.admin)).status_code == 502


def test_unread_endpoint_is_admin_only_and_degrades_to_an_empty_stale_list(client, world, monkeypatch):
    monkeypatch.setattr(get_settings(), "order_chat_enabled", True)
    monkeypatch.setattr("app.api.routes.printerval_chat_api.unread_orders",
                        lambda *_a, **_k: [{"order_id": "x", "order_code": "DJ1", "count": 2}])
    body = client.get("/api/printerval-chat/unread", headers=_headers(world.admin)).json()
    assert body == {"items": [{"order_id": "x", "order_code": "DJ1", "count": 2}], "stale": False}

    monkeypatch.setattr("app.api.routes.printerval_chat_api.unread_orders",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("down")))
    assert client.get("/api/printerval-chat/unread", headers=_headers(world.admin)).json() == {
        "items": [], "stale": True}

    designer = User(username=f"d-{uuid.uuid4().hex[:5]}", full_name="D", role="designer", password_hash="x",
                    active=True, platform_id=world.platform.id)
    world.session.add(designer)
    world.session.commit()
    assert client.get("/api/printerval-chat/unread", headers=_headers(designer)).status_code == 403


def test_admin_sees_the_fix_reason_on_list_rows_and_the_detail_but_nobody_else_does(client, world):
    from app.api.routes.orders_api import _summarize_orders

    chat.capture_chat(world.session, world.order, "fix", client_factory=FakeChat([FIX_OPEN]))
    world.session.commit()

    [row] = _summarize_orders(world.session, world.admin, [world.order])
    assert row.fix_reason == "Sai màu — Sửa lại phần tay áo"
    detail = client.get(f"/api/orders/{world.order.id}", headers=_headers(world.admin)).json()["order"]
    assert detail["fix_reason"] == "Sai màu — Sửa lại phần tay áo"

    support = User(username=f"s-{uuid.uuid4().hex[:5]}", full_name="S", role="support", password_hash="x",
                   active=True, platform_id=world.platform.id)
    world.session.add(support)
    world.session.commit()
    [support_row] = _summarize_orders(world.session, support, [world.order])
    assert getattr(support_row, "fix_reason", None) is None  # the non-Admin row type has no such field

    world.order.state = OrderState.QC_PENDING.value  # only orders in Fix carry a reason
    [back_in_review] = _summarize_orders(world.session, world.admin, [world.order])
    assert back_in_review.fix_reason is None

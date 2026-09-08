"""Tests for the Celery task wrapper itself (plumbing/error handling) — the actual
sync logic is covered directly in test_assignment_sync.py. Mirrors how
test_crawl_tasks.py tests crawl_and_claim's own failure paths: mock the module-level
dependencies (SessionLocal, playwright_session) rather than relying on cross-connection
DB visibility, since the task opens its own session independent of the test's."""

import uuid

from app.workers import assignment_sync_tasks


class _FakeSession:
    def __init__(self, objects: dict):
        self._objects = objects
        self.closed = False

    def get(self, model, pk):
        return self._objects.get((model.__name__, str(pk)))

    def close(self):
        self.closed = True


def test_task_returns_quietly_when_order_or_designer_missing(monkeypatch):
    fake_session = _FakeSession({})  # nothing exists
    monkeypatch.setattr(assignment_sync_tasks, "SessionLocal", lambda: fake_session)

    assignment_sync_tasks.sync_assignment_to_printerval_task(str(uuid.uuid4()), str(uuid.uuid4()))

    assert fake_session.closed is True  # always cleans up, even on early return


def test_task_returns_quietly_when_designer_not_registered_on_printerval(monkeypatch):
    from app.adapters.db.models import Order, User

    order_id, designer_id = uuid.uuid4(), uuid.uuid4()
    order = Order(id=order_id, external_order_id="DJ0000001")
    designer = User(id=designer_id, printerval_designer_option=None)
    fake_session = _FakeSession({("Order", str(order_id)): order, ("User", str(designer_id)): designer})
    monkeypatch.setattr(assignment_sync_tasks, "SessionLocal", lambda: fake_session)

    calls = []
    monkeypatch.setattr(assignment_sync_tasks, "playwright_session", lambda **k: calls.append(k))

    assignment_sync_tasks.sync_assignment_to_printerval_task(str(order_id), str(designer_id))

    assert calls == []  # never even tries to open a browser for an unregistered designer
    assert fake_session.closed is True


def test_task_logs_and_returns_when_playwright_session_fails_to_open(monkeypatch):
    from app.adapters.db.models import Order, Platform, User

    order_id, designer_id, platform_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    order = Order(id=order_id, external_order_id="DJ0000001", platform_id=platform_id)
    designer = User(id=designer_id, printerval_designer_option="Linh Designer - 2D Prin")
    platform = Platform(id=platform_id, account_username="acc@printerval.com", account_password="pw")
    fake_session = _FakeSession(
        {
            ("Order", str(order_id)): order,
            ("User", str(designer_id)): designer,
            ("Platform", str(platform_id)): platform,
        }
    )
    monkeypatch.setattr(assignment_sync_tasks, "SessionLocal", lambda: fake_session)

    def _boom(**kwargs):
        raise RuntimeError("Cloudflare/login not ready")

    monkeypatch.setattr(assignment_sync_tasks, "playwright_session", _boom)

    # Must not raise — a browser that never opened must not crash the task.
    assignment_sync_tasks.sync_assignment_to_printerval_task(str(order_id), str(designer_id))

    assert fake_session.closed is True

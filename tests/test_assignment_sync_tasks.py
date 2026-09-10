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

    def commit(self):
        pass

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

    assignment_sync_tasks.sync_assignment_to_printerval_task(str(order_id), str(designer_id))

    assert fake_session.closed is True


def test_task_logs_and_returns_when_playwright_session_fails_to_open(monkeypatch):
    """Regression test: `playwright_session`/`PlaywrightPrintervalAdapter` used to not
    be imported into this module at all — a real designer assignment always hit a
    NameError here, silently swallowed by the surrounding try/except as if the browser
    itself had failed to open, so a Designer never actually got synced to Printerval
    from the OrdersListPage assign flow."""
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


class _FakePrintervalAssignmentRequest:
    def __init__(self, id, platform_id):
        self.id = id
        self.platform_id = platform_id
        self.lifecycle = "pending"
        self.error_class = None
        self.error_message = None


def test_sync_printerval_assignment_request_returns_quietly_when_request_missing(monkeypatch):
    fake_session = _FakeSession({})
    monkeypatch.setattr(assignment_sync_tasks, "SessionLocal", lambda: fake_session)

    assignment_sync_tasks.sync_printerval_assignment_request(str(uuid.uuid4()))

    assert fake_session.closed is True


def test_sync_printerval_assignment_request_fails_fast_when_platform_has_no_credentials(monkeypatch):
    request_id, platform_id = uuid.uuid4(), uuid.uuid4()
    from app.adapters.db.models import Platform

    request = _FakePrintervalAssignmentRequest(request_id, platform_id)
    platform = Platform(id=platform_id, account_username="acc@printerval.com", account_password=None)
    fake_session = _FakeSession(
        {
            ("PrintervalAssignmentRequest", str(request_id)): request,
            ("Platform", str(platform_id)): platform,
        }
    )
    monkeypatch.setattr(assignment_sync_tasks, "SessionLocal", lambda: fake_session)

    assignment_sync_tasks.sync_printerval_assignment_request(str(request_id))

    assert request.lifecycle == "failed"
    assert request.error_class == "AUTH"
    assert fake_session.closed is True


def test_sync_printerval_assignment_request_passes_a_playwright_fallback_when_it_opens(monkeypatch):
    """Regression test (live incident 2026-09-09): a *fresh* HTTP login started
    getting rejected (403/AUTH) after this endpoint had been hit repeatedly in a short
    window, even with correct credentials — while the persistent Chrome profile (no
    fresh login per call) kept working. Without a fallback wired in, one rejected
    login permanently failed the whole write with no recovery path."""
    request_id, platform_id = uuid.uuid4(), uuid.uuid4()
    from app.adapters.db.models import Platform

    request = _FakePrintervalAssignmentRequest(request_id, platform_id)
    platform = Platform(id=platform_id, account_username="acc@printerval.com", account_password="pw")
    fake_session = _FakeSession(
        {
            ("PrintervalAssignmentRequest", str(request_id)): request,
            ("Platform", str(platform_id)): platform,
        }
    )
    monkeypatch.setattr(assignment_sync_tasks, "SessionLocal", lambda: fake_session)

    class _FakePage:
        pass

    class _FakePlaywrightSessionCM:
        def __enter__(self):
            return _FakePage()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(assignment_sync_tasks, "playwright_session", lambda **k: _FakePlaywrightSessionCM())
    monkeypatch.setattr(assignment_sync_tasks, "PlaywrightPrintervalAdapter", lambda **k: "fake-playwright-adapter")

    captured = {}

    def _fake_execute_request(session, adapter, req):
        captured["adapter"] = adapter
        return {"lifecycle": "succeeded"}

    monkeypatch.setattr(assignment_sync_tasks, "execute_request", _fake_execute_request)

    assignment_sync_tasks.sync_printerval_assignment_request(str(request_id))

    assert captured["adapter"].fallback_adapter == "fake-playwright-adapter"
    assert fake_session.closed is True


def test_sync_printerval_assignment_request_continues_http_only_when_playwright_fails_to_open(monkeypatch):
    request_id, platform_id = uuid.uuid4(), uuid.uuid4()
    from app.adapters.db.models import Platform

    request = _FakePrintervalAssignmentRequest(request_id, platform_id)
    platform = Platform(id=platform_id, account_username="acc@printerval.com", account_password="pw")
    fake_session = _FakeSession(
        {
            ("PrintervalAssignmentRequest", str(request_id)): request,
            ("Platform", str(platform_id)): platform,
        }
    )
    monkeypatch.setattr(assignment_sync_tasks, "SessionLocal", lambda: fake_session)

    def _boom(**kwargs):
        raise RuntimeError("Cloudflare/login not ready")

    monkeypatch.setattr(assignment_sync_tasks, "playwright_session", _boom)

    captured = {}

    def _fake_execute_request(session, adapter, req):
        captured["adapter"] = adapter
        return {"lifecycle": "succeeded"}

    monkeypatch.setattr(assignment_sync_tasks, "execute_request", _fake_execute_request)

    # Must not raise — falls back to HTTP-only instead of aborting the whole request.
    assignment_sync_tasks.sync_printerval_assignment_request(str(request_id))

    assert captured["adapter"].fallback_adapter is None
    assert fake_session.closed is True

import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import User
from app.api.deps import get_db
from app.api.main import create_app
from app.application.auth import hash_password


@pytest.fixture()
def client(db_session):
    app = create_app()

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_login_session():
    """The login_session module holds one process-wide `_login_session` global —
    reset it around every test in this file so state never leaks between tests."""
    from app.adapters.printerval import login_session

    login_session._login_session = None
    yield
    login_session._login_session = None


def _login(client, db_session, role, username="user1"):
    user = User(
        username=username, full_name=username, role=role,
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(user)
    db_session.commit()
    client.post("/login", data={"username": username, "password": "s3cret!"})
    return user


class _FakePage:
    def __init__(self):
        self.url = None

    def goto(self, url):
        self.url = url


class _FakeContext:
    def __init__(self):
        self.pages = []
        self.closed = False

    def close(self):
        self.closed = True


class _FakePlaywrightCM:
    def __init__(self):
        self.exited = False

    def __exit__(self, *args):
        self.exited = True


def test_printerval_login_page_requires_admin(client, db_session):
    _login(client, db_session, "designer")

    resp = client.get("/printerval-login")

    assert resp.status_code == 403


def test_printerval_login_start_requires_admin(client, db_session):
    _login(client, db_session, "designer")

    resp = client.post("/printerval-login/start")

    assert resp.status_code == 403


def test_printerval_login_start_opens_a_session_and_redirects(client, db_session, monkeypatch):
    from app.adapters.printerval import login_session

    fake_page = _FakePage()
    fake_context = _FakeContext()
    fake_cm = _FakePlaywrightCM()

    def _fake_open(*args, **kwargs):
        return fake_cm, fake_context, fake_page

    monkeypatch.setattr(login_session, "open_playwright_session", _fake_open)

    _login(client, db_session, "admin")
    resp = client.post("/printerval-login/start", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/printerval-login"
    assert login_session._login_session is not None
    assert login_session._login_session["context"] is fake_context
    assert fake_page.url == login_session.ADMIN_URL


def test_printerval_login_start_reuses_an_already_open_session(client, db_session, monkeypatch):
    """A second click on "start" while a window is already open must not open a
    second browser — reuse the existing one."""
    from app.adapters.printerval import login_session

    calls = {"n": 0}

    def _fake_open(*args, **kwargs):
        calls["n"] += 1
        return _FakePlaywrightCM(), _FakeContext(), _FakePage()

    monkeypatch.setattr(login_session, "open_playwright_session", _fake_open)

    _login(client, db_session, "admin")
    client.post("/printerval-login/start")
    client.post("/printerval-login/start")

    assert calls["n"] == 1


def test_printerval_login_start_opens_fresh_session_if_previous_one_is_stale(
    client, db_session, monkeypatch
):
    """If the human closed the Chrome window by hand (not via Done), the stored
    context is dead — accessing it raises, and start must recover by opening fresh."""
    from app.adapters.printerval import login_session

    class _DeadContext:
        @property
        def pages(self):
            raise RuntimeError("Target page, context or browser has been closed")

    login_session._login_session = {
        "playwright_cm": _FakePlaywrightCM(), "context": _DeadContext()
    }

    calls = {"n": 0}

    def _fake_open(*args, **kwargs):
        calls["n"] += 1
        return _FakePlaywrightCM(), _FakeContext(), _FakePage()

    monkeypatch.setattr(login_session, "open_playwright_session", _fake_open)

    _login(client, db_session, "admin")
    resp = client.post("/printerval-login/start", follow_redirects=False)

    assert resp.status_code == 303
    assert calls["n"] == 1
    assert isinstance(login_session._login_session["context"], _FakeContext)


def test_printerval_login_page_reflects_open_state(client, db_session):
    from app.adapters.printerval import login_session

    login_session._login_session = {
        "playwright_cm": _FakePlaywrightCM(), "context": _FakeContext()
    }

    _login(client, db_session, "admin")
    resp = client.get("/printerval-login")

    assert resp.status_code == 200
    assert "Done" in resp.text


def test_printerval_login_page_reflects_closed_state(client, db_session):
    _login(client, db_session, "admin")

    resp = client.get("/printerval-login")

    assert resp.status_code == 200
    assert "Mở Chrome để đăng nhập" in resp.text


def test_printerval_login_done_requires_admin(client, db_session):
    _login(client, db_session, "designer")

    resp = client.post("/printerval-login/done")

    assert resp.status_code == 403


def test_printerval_login_done_closes_the_session_and_redirects(client, db_session, monkeypatch):
    from app.adapters.printerval import login_session

    closed = {"context": False, "cm_exited": False}

    class _TrackingContext(_FakeContext):
        def close(self):
            closed["context"] = True

    class _TrackingCM(_FakePlaywrightCM):
        def __exit__(self, *args):
            closed["cm_exited"] = True

    def _fake_close(playwright_cm, context):
        context.close()
        playwright_cm.__exit__(None, None, None)

    monkeypatch.setattr(login_session, "close_playwright_session", _fake_close)
    login_session._login_session = {
        "playwright_cm": _TrackingCM(), "context": _TrackingContext()
    }

    _login(client, db_session, "admin")
    resp = client.post("/printerval-login/done", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/orders"
    assert closed["context"] is True
    assert closed["cm_exited"] is True
    assert login_session._login_session is None


def test_printerval_login_done_is_a_no_op_when_nothing_is_open(client, db_session):
    _login(client, db_session, "admin")

    resp = client.post("/printerval-login/done", follow_redirects=False)

    assert resp.status_code == 303

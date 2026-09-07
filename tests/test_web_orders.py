import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import Order, User
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
    client.post("/login", data={"username": username, "password": "s3cret!"})
    return user


def test_root_redirects_authed_user_to_orders(client, db_session):
    _login(client, db_session, "admin")
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/orders"


def test_orders_requires_login_redirects_to_login(client):
    resp = client.get("/orders", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_orders_list_shows_all_orders_for_admin(client, db_session):
    _login(client, db_session, "admin")
    db_session.add(Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value))
    db_session.add(Order(external_order_id="DJ2", state=OrderState.DISCOVERED.value))
    db_session.commit()

    resp = client.get("/orders")

    assert resp.status_code == 200
    assert "DJ1" in resp.text
    assert "DJ2" in resp.text


def test_orders_list_shows_empty_for_designer_with_no_assignments(client, db_session):
    _login(client, db_session, "designer")
    db_session.add(Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value))
    db_session.commit()

    resp = client.get("/orders")

    assert resp.status_code == 200
    assert "DJ1" not in resp.text


def test_orders_table_partial_returns_only_table_fragment(client, db_session):
    _login(client, db_session, "admin")

    resp = client.get("/orders/table")

    assert resp.status_code == 200
    assert "<table" in resp.text
    assert "<html" not in resp.text


def test_orders_refresh_requires_admin_403_for_designer(client, db_session):
    _login(client, db_session, "designer")

    resp = client.post("/orders/refresh")

    assert resp.status_code == 403


def test_orders_refresh_runs_crawl_and_shows_summary(client, db_session, monkeypatch):
    from contextlib import contextmanager

    from app.api.routes import web

    @contextmanager
    def _fake_session():
        yield object()

    def _fake_run_crawl_cycle(session, adapter, limit=40):
        return {
            "discovered": 2,
            "claimed": 2,
            "failed_claim": 0,
            "imported": 1,
            "failed_import": 1,
        }

    monkeypatch.setattr(web, "playwright_session", _fake_session)
    monkeypatch.setattr(web, "run_crawl_cycle", _fake_run_crawl_cycle)

    _login(client, db_session, "admin")
    resp = client.post("/orders/refresh")

    assert resp.status_code == 200
    assert "2 đơn mới" in resp.text
    assert "1 đơn nhập thành công" in resp.text
    assert "1 lỗi" in resp.text


def test_orders_refresh_shows_error_message_on_playwright_failure(client, db_session, monkeypatch):
    from app.api.routes import web

    def _boom(*args, **kwargs):
        raise RuntimeError("Cloudflare/login not ready")

    monkeypatch.setattr(web, "playwright_session", _boom)

    _login(client, db_session, "admin")
    resp = client.post("/orders/refresh")

    assert resp.status_code == 200
    assert "Crawl thất bại" in resp.text


def test_orders_refresh_shows_distinct_message_on_discover_failure(client, db_session, monkeypatch):
    """Regression test for the real incident: a genuinely visible Waiting order on the
    live site was reported as "0 new orders" (looking like success) because a discover
    failure wasn't distinguished from "nothing new". DiscoverFailedError must produce a
    message distinct from both the success path and the generic Playwright-failure path.
    """
    from contextlib import contextmanager

    from app.api.routes import web
    from app.application.crawl import DiscoverFailedError

    @contextmanager
    def _fake_session():
        yield object()

    def _fake_run_crawl_cycle(session, adapter, limit=40):
        raise DiscoverFailedError("EXTERNAL_CHANGED")

    monkeypatch.setattr(web, "playwright_session", _fake_session)
    monkeypatch.setattr(web, "run_crawl_cycle", _fake_run_crawl_cycle)

    _login(client, db_session, "admin")
    resp = client.post("/orders/refresh")

    assert resp.status_code == 200
    assert "tìm đơn mới" in resp.text
    assert "kiểm tra Chrome profile" not in resp.text
    assert "Đã crawl xong" not in resp.text


def test_orders_refresh_recovers_from_a_mid_crawl_db_error(client, db_session, monkeypatch):
    """Regression test for a real production crash: a failed statement mid-crawl
    (e.g. an idempotency-key length overflow) aborts the session's transaction: any
    further query on that same session — including this route's own re-render of the
    order list right after — fails too unless rolled back first. Without db.rollback()
    in the except block, this whole request would raise instead of returning 200 with
    a graceful error message."""
    from contextlib import contextmanager

    from sqlalchemy import text

    from app.api.routes import web

    @contextmanager
    def _fake_session():
        yield object()

    def _fake_run_crawl_cycle(session, adapter, limit=40):
        session.execute(text("SELECT this_column_does_not_exist_anywhere"))

    monkeypatch.setattr(web, "playwright_session", _fake_session)
    monkeypatch.setattr(web, "run_crawl_cycle", _fake_run_crawl_cycle)

    _login(client, db_session, "admin")
    resp = client.post("/orders/refresh")

    assert resp.status_code == 200
    assert "Crawl thất bại" in resp.text


def test_order_detail_page_renders_product_fields(client, db_session):
    _login(client, db_session, "admin")
    order = Order(
        external_order_id="DJ_DETAIL_1",
        state=OrderState.CLAIMED_IMPORTED.value,
        product_name="Test Mug",
        sku="P999-XL",
        thumbnail_url="https://assets.printerval.com/thumb.webp",
        product_variants=[{"name": "Size", "value": "XL"}],
        custom_config={"original": [{"key": "Name", "value": "Alice"}], "translated_vn": []},
    )
    db_session.add(order)
    db_session.commit()

    resp = client.get(f"/orders/{order.id}")

    assert resp.status_code == 200
    assert "Test Mug" in resp.text
    assert "P999-XL" in resp.text
    assert "assets.printerval.com/thumb.webp" in resp.text
    assert "Alice" in resp.text


def test_orders_table_renders_thumbnail_and_sku(client, db_session):
    _login(client, db_session, "admin")
    order = Order(
        external_order_id="DJ_TABLE_1",
        state=OrderState.CLAIMED_IMPORTED.value,
        sku="P888-M",
        thumbnail_url="https://assets.printerval.com/other-thumb.webp",
    )
    db_session.add(order)
    db_session.commit()

    resp = client.get("/orders/table")

    assert resp.status_code == 200
    assert "P888-M" in resp.text
    assert "assets.printerval.com/other-thumb.webp" in resp.text

from datetime import UTC, datetime

from app.adapters.db.models import Assignment, Order
from app.api.deps import DEFAULT_PLATFORM_ID
from tests.test_orders_api import _login, _seed_platform, client  # noqa: F401


def _order(db, code, state, **kw):
    order = Order(external_order_id=code, platform_id=DEFAULT_PLATFORM_ID, state=state, **kw)
    db.add(order)
    db.flush()
    return order


def _seed(db_session):
    _seed_platform(db_session)
    _order(db_session, "W1", "WAITING")
    _order(db_session, "D1", "IN_PROGRESS", product_name="Red mug")
    _order(db_session, "D2", "IN_PROGRESS", template_missing=True)
    for i in range(5):
        _order(db_session, f"R{i}", "QC_PENDING", product_name=f"Shirt {i}")
    _order(db_session, "F1", "REVISION")
    _order(db_session, "F2", "REVISION", fix_approved_by_admin=True)
    _order(db_session, "X1", "DONE", created_at=datetime(2026, 10, 1, 20, 0, tzinfo=UTC))
    db_session.commit()


def test_page_returns_one_tab_with_counters_for_all_tabs(client, db_session):  # noqa: F811
    _seed(db_session)
    _login(client, db_session, "admin", "admin_page")

    body = client.get("/api/orders/page?tab=review&page_size=2").json()

    assert body["total"] == 5 and len(body["items"]) == 2
    assert {k: body["counts"][k] for k in ("waiting", "doing", "review", "fix", "done")} == {
        "waiting": 1, "doing": 2, "review": 5, "fix": 2, "done": 1,
    }
    assert body["counts"]["doing_missing"] == 1 and body["counts"]["fix_pending"] == 1
    second = client.get("/api/orders/page?tab=review&page_size=2&page=3").json()
    assert len(second["items"]) == 1


def test_page_filters_search_and_sub_tabs(client, db_session):  # noqa: F811
    _seed(db_session)
    _login(client, db_session, "admin", "admin_page_filters")

    mug = client.get("/api/orders/page?tab=doing&q=red").json()
    assert [o["external_order_id"] for o in mug["items"]] == ["D1"]
    assert mug["search_counts"]["doing"] == 1 and mug["search_counts"]["review"] == 0

    missing = client.get("/api/orders/page?tab=doing&doing_sub=missing").json()
    assert [o["external_order_id"] for o in missing["items"]] == ["D2"]
    pending = client.get("/api/orders/page?tab=fix&fix_sub=pending").json()
    assert [o["external_order_id"] for o in pending["items"]] == ["F1"]


def test_page_date_range_uses_vietnam_day_boundaries(client, db_session):  # noqa: F811
    _seed(db_session)
    _login(client, db_session, "admin", "admin_page_dates")

    # 2026-10-01 20:00 UTC is already 2026-10-02 in UTC+7.
    on_second = client.get("/api/orders/page?tab=done&date_field=created_at&date_from=2026-10-02&date_to=2026-10-02").json()
    on_first = client.get("/api/orders/page?tab=done&date_field=created_at&date_from=2026-10-01&date_to=2026-10-01").json()
    assert on_second["total"] == 1 and on_first["total"] == 0


def test_page_ids_only_and_designer_filter(client, db_session):  # noqa: F811
    _seed(db_session)
    admin = _login(client, db_session, "admin", "admin_page_ids")
    order = db_session.query(Order).filter_by(external_order_id="R0").one()
    db_session.add(Assignment(order_id=order.id, designer_id=admin.id, status="approved"))
    db_session.commit()

    ids = client.get("/api/orders/page?tab=review&ids_only=true").json()
    assert ids["total"] == 5 and len(ids["ids"]) == 5
    mine = client.get(f"/api/orders/page?tab=review&designer_id={admin.id}").json()
    assert [o["external_order_id"] for o in mine["items"]] == ["R0"]
    assert client.get("/api/orders/page?tab=review&designer_id=unassigned").json()["total"] == 4


def test_page_is_admin_only_and_validates_tab(client, db_session):  # noqa: F811
    _seed(db_session)
    _login(client, db_session, "designer", "designer_page")
    assert client.get("/api/orders/page?tab=review").status_code == 403
    _login(client, db_session, "admin", "admin_page_validate")
    assert client.get("/api/orders/page?tab=nope").status_code == 422


def test_platform_designers_lists_distinct_names(client, db_session):  # noqa: F811
    _seed_platform(db_session)
    _login(client, db_session, "admin", "admin_platform_designers")
    _order(db_session, "P1", "WAITING", printerval_designer="Beta")
    _order(db_session, "P2", "WAITING", printerval_designer="Alpha")
    _order(db_session, "P3", "DONE", printerval_designer="Alpha")
    _order(db_session, "P4", "DONE")
    db_session.commit()

    assert client.get("/api/orders/platform-designers").json() == {"designers": ["Alpha", "Beta"]}

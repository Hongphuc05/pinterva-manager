from datetime import UTC, datetime

from test_orders_api import _login, _seed_platform, client  # noqa: F401

from app.adapters.db.models import Assignment, Order
from app.api.deps import DEFAULT_PLATFORM_ID


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


def test_page_validates_tab_per_role_and_rejects_accountant(client, db_session):  # noqa: F811
    _seed(db_session)
    _login(client, db_session, "admin", "admin_page_validate")
    assert client.get("/api/orders/page?tab=nope").status_code == 422
    assert client.get("/api/orders/page?tab=paid").status_code == 422  # a designer tab
    _login(client, db_session, "accountant", "accountant_page")
    assert client.get("/api/orders/page?tab=review").status_code == 403


def test_designer_page_only_has_own_orders_and_cannot_search_by_code(client, db_session):  # noqa: F811
    _seed_platform(db_session)
    designer = _login(client, db_session, "designer", "designer_page_tabs")
    mine = [
        _order(db_session, "MINE-DOING", "IN_PROGRESS", product_name="Blue hoodie"),
        _order(db_session, "MINE-REVIEW", "QC_PENDING", product_name="Blue cap"),
        _order(db_session, "MINE-MISSING", "IN_PROGRESS", template_missing=True),
        _order(db_session, "MINE-PAID", "DONE", is_paid=True),
        _order(db_session, "MINE-FIX", "REVISION", fix_approved_by_admin=True),
    ]
    _order(db_session, "NOT-MINE", "IN_PROGRESS", product_name="Blue other")
    for order in mine:
        db_session.add(Assignment(order_id=order.id, designer_id=designer.id, status="approved"))
    db_session.commit()

    body = client.get("/api/orders/page").json()  # default tab = first designer tab (doing)
    assert body["total"] == 1 and body["items"][0]["product_name"] == "Blue hoodie"
    assert body["counts"] == {"doing": 1, "fix": 1, "review": 1, "waiting_update": 1, "paid": 1, "done": 0}

    assert client.get("/api/orders/page?tab=review&q=MINE-REVIEW").json()["total"] == 0  # code is private
    assert client.get("/api/orders/page?tab=review&q=cap").json()["total"] == 1
    assert client.get("/api/orders/page?tab=waiting").status_code == 422


def test_support_page_tabs_partition_visible_orders(client, db_session):  # noqa: F811
    _seed_platform(db_session)
    _login(client, db_session, "support", "support_page_tabs")
    _order(db_session, "S-UNCHECKED", "WAITING")
    _order(db_session, "S-DUP", "WAITING", duplicate_check_status="duplicate")
    _order(db_session, "S-NONDUP", "WAITING", duplicate_check_status="non_duplicate")
    _order(db_session, "S-DOING", "IN_PROGRESS")
    _order(db_session, "S-HIDDEN", "DONE")
    db_session.commit()

    body = client.get("/api/orders/page?tab=all").json()
    assert body["counts"] == {"all": 1, "duplicate": 1, "non_duplicate": 1, "doing": 1}
    assert [o["external_order_id"] for o in body["items"]] == ["S-UNCHECKED"]
    assert body["submitted_count"] == 1
    assert client.get("/api/orders/page?tab=review").status_code == 422


def test_platform_designers_lists_distinct_names(client, db_session):  # noqa: F811
    _seed_platform(db_session)
    _login(client, db_session, "admin", "admin_platform_designers")
    _order(db_session, "P1", "WAITING", printerval_designer="Beta")
    _order(db_session, "P2", "WAITING", printerval_designer="Alpha")
    _order(db_session, "P3", "DONE", printerval_designer="Alpha")
    _order(db_session, "P4", "DONE")
    db_session.commit()

    assert client.get("/api/orders/platform-designers").json() == {"designers": ["Alpha", "Beta"]}


def test_page_date_range_can_filter_by_tacahu_deadline(client, db_session):  # noqa: F811
    _seed_platform(db_session)
    _login(client, db_session, "admin", "admin_page_deadline")
    _order(db_session, "DL-IN", "WAITING", deadline_tacahu=datetime(2026, 10, 20, 3, 0, tzinfo=UTC))
    _order(db_session, "DL-OUT", "WAITING", deadline_tacahu=datetime(2026, 11, 5, 3, 0, tzinfo=UTC))
    _order(db_session, "DL-NONE", "WAITING")
    db_session.commit()

    body = client.get(
        "/api/orders/page?tab=waiting&date_field=deadline_tacahu&date_from=2026-10-20&date_to=2026-10-20"
    ).json()

    assert [o["external_order_id"] for o in body["items"]] == ["DL-IN"]


def test_designer_page_date_range_can_filter_by_tacahu_deadline(client, db_session):  # noqa: F811
    _seed_platform(db_session)
    designer = _login(client, db_session, "designer", "designer_page_deadline")
    in_range = _order(
        db_session,
        "DES-DL-IN",
        "IN_PROGRESS",
        product_name="Designer deadline in range",
        deadline_tacahu=datetime(2026, 10, 20, 3, 0, tzinfo=UTC),
    )
    _order(
        db_session,
        "DES-DL-OUT",
        "IN_PROGRESS",
        product_name="Designer deadline out of range",
        deadline_tacahu=datetime(2026, 11, 5, 3, 0, tzinfo=UTC),
    )
    db_session.add(Assignment(order_id=in_range.id, designer_id=designer.id, status="approved"))
    db_session.commit()

    body = client.get(
        "/api/orders/page?tab=doing&date_field=deadline_tacahu&date_from=2026-10-20&date_to=2026-10-20"
    ).json()

    assert [o["external_order_id"] for o in body["items"]] == ["DES-DL-IN"]
    assert body["items"][0]["deadline_tacahu"] == "2026-10-20T03:00:00Z"


def test_admin_filters_by_duplicate_check_tag(client, db_session):  # noqa: F811
    _seed_platform(db_session)
    _order(db_session, "WU1", "WAITING", duplicate_check_status="uncheck")
    _order(db_session, "WU2", "WAITING", duplicate_check_status="uncheck")
    _order(db_session, "WN1", "WAITING", duplicate_check_status="non_duplicate")
    db_session.commit()
    _login(client, db_session, "admin", "admin_check_filter")

    def codes(query):
        return {i["external_order_id"] for i in client.get(f"/api/orders/page?tab=waiting{query}").json()["items"]}

    assert codes("") == {"WU1", "WU2", "WN1"}
    assert codes("&check_status=unchecked") == {"WU1", "WU2"}
    assert codes("&check_status=checked") == {"WN1"}  # in Waiting, checked = Không trùng lặp
    ids = client.get("/api/orders/page?tab=waiting&check_status=checked&ids_only=true").json()["ids"]
    assert len(ids) == 1
    assert client.get("/api/orders/page?tab=waiting&check_status=bogus").status_code == 422


def test_an_order_whose_gallery_is_json_null_does_not_take_the_page_down(client, db_session):  # noqa: F811
    """DJ4171681: one crawled order stored JSON null as its gallery and every order tab returned 500."""
    from sqlalchemy import text

    _seed_platform(db_session)
    broken = _order(db_session, "W-NULL", "WAITING")
    synced = _order(db_session, "W-SYNC", "WAITING", product_image_urls=["a.jpg", "b.jpg"])
    empty = _order(db_session, "W-NONE", "WAITING", product_image_urls=None)
    db_session.commit()
    db_session.execute(text("UPDATE orders SET product_image_urls = 'null'::jsonb WHERE id = :id"), {"id": broken.id})
    db_session.commit()
    _login(client, db_session, "admin", "admin_page_json_null")

    body = client.get("/api/orders/page?tab=waiting").json()
    assert body["counts"]["waiting"] == 3 and body["aux"]["synced_images"] == 1
    only_synced = client.get("/api/orders/page?tab=waiting&synced_images=true").json()
    assert [o["external_order_id"] for o in only_synced["items"]] == [synced.external_order_id]
    # Python None is stored as SQL NULL from now on, never as JSON null.
    kind = db_session.execute(text("SELECT jsonb_typeof(product_image_urls) FROM orders WHERE id = :id"), {"id": empty.id})
    assert kind.scalar() is None

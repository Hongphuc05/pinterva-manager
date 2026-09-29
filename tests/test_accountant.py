from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.adapters.db.models import (
    Assignment,
    Order,
    PaymentBatch,
    Platform,
    User,
    UserBankQr,
    WorkflowEvent,
)
from app.application.auth import create_session_token, hash_password
from app.application.payments import backfill_payment_batches
from app.domain.models import OrderState

LINK = "https://drive.google.com/drive/folders/result"


@pytest.fixture
def world(db_session):
    platform = Platform(name="Acct plat", account_username="acct@example.com",
                        standard_order_rate=40000, duplicate_order_rate=15000)
    other = Platform(name="Acct other", account_username="acct-other@example.com")
    db_session.add_all([platform, other])
    db_session.flush()

    def user(username, role, plat=platform, **kw):
        u = User(username=username, full_name=username.title(), role=role,
                 password_hash=hash_password("pass"), platform_id=plat.id, **kw)
        db_session.add(u)
        return u

    admin = user("acct_admin", "admin")
    accountant = user("acct_kt", "accountant")
    dan = user("acct_dan", "designer", telegram_chat_id="1", telegram_notifications_enabled=True)
    tram = user("acct_tram", "designer")
    support = user("acct_support", "support")
    stranger = user("acct_stranger", "designer", plat=other)
    db_session.flush()

    def order(code, designer, *, link=True, paid=False, domain="standard", custom_rate=None, plat=platform):
        o = Order(external_order_id=code, platform_id=plat.id, state=OrderState.QC_PENDING.value,
                  note_outsource=LINK if link else None, is_paid=paid, work_domain=domain,
                  custom_rate=custom_rate, product_name=f"Prod {code}")
        db_session.add(o)
        db_session.flush()
        db_session.add(Assignment(order_id=o.id, designer_id=designer.id, status="approved"))
        return o

    orders = {
        "dan1": order("AC-DAN-1", dan),
        "dan2": order("AC-DAN-2", dan, domain="duplicate"),  # 15.000
        "dan3": order("AC-DAN-3", dan, custom_rate=55000),
        "dan_nolink": order("AC-DAN-NOLINK", dan, link=False),  # not credited yet: never payable
        "dan_paid": order("AC-DAN-PAID", dan, paid=True),
        "tram1": order("AC-TRAM-1", tram),
        "foreign": order("AC-FOREIGN", stranger, plat=other),
    }
    db_session.add(UserBankQr(user_id=dan.id, storage_key="acct/dan.png", original_filename="dan.png",
                              content_type="image/png", byte_size=10))
    db_session.commit()

    def hdr(u, plat=None):
        h = {"Authorization": f"Bearer {create_session_token(str(u.id), u.role)}"}
        if plat:
            h["X-Platform-Id"] = str(plat.id)
        return h

    return type("World", (), dict(
        platform=platform, other=other, admin=admin, accountant=accountant, dan=dan, tram=tram,
        support=support, stranger=stranger, orders=orders, hdr=hdr,
        admin_hdr=hdr(admin, platform), acct_hdr=hdr(accountant),
    ))


def test_accountant_is_denied_everything_but_the_payment_page(client, world):
    denied = [
        ("GET", "/api/orders"),
        ("GET", "/api/finance/stats"),
        ("GET", "/api/finance/rates"),
        ("POST", "/api/finance/mark-paid"),
        ("POST", "/api/finance/unmark-paid"),
        ("PUT", f"/api/finance/orders/{world.orders['dan1'].id}/rate"),
        ("GET", "/api/users"),
        ("GET", "/api/users/me/bank-qr"),
        ("GET", "/api/finance/notes"),
        ("GET", "/api/duplicate-board"),
        ("GET", "/api/my-tasks"),
        ("GET", "/api/support-worker/queue"),
        ("GET", "/api/telegram/status"),
    ]
    for method, url in denied:
        res = client.request(method, url, headers=world.acct_hdr, json={})
        assert res.status_code == 403, (method, url, res.status_code)

    for url in ("/api/me", "/api/platforms/current", "/api/accountant/designers", "/api/finance/payment-history",
                f"/api/users/{world.dan.id}/bank-qr"):
        assert client.get(url, headers=world.acct_hdr).status_code == 200, url


def test_pending_list_matches_admin_unpaid_and_hides_rates(client, world):
    res = client.get("/api/accountant/designers", headers=world.acct_hdr)
    assert res.status_code == 200
    rows = {r["designer_name"]: r for r in res.json()}
    assert set(rows) == {"Acct_Dan", "Acct_Tram"}  # the other platform's designer is not listed
    assert rows["Acct_Dan"]["pending_count"] == 3  # no-link and already-paid orders excluded
    assert rows["Acct_Dan"]["pending_amount"] == 40000 + 15000 + 55000
    assert rows["Acct_Dan"]["has_qr"] is True and rows["Acct_Tram"]["has_qr"] is False
    assert "rate" not in res.text and "custom_rate" not in res.text

    # Same numbers as the Admin finance page shows as "chưa thanh toán".
    stats = client.get("/api/finance/stats", headers=world.admin_hdr).json()
    admin_row = next(d for d in stats["designers_summary"] if d["designer_id"] == str(world.dan.id))
    assert admin_row["unpaid_tasks"] == 3 and admin_row["unpaid_amount"] == 110000

    detail = client.get(f"/api/accountant/designers/{world.dan.id}", headers=world.acct_hdr).json()
    assert {o["external_order_id"] for o in detail["orders"]} == {"AC-DAN-1", "AC-DAN-2", "AC-DAN-3"}
    assert detail["pending_amount"] == 110000
    assert all("amount" not in o and "rate" not in o for o in detail["orders"])


def _pay(client, world, designer, **override):
    detail = client.get(f"/api/accountant/designers/{designer.id}", headers=world.acct_hdr).json()
    body = {"order_ids": [o["order_id"] for o in detail["orders"]], "expected_total": detail["pending_amount"]}
    body.update(override)
    return client.post(f"/api/accountant/designers/{designer.id}/pay", headers=world.acct_hdr, json=body)


def test_accountant_pays_like_admin_and_it_is_recorded(client, db_session, world):
    with patch("app.workers.telegram_tasks.safe_dispatch_telegram_task") as dispatch:
        res = _pay(client, world, world.dan)
    assert res.status_code == 200
    assert res.json() == {"ok": True, "paid_count": 3, "total_amount": 110000}

    db_session.expire_all()
    for key in ("dan1", "dan2", "dan3"):
        o = db_session.get(Order, world.orders[key].id)
        assert o.is_paid and o.paid_by_id == world.accountant.id and o.state == OrderState.DONE.value
        event = db_session.query(WorkflowEvent).filter_by(order_id=o.id, to_state="DONE").one()
        assert event.actor_id == world.accountant.id and event.evidence["action"] == "mark_paid"
    assert not db_session.get(Order, world.orders["dan_nolink"].id).is_paid

    batch = db_session.query(PaymentBatch).one()
    assert (batch.paid_by_name, batch.paid_by_role, batch.designer_id) == ("Acct_Kt", "accountant", world.dan.id)
    assert (batch.order_count, batch.total_amount, batch.source) == (3, 110000, "payment")
    assert sorted(i["amount"] for i in batch.items) == [15000, 40000, 55000]

    dispatch.assert_called_once()
    assert dispatch.call_args.args[1:] == (str(world.dan.id), 3, 110000)

    # Dan is done: only Tram is still waiting.
    names = [r["designer_name"] for r in client.get("/api/accountant/designers", headers=world.acct_hdr).json()]
    assert names == ["Acct_Tram"]


def test_payment_refused_when_what_was_shown_changed(client, db_session, world):
    # Wrong total (e.g. Admin changed a rate after the popup opened).
    assert _pay(client, world, world.dan, expected_total=100000).status_code == 409
    # An order that is not this designer's.
    assert _pay(client, world, world.dan, order_ids=[str(world.orders["tram1"].id)], expected_total=40000).status_code == 409
    # An order paid by someone else meanwhile.
    shown = client.get(f"/api/accountant/designers/{world.dan.id}", headers=world.acct_hdr).json()
    world.orders["dan1"].is_paid = True
    db_session.commit()
    res = client.post(f"/api/accountant/designers/{world.dan.id}/pay", headers=world.acct_hdr,
                      json={"order_ids": [o["order_id"] for o in shown["orders"]], "expected_total": shown["pending_amount"]})
    assert res.status_code == 409

    db_session.expire_all()
    assert not db_session.get(Order, world.orders["dan2"].id).is_paid  # nothing was paid
    assert db_session.query(PaymentBatch).count() == 0


def test_order_arriving_after_the_popup_opened_waits_for_the_next_payment(client, db_session, world):
    shown = client.get(f"/api/accountant/designers/{world.dan.id}", headers=world.acct_hdr).json()
    late = Order(external_order_id="AC-DAN-LATE", platform_id=world.platform.id, state=OrderState.QC_PENDING.value,
                 note_outsource=LINK)
    db_session.add(late)
    db_session.flush()
    db_session.add(Assignment(order_id=late.id, designer_id=world.dan.id, status="approved"))
    db_session.commit()

    res = client.post(f"/api/accountant/designers/{world.dan.id}/pay", headers=world.acct_hdr,
                      json={"order_ids": [o["order_id"] for o in shown["orders"]], "expected_total": shown["pending_amount"]})
    assert res.status_code == 200 and res.json()["paid_count"] == 3
    rows = client.get("/api/accountant/designers", headers=world.acct_hdr).json()
    assert next(r for r in rows if r["designer_name"] == "Acct_Dan")["pending_count"] == 1


def test_designer_without_qr_can_still_be_paid(client, world):
    assert _pay(client, world, world.tram).status_code == 200


def test_admin_payment_is_recorded_and_never_twice(client, db_session, world):
    ids = [str(world.orders["dan1"].id), str(world.orders["tram1"].id)]
    assert client.post("/api/finance/mark-paid", headers=world.admin_hdr, json={"order_ids": ids}).json()["updated_count"] == 2
    batches = {b.designer_id: b for b in db_session.query(PaymentBatch).all()}
    assert set(batches) == {world.dan.id, world.tram.id}  # one row per designer
    assert batches[world.dan.id].paid_by_role == "admin" and batches[world.dan.id].total_amount == 40000

    # Paying the same orders again changes nothing and records nothing.
    assert client.post("/api/finance/mark-paid", headers=world.admin_hdr, json={"order_ids": ids}).json()["updated_count"] == 0
    assert db_session.query(PaymentBatch).count() == 2


def test_history_visible_to_admin_and_accountant_only(client, world):
    _pay(client, world, world.dan)
    admin_view = client.get("/api/finance/payment-history", headers=world.admin_hdr).json()
    acct_view = client.get("/api/finance/payment-history", headers=world.acct_hdr).json()
    assert admin_view["total"] == acct_view["total"] == 1
    batch = acct_view["batches"][0]
    assert (batch["paid_by_name"], batch["designer_name"], batch["order_count"], batch["total_amount"]) == (
        "Acct_Kt", "Acct_Dan", 3, 110000)
    assert all(i["amount"] is None for i in batch["items"])  # the Accountant never sees rates
    assert sorted(i["amount"] for i in admin_view["batches"][0]["items"]) == [15000, 40000, 55000]

    for u in (world.dan, world.support):
        assert client.get("/api/finance/payment-history", headers=world.hdr(u)).status_code == 403
    # History of another platform is not visible.
    other_admin = client.get("/api/finance/payment-history", headers=world.hdr(world.admin, world.other)).json()
    assert other_admin["total"] == 0


def test_accountant_sees_qr_of_own_platform_only(client, world):
    assert client.get(f"/api/users/{world.dan.id}/bank-qr", headers=world.acct_hdr).json()["images"]
    assert client.get(f"/api/users/{world.stranger.id}/bank-qr", headers=world.acct_hdr).status_code == 404


def test_admin_can_create_an_accountant(client, world):
    res = client.post("/api/users", headers=world.admin_hdr,
                      json={"username": "acct_new", "full_name": "Kế toán", "password": "secret1", "role": "accountant"})
    assert res.status_code in (200, 201), res.text
    assert res.json()["role"] == "accountant"


def test_backfill_rebuilds_one_row_per_payment_click_and_designer(db_session, world):
    click1 = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    click2 = click1 + timedelta(days=2)
    for key, when in (("dan1", click1), ("dan2", click1), ("tram1", click1), ("dan3", click2)):
        o = world.orders[key]
        o.is_paid, o.paid_at, o.paid_by_id = True, when, world.admin.id
    # The fixture's pre-paid order has no payer/time: still recorded, under "Không rõ".
    db_session.commit()

    created = backfill_payment_batches(db_session)
    batches = db_session.query(PaymentBatch).all()
    assert created == len(batches) == 4
    by = {(b.designer_id, b.paid_at): b for b in batches if b.paid_by_id}
    assert by[(world.dan.id, click1)].order_count == 2 and by[(world.dan.id, click1)].total_amount == 55000
    assert by[(world.tram.id, click1)].order_count == 1
    assert by[(world.dan.id, click2)].total_amount == 55000
    assert all(b.source == "backfill" for b in batches)
    assert {b.paid_by_name for b in batches} == {"Acct_Admin", "Không rõ"}

    assert backfill_payment_batches(db_session) == 0  # re-running adds nothing
    assert db_session.query(PaymentBatch).count() == 4

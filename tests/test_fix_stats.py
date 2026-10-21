"""Designer Fix statistics: who a Fix belongs to, which Fixes do not count, the period and access."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.adapters.db.models import (
    Assignment,
    ExternalObservation,
    Order,
    Platform,
    User,
    WorkflowEvent,
)
from app.application import fix_stats
from app.application.auth import create_session_token
from app.domain.models import OrderState

T0 = datetime(2026, 10, 13, 3, 0, tzinfo=UTC)  # Tuesday 13/10, 10:00 Vietnam


@pytest.fixture()
def world(db_session):
    platform = Platform(name="P fix", account_username="fix@print.com", is_active=True)
    other_platform = Platform(name="P other", account_username="other@print.com", is_active=True)
    db_session.add_all([platform, other_platform])
    db_session.flush()

    def user(role, name):
        u = User(username=f"{name}-{uuid.uuid4().hex[:4]}", full_name=name, role=role, password_hash="x",
                 active=True, platform_id=platform.id)
        db_session.add(u)
        return u

    a, b, admin = user("designer", "An"), user("designer-trello", "Bình"), user("admin", "Admin")
    db_session.flush()

    def order(code, plat=platform, assigned=None):
        o = Order(external_order_id=code, platform_id=plat.id, state=OrderState.QC_PENDING.value,
                  product_name=f"Áo {code}", duplicate_check_status="uncheck", work_domain="standard")
        db_session.add(o)
        db_session.flush()
        if assigned:
            db_session.add(Assignment(order_id=o.id, designer_id=assigned.id, status="approved"))
        return o

    def ev(o, minutes, from_state, to_state, actor=None, **evidence):
        db_session.add(WorkflowEvent(order_id=o.id, from_state=from_state, to_state=to_state,
                                     actor_id=actor.id if actor else None, evidence=evidence,
                                     created_at=T0 + timedelta(minutes=minutes)))

    def submit(o, minutes, who, from_state="IN_PROGRESS"):
        ev(o, minutes, from_state, "QC_PENDING", who, source="designer_result_submit")

    def fix(o, minutes):
        ev(o, minutes, "QC_PENDING", "REVISION", action="REQUEST_FIX")

    return type("W", (), {"session": db_session, "platform": platform, "other": other_platform, "a": a, "b": b,
                          "admin": admin, "order": staticmethod(order), "ev": staticmethod(ev),
                          "submit": staticmethod(submit), "fix": staticmethod(fix)})


def _row(rows, designer):
    return next(r for r in rows if r["designer_id"] == str(designer.id))


def test_rate_counts_orders_and_notes_an_order_fixed_three_times(world):
    w = world
    thrice = w.order("DJ1")
    w.submit(thrice, 0, w.a)
    for n in range(3):
        w.fix(thrice, 60 + n * 120)
        w.submit(thrice, 120 + n * 120, w.a, from_state="REVISION")
    for code in ("DJ2", "DJ3", "DJ4", "DJ5"):
        w.submit(w.order(code), 10, w.a)
    w.session.commit()

    row = _row(fix_stats.designer_fix_stats(w.session, w.platform.id), w.a)

    # 5 orders, 1 Fixed: 20%, and that one came back 3 times.
    assert (row["submitted_orders"], row["fixed_orders"], row["fix_rate"]) == (5, 1, 20.0)
    assert (row["fix_count"], row["max_fixes_per_order"], row["repeat_orders"]) == (3, 3, 1)
    assert row["distribution"] == {"1": 0, "2": 0, "3+": 1}


def test_fake_and_admin_rejected_fixes_are_listed_but_not_counted(world):
    w = world
    rejected = w.order("DJ10")
    w.submit(rejected, 0, w.a)
    w.fix(rejected, 60)
    w.ev(rejected, 70, "REVISION", "QC_PENDING", w.admin, action="REJECT_FIX_TO_REVIEW")

    bounced = w.order("DJ11")
    w.submit(bounced, 0, w.a)
    w.fix(bounced, 60)  # real
    w.submit(bounced, 180, w.a, from_state="REVISION")
    w.fix(bounced, 182)  # 2 minutes after the resubmission, before the 20/10 guard: the sync's echo
    w.session.commit()

    row = _row(fix_stats.designer_fix_stats(w.session, w.platform.id), w.a)
    assert (row["submitted_orders"], row["fixed_orders"], row["fix_count"]) == (2, 1, 1)
    assert row["excluded"] == {"fake": 1, "admin_rejected": 1}

    orders = fix_stats.designer_fixed_orders(w.session, w.platform.id, w.a.id)
    by_code = {o["external_order_id"]: o for o in orders}
    assert [f["excluded"] for f in by_code["DJ10"]["fixes"]] == ["admin_rejected"]
    assert [f["excluded"] for f in by_code["DJ11"]["fixes"]] == [None, "fake"]
    assert by_code["DJ11"]["fix_count"] == 1


def test_a_quick_refix_after_the_guard_counts(world, monkeypatch):
    w = world
    monkeypatch.setattr(fix_stats, "FAKE_FIX_GUARD_SINCE", T0)  # the sync no longer records echoes
    o = w.order("DJ12")
    w.submit(o, 0, w.a)
    w.fix(o, 60)
    w.submit(o, 180, w.a, from_state="REVISION")
    w.fix(o, 182)
    w.session.commit()
    assert _row(fix_stats.designer_fix_stats(w.session, w.platform.id), w.a)["fix_count"] == 2


def test_a_fix_belongs_to_whoever_made_the_submission_qc_answered(world):
    w = world
    on_behalf = w.order("DJ20", assigned=w.b)
    w.submit(on_behalf, 0, w.admin)  # Admin submits for the assigned Designer
    w.fix(on_behalf, 60)

    handed_over = w.order("DJ21")
    w.submit(handed_over, 0, w.a)
    w.submit(handed_over, 30, w.b, from_state="IN_PROGRESS")  # reassigned, B submits again
    w.fix(handed_over, 90)

    foreign = w.order("DJ22", plat=w.other)
    w.submit(foreign, 0, w.a)
    w.fix(foreign, 60)
    w.session.commit()

    rows = fix_stats.designer_fix_stats(w.session, w.platform.id)
    assert (_row(rows, w.b)["submitted_orders"], _row(rows, w.b)["fixed_orders"]) == (2, 2)
    assert (_row(rows, w.a)["submitted_orders"], _row(rows, w.a)["fixed_orders"]) == (1, 0)  # not the other platform


def test_the_period_is_the_first_submission_and_its_fixes_count_whenever_they_came(world):
    w = world
    inside = w.order("DJ30")
    w.submit(inside, 0, w.a)  # 13/10
    w.fix(inside, 60 * 24 * 3)  # 16/10, after the period
    w.submit(w.order("DJ31"), 60 * 24 * 7, w.a)  # 20/10, outside
    w.session.commit()

    rows = fix_stats.designer_fix_stats(w.session, w.platform.id, date(2026, 10, 12), date(2026, 10, 14))
    assert (_row(rows, w.a)["submitted_orders"], _row(rows, w.a)["fixed_orders"]) == (1, 1)


def test_each_fix_shows_qcs_reason_from_the_chat(world):
    w = world
    o = w.order("DJ40")
    w.submit(o, 0, w.a)
    w.fix(o, 60)
    w.session.add(ExternalObservation(order_id=o.id, source="printerval.chat", external_id="40", observed_state="fix",
                                      evidence={"last_message_id": 1, "messages": [{
                                          "id": 1, "fix_round": 1, "type": "fix_open", "mine": False,
                                          "fix_reason_label": "Lỗi làm khác mockup gốc", "content": "x",
                                          "sent_at": (T0 + timedelta(minutes=57)).isoformat()}]}))
    w.session.commit()
    [order] = fix_stats.designer_fixed_orders(w.session, w.platform.id, w.a.id)
    assert order["fixes"][0]["reason"] == "Lỗi làm khác mockup gốc"


def test_only_admins_see_it_scoped_to_their_platform(client, world):
    w = world
    o = w.order("DJ50")
    w.submit(o, 0, w.a)
    w.fix(o, 60)
    w.session.commit()

    def get(user, path):
        return client.get(path, headers={"Authorization": f"Bearer {create_session_token(str(user.id), user.role)}",
                                         "X-Platform-Id": str(w.platform.id)})

    summary = get(w.admin, "/api/designers/fix-stats?date_from=2026-10-01&date_to=2026-10-31")
    assert summary.status_code == 200
    body = summary.json()
    assert body["incomplete"] is False and body["repeat_threshold"] == 3
    assert _row(body["designers"], w.a)["fixed_orders"] == 1
    assert get(w.admin, "/api/designers/fix-stats").json()["incomplete"] is True  # no start: history before 21/09
    detail = get(w.admin, f"/api/designers/{w.a.id}/fix-stats").json()
    assert [x["external_order_id"] for x in detail["orders"]] == ["DJ50"]

    assert get(w.a, "/api/designers/fix-stats").status_code == 403
    assert get(w.admin, "/api/designers/fix-stats?date_from=2026-10-31&date_to=2026-10-01").status_code == 422


def test_a_designer_sees_only_their_own_rate_with_the_previous_period_to_compare(client, world):
    w = world
    w.a.platform_id = w.platform.id
    this_week = w.order("DJ60")
    w.submit(this_week, 60 * 24 * 7, w.a)  # 20/10
    w.fix(this_week, 60 * 24 * 7 + 60)
    w.submit(w.order("DJ61"), 60 * 24 * 7, w.a)
    last_week = w.order("DJ62")
    w.submit(last_week, 0, w.a)  # 13/10
    w.fix(last_week, 60)
    w.submit(w.order("DJ63"), 0, w.b)  # someone else's
    w.session.commit()

    def get(user, path, platform=None):
        headers = {"Authorization": f"Bearer {create_session_token(str(user.id), user.role)}"}
        if platform:
            headers["X-Platform-Id"] = str(platform.id)
        return client.get(path, headers=headers)

    # Another platform in the header changes nothing: a Designer's numbers come from their own platform.
    body = get(w.a, "/api/my/fix-stats?date_from=2026-10-19&date_to=2026-10-25", platform=w.other).json()
    assert (body["summary"]["submitted_orders"], body["summary"]["fixed_orders"], body["summary"]["fix_rate"]) == (2, 1, 50.0)
    assert (body["previous"]["submitted_orders"], body["previous"]["fixed_orders"]) == (1, 1)  # 12/10-18/10
    assert [o["product_name"] for o in body["orders"]] == ["Áo DJ60"]
    assert "external_order_id" not in body["orders"][0]  # no order code for Designers
    assert body["summary"]["designer_id"] == str(w.a.id) and "DJ63" not in str(body)

    assert get(w.admin, "/api/my/fix-stats").status_code == 403
    support = User(username=f"sup-{uuid.uuid4().hex[:4]}", full_name="S", role="support", password_hash="x",
                   active=True, platform_id=w.platform.id)
    w.session.add(support)
    w.session.commit()
    assert get(support, "/api/my/fix-stats").status_code == 403
    assert get(w.a, "/api/designers/fix-stats").status_code == 403  # nor anyone else's numbers

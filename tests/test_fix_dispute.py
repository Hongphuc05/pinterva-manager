""""Báo fix không đúng": the Admin disputes Printerval's Fix (web, Telegram), the worker sends it, the
status sync follows the arbitration, and an upheld dispute does not count in the Designer's Fix rate."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.adapters.db.models import (
    Assignment,
    DeadLetter,
    Order,
    Platform,
    TelegramActionLog,
    TelegramFixConversation,
    User,
    WorkflowEvent,
)
from app.application import fix_dispute
from app.application.auth import create_session_token, hash_password
from app.domain.models import OrderState

NOTE = "Đơn dạng 3D, trước giờ vẫn làm theo temp đang làm"


@pytest.fixture()
def world(db_session, monkeypatch):
    queued: list[str] = []
    monkeypatch.setattr(fix_dispute, "queue_send", lambda order: queued.append(str(order.id)))
    platform = Platform(name="Dispute plat", account_username="dispute@example.com",
                        account_password="pw", team_outsource="2D")
    db_session.add(platform)
    db_session.flush()
    admin = User(username="dispute-admin", full_name="Admin D", role="admin", password_hash=hash_password("p"),
                 telegram_chat_id="555", active=True)
    designer = User(username="dispute-des", full_name="Des D", role="designer", password_hash=hash_password("p"),
                    platform_id=platform.id, active=True)
    db_session.add_all([admin, designer])
    db_session.flush()
    order = Order(external_order_id="DJ4172042", platform_id=platform.id, state=OrderState.REVISION.value,
                  fix_return_count=1, printerval_status="fix", designer_note="old note")
    db_session.add(order)
    db_session.flush()
    db_session.add(Assignment(order_id=order.id, designer_id=designer.id, status="approved"))
    db_session.commit()

    def hdr(user):
        return {"Authorization": f"Bearer {create_session_token(str(user.id), user.role)}",
                "X-Platform-Id": str(platform.id)}

    return type("W", (), dict(platform=platform, admin=admin, designer=designer, order=order, hdr=hdr, queued=queued))


# ----------------------------------------------------------------------------- input rules


def test_input_follows_printervals_own_checks():
    assert fix_dispute.clean_input(f"  {NOTE}  ", ["https://a.png", " "]) == (NOTE, ["https://a.png"])
    for note, images, message in [
        ("ngắn", [], "ít nhất 10"),
        ("x" * 1001, [], "tối đa 1000"),
        (NOTE, [f"https://{i}.png" for i in range(6)], "Tối đa 5"),
        (NOTE, ["ftp://a.png"], "http://"),
    ]:
        with pytest.raises(fix_dispute.FixDisputeError, match=message):
            fix_dispute.clean_input(note, images)


def test_telegram_reply_template_is_split_into_reason_and_links():
    text = f"LÝ DO: {NOTE}\nvẫn đúng mockup\nẢNH:\nhttps://img.test/1.png\nhttps://img.test/2.png"
    assert fix_dispute.parse_reply(text) == (f"{NOTE}\nvẫn đúng mockup", ["https://img.test/1.png", "https://img.test/2.png"])
    # Without the headings it still works: link-only lines are images.
    assert fix_dispute.parse_reply(f"{NOTE}\nhttps://img.test/1.png") == (NOTE, ["https://img.test/1.png"])


# ----------------------------------------------------------------------------- web command


def test_admin_disputes_a_fix_and_it_is_queued_once(client, db_session, world):
    url = f"/api/orders/{world.order.id}/fix-dispute"
    res = client.post(url, json={"note": NOTE, "images": ["https://img.test/1.png"]}, headers=world.hdr(world.admin))

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["fix_dispute"]["push"] == "queued" and body["fix_dispute"]["round"] == 1
    assert body["fix_dispute_blocked"] == "Đã gửi khiếu nại lượt Fix này."
    assert world.queued == [str(world.order.id)]
    db_session.refresh(world.order)
    assert world.order.state == OrderState.REVISION.value  # Review only once Printerval says so
    assert world.order.fix_rejected_by_admin is True
    events = [e.evidence["action"] for e in db_session.query(WorkflowEvent).filter_by(order_id=world.order.id)]
    assert "FIX_DISPUTE_SUBMITTED" in events

    again = client.post(url, json={"note": NOTE, "images": []}, headers=world.hdr(world.admin))
    assert again.status_code == 400 and "Đã gửi khiếu nại" in again.json()["detail"]


def test_dispute_is_admin_only_validated_and_needs_an_open_fix(client, db_session, world):
    url = f"/api/orders/{world.order.id}/fix-dispute"
    assert client.post(url, json={"note": NOTE}, headers=world.hdr(world.designer)).status_code == 403
    assert client.post(url, json={"note": "ngắn"}, headers=world.hdr(world.admin)).status_code == 400
    world.order.fix_approved_by_admin = True
    db_session.commit()
    res = client.post(url, json={"note": NOTE}, headers=world.hdr(world.admin))
    assert res.status_code == 400 and "đã được duyệt" in res.json()["detail"]


def test_the_designer_never_sees_the_dispute(client, db_session, world):
    client.post(f"/api/orders/{world.order.id}/fix-dispute", json={"note": NOTE}, headers=world.hdr(world.admin))
    world.order.state = OrderState.QC_PENDING.value  # back in Review, visible to the Designer again
    db_session.commit()
    rows = client.get("/api/orders/page?tab=review", headers=world.hdr(world.designer)).json()["items"]
    assert rows and "fix_dispute" not in rows[0]
    admin_rows = client.get("/api/orders/page?tab=review", headers=world.hdr(world.admin)).json()["items"]
    assert admin_rows[0]["fix_dispute"]["note"] == NOTE


# ----------------------------------------------------------------------------- worker


class FakeClient:
    def __init__(self, rows, *, refuse=None):
        self.rows = list(rows)
        self.sent: list[tuple] = []
        self.refuse = refuse

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def find_order(self, code, statuses=()):
        return self.rows.pop(0) if len(self.rows) > 1 else self.rows[0]

    def submit_fix_dispute(self, job_id, note, images):
        if self.refuse:
            raise self.refuse
        self.sent.append((job_id, note, images))


def _run_task(db_session, order, fake):
    from app.workers import assignment_sync_tasks

    with patch.object(assignment_sync_tasks, "PrintervalApiClient", lambda **_: fake), \
            patch.object(assignment_sync_tasks, "SessionLocal", lambda: db_session), \
            patch.object(db_session, "close", lambda: None):
        assignment_sync_tasks.send_fix_dispute_task.run(str(order.id))
    db_session.refresh(order)


def _submit(db_session, world):
    fix_dispute.submit(db_session, world.order, admin=world.admin, note=NOTE, images=["https://img.test/1.png"], source="web")
    db_session.commit()


PENDING = {"kind": "team", "round": 1, "status": "pending", "note": NOTE, "at": "2026-10-21 23:08:44",
           "arbiter_at": "", "arbiter_note": ""}


def test_worker_sends_the_dispute_and_follows_printerval_to_review(db_session, world):
    _submit(db_session, world)
    fake = FakeClient([
        {"id": 4172042, "status": "fix", "outsource_fix_dispute": None, "outsource_fix_dispute_can": True},
        {"id": 4172042, "status": "review", "outsource_fix_dispute": PENDING, "outsource_fix_dispute_can": False},
    ])

    _run_task(db_session, world.order, fake)

    assert fake.sent == [(4172042, NOTE, ["https://img.test/1.png"])]
    assert world.order.state == OrderState.QC_PENDING.value
    assert world.order.designer_note == ""
    assert world.order.fix_dispute["push"] == "sent"
    assert world.order.fix_dispute["remote_status"] == "pending"


def test_worker_never_sends_twice_when_printerval_already_has_it(db_session, world):
    _submit(db_session, world)
    fake = FakeClient([{"id": 4172042, "status": "review", "outsource_fix_dispute": PENDING, "outsource_fix_dispute_can": False}])

    _run_task(db_session, world.order, fake)

    assert fake.sent == []
    assert world.order.fix_dispute["push"] == "sent"
    assert world.order.state == OrderState.QC_PENDING.value


def test_a_refused_dispute_is_marked_failed_toasted_and_can_be_sent_again(client, db_session, world):
    from app.adapters.errors import ErrorClass
    from app.adapters.printerval.api_client import PrintervalApiError

    _submit(db_session, world)
    refusal = PrintervalApiError(ErrorClass.PERMANENT_EXTERNAL, "Printerval không nhận khiếu nại Fix (HTTP 422)")
    fake = FakeClient([{"id": 4172042, "status": "fix", "outsource_fix_dispute": None, "outsource_fix_dispute_can": True}],
                      refuse=refusal)

    _run_task(db_session, world.order, fake)

    assert world.order.fix_dispute["push"] == "failed"
    assert "422" in world.order.fix_dispute["push_error"]
    assert world.order.state == OrderState.REVISION.value
    assert db_session.query(DeadLetter).count() == 1
    res = client.post(f"/api/orders/{world.order.id}/fix-dispute/retry", json={}, headers=world.hdr(world.admin))
    assert res.status_code == 200 and res.json()["fix_dispute"]["push"] == "queued"


# ----------------------------------------------------------------------------- arbitration


def test_a_rejected_dispute_reopens_the_same_fix_without_counting_it_twice(db_session, world):
    _submit(db_session, world)
    fix_dispute.mark_sent(world.order)
    fix_dispute.observe(db_session, world.order, status="review", dispute=PENDING, can=False)
    assert world.order.state == OrderState.QC_PENDING.value

    rejected = {**PENDING, "status": "rejected", "arbiter_note": "FIX đúng, sai màu logo"}
    changed, back_in_fix = fix_dispute.observe(db_session, world.order, status="fix", dispute=rejected, can=False)

    assert changed and back_in_fix
    assert world.order.state == OrderState.REVISION.value
    assert world.order.fix_return_count == 1
    assert world.order.fix_dispute["outcome"] == "rejected"
    assert fix_dispute.blocked_reason(world.order) == "Khiếu nại lượt Fix này đã bị bác."
    assert fix_dispute.observe(db_session, world.order, status="fix", dispute=rejected, can=False) == (False, False)


def test_the_status_sync_moves_a_rejected_dispute_back_to_fix_and_tells_admins(db_session, world, monkeypatch):
    from app.application import status_sync

    _submit(db_session, world)
    fix_dispute.mark_sent(world.order)
    fix_dispute.observe(db_session, world.order, status="review", dispute=PENDING, can=False)
    world.order.status_changed_at = datetime.now(UTC) - timedelta(minutes=2)  # inside the 30-minute guard
    db_session.commit()
    notified: list[str] = []
    monkeypatch.setattr(status_sync, "_dispatch_admin_fix_notifications", lambda s, o: notified.append(o.external_order_id))
    rejected = {**PENDING, "status": "rejected", "arbiter_note": "FIX đúng"}
    row = {"id": 4172042, "status": "fix", "outsource_fix_dispute": rejected, "outsource_fix_dispute_can": False}

    status_sync.sync_selected_order_statuses(
        db_session, world.platform, [world.order], api_client=type("C", (), {"get_designer_map": lambda self: {}})(),
        prefetched_rows={"4172042": row},
    )

    db_session.refresh(world.order)
    assert world.order.state == OrderState.REVISION.value
    assert world.order.fix_return_count == 1
    assert notified == ["DJ4172042"]


def test_an_upheld_dispute_does_not_count_in_the_designers_fix_rate(db_session, world):
    from app.application.fix_stats import designer_fix_stats

    order = world.order
    t0 = datetime(2026, 10, 21, 3, 0, tzinfo=UTC)

    def ev(minutes, frm, to, actor, action):
        db_session.add(WorkflowEvent(order_id=order.id, from_state=frm, to_state=to, actor_id=actor,
                                     evidence={"action": action}, created_at=t0 + timedelta(minutes=minutes)))

    ev(0, "IN_PROGRESS", "QC_PENDING", world.designer.id, "SUBMIT_REVIEW")
    ev(10, "QC_PENDING", "REVISION", None, "REQUEST_FIX")
    ev(20, "REVISION", "QC_PENDING", world.admin.id, "FIX_DISPUTE_TO_REVIEW")
    ev(30, "QC_PENDING", "QC_PENDING", None, "FIX_DISPUTE_ACCEPTED")
    db_session.commit()

    stats = designer_fix_stats(db_session, world.platform.id, date_from=None, date_to=None)
    row = next(r for r in stats if r["designer_id"] == str(world.designer.id))
    assert row["fix_count"] == 0
    assert row["excluded"]["dispute_accepted"] == 1


# ----------------------------------------------------------------------------- Telegram


def test_telegram_asks_for_the_template_previews_and_sends_on_confirm(client, db_session, world):
    db_session.add_all([
        TelegramActionLog(order_id=world.order.id, action_type="REJECT_FIX", callback_token="rej-1", payload={},
                          expires_at=datetime.now(UTC) + timedelta(hours=1)),
        TelegramFixConversation(order_id=world.order.id, chat_id="555", root_message_id=100, transient_message_ids=[]),
    ])
    db_session.commit()
    sent: list[dict] = []

    def fake_send(chat_id, text, reply_markup=None, **_):
        sent.append({"text": text, "markup": reply_markup})
        return {"message_id": 200 + len(sent)}

    with patch("app.api.routes.telegram_api.send_message", fake_send), \
            patch("app.api.routes.telegram_api.delete_messages", return_value=True):
        client.post("/api/telegram/webhook", json={"callback_query": {"data": "rejfix:rej-1", "from": {"id": 555}}})
        assert "LÝ DO:" in sent[-1]["text"] and sent[-1]["markup"]["force_reply"] is True

        # A reply that breaks the rules is explained and the bot keeps waiting.
        client.post("/api/telegram/webhook", json={"message": {
            "chat": {"id": 555}, "text": "LÝ DO: ngắn", "message_id": 300, "reply_to_message": {"message_id": 201}}})
        assert "ít nhất 10" in sent[-1]["text"]

        client.post("/api/telegram/webhook", json={"message": {
            "chat": {"id": 555}, "text": f"LÝ DO: {NOTE}\nẢNH:\nhttps://img.test/1.png", "message_id": 301,
            "reply_to_message": {"message_id": 201}}})
        preview = sent[-1]
        assert NOTE in preview["text"] and "https://img.test/1.png" in preview["text"]
        send_button = preview["markup"]["inline_keyboard"][0][0]["callback_data"]
        assert send_button.startswith("dispsend:")
        assert world.queued == []  # nothing goes to Printerval before the confirmation

        client.post("/api/telegram/webhook", json={"callback_query": {"data": send_button, "from": {"id": 555}}})

    db_session.refresh(world.order)
    assert world.order.fix_dispute["note"] == NOTE and world.order.fix_dispute["source"] == "telegram"
    assert world.queued == [str(world.order.id)]
    assert db_session.query(TelegramFixConversation).one().status == "cleaned"

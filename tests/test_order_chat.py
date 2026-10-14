from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.db.models import (
    Assignment,
    Order,
    OrderChatMessage,
    OrderChatRead,
    Platform,
    User,
)
from app.application import order_chat as chat
from app.application.auth import create_session_token, hash_password


class FakeChatClient:
    def __init__(self, chats: dict[int, list[dict]], unread_ids=(), fail_for=()):
        self.chats = chats
        self.unread_ids = list(unread_ids)
        self.fail_for = set(fail_for)
        self.calls: list[tuple[int, int]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def login(self):
        return None

    def fetch_chat_unread(self, ids):
        return {"job_ids": self.unread_ids, "unread": {}}

    def fetch_chat_messages(self, job_id, after_id=0):
        self.calls.append((job_id, after_id))
        if job_id in self.fail_for:
            raise RuntimeError("Printerval down")
        all_messages = self.chats.get(job_id, [])
        newest = max((m["id"] for m in all_messages), default=0)
        return {
            "messages": [m for m in all_messages if m["id"] > after_id],
            "chat": {"last_message_id": newest},
        }


def _vn(minutes_ago: int) -> str:
    moment = datetime.now(chat.PRINTERVAL_TZ) - timedelta(minutes=minutes_ago)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _msg(mid: int, *, minutes_ago: int = 1, mine: bool = False, content: str = "hi", **extra) -> dict:
    return {
        "id": mid, "design_job_id": 0, "fix_round": 1, "type": extra.pop("type", "fix_open"),
        "sender_type": "outsource" if mine else "staff", "sender_name": "QC Người", "content": content,
        "image_urls": extra.pop("image_urls", []), "fix_reason_label": "", "created_at": _vn(minutes_ago),
        "mine": mine, **extra,
    }


@pytest.fixture()
def world(db_session):
    platform = Platform(name="Chat Plat", account_username="chat@print.com", team_outsource="team", is_active=True)
    other = Platform(name="Other Plat", account_username="other@print.com", team_outsource="t2", is_active=True)
    db_session.add_all([platform, other])
    db_session.flush()

    def user(name: str, role: str, plat: Platform | None) -> User:
        u = User(
            username=f"{name}-{uuid.uuid4().hex[:6]}", full_name=name, role=role,
            password_hash=hash_password("pass"), active=True, platform_id=plat.id if plat else None,
        )
        db_session.add(u)
        db_session.flush()
        return u

    admin = user("admin", "admin", platform)
    des_a = user("des-a", "designer", platform)
    des_b = user("des-b", "designer", platform)
    support = user("support", "support", platform)
    other_admin = user("other-admin", "admin", other)

    def order(code: str, state="IN_PROGRESS", plat=platform, designer: User | None = None) -> Order:
        o = Order(
            external_order_id=code, platform_id=plat.id, state=state,
            duplicate_check_status="uncheck", work_domain="standard",
        )
        db_session.add(o)
        db_session.flush()
        if designer:
            db_session.add(Assignment(order_id=o.id, designer_id=designer.id, status="approved"))
        return o

    o1 = order("DJ4100001", designer=des_a)
    o2 = order("DJ4100002", designer=des_b)
    db_session.commit()
    return type("W", (), dict(
        platform=platform, other=other, admin=admin, des_a=des_a, des_b=des_b, support=support,
        other_admin=other_admin, o1=o1, o2=o2, order=order, session=db_session,
    ))


def _sync(world, client, order):
    return chat.sync_order_chat(world.session, client, order)


def _bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_session_token(str(user.id), user.role)}"}


def test_sync_stores_messages_once_and_moves_the_cursor(world):
    client = FakeChatClient({4100001: [_msg(10), _msg(11, mine=True, content="ok", image_urls=["https://img/x.png", "javascript:x"])]})

    assert _sync(world, client, world.o1) == 2
    assert _sync(world, client, world.o1) == 0  # nothing new, nothing duplicated

    world.session.refresh(world.o1)
    assert world.o1.chat_last_message_id == 11 and world.o1.chat_synced_at is not None
    assert client.calls == [(4100001, 0), (4100001, 11)]
    rows = world.session.query(OrderChatMessage).filter_by(order_id=world.o1.id).order_by(OrderChatMessage.external_id).all()
    assert [r.external_id for r in rows] == [10, 11]
    assert rows[1].mine is True and rows[1].image_urls == ["https://img/x.png"]  # only http(s) links
    assert rows[0].sent_at.tzinfo is not None


def test_a_sweep_takes_unread_jobs_and_a_rotating_slice_and_survives_one_failure(world):
    o3 = world.order("DJ4100003")
    o4 = world.order("DJ4100004")
    world.session.commit()
    chats = {4100001: [_msg(1)], 4100002: [_msg(2)], 4100003: [_msg(3)], 4100004: [_msg(4)]}
    client = FakeChatClient(chats, unread_ids=[4100004], fail_for=[4100002])

    stats = chat.sync_platform_chats(world.session, world.platform, rotation=2, client_factory=lambda _p: client)

    fetched = {job for job, _ in client.calls}
    assert 4100004 in fetched  # unread job is always taken
    assert len(fetched) == 3  # unread + 2 from the rotation
    assert stats["errors"] == (1 if 4100002 in fetched else 0)
    assert stats["orders"] + stats["errors"] == 3
    assert o3 and o4


def test_history_is_baseline_and_only_recent_messages_are_unread(world):
    client = FakeChatClient({4100001: [_msg(20, minutes_ago=600), _msg(21, minutes_ago=60), _msg(22, minutes_ago=1)]})
    _sync(world, client, world.o1)

    items = chat.unread_for_user(world.session, world.admin, world.platform.id)
    assert [(i["order_code"], i["count"], i["latest_id"]) for i in items] == [("DJ4100001", 1, 22)]
    assert items[0]["snippet"] == "hi" and items[0]["sender_name"] == "QC Người"


def test_unread_is_admin_only_platform_scoped_and_ignores_own_messages(world):
    client = FakeChatClient({
        4100001: [_msg(30), _msg(31, mine=True, content="mine")],
        4100002: [_msg(40)],
    })
    _sync(world, client, world.o1)
    _sync(world, client, world.o2)
    plat = world.platform.id

    assert {i["order_code"] for i in chat.unread_for_user(world.session, world.admin, plat)} == {"DJ4100001", "DJ4100002"}
    assert chat.unread_for_user(world.session, world.des_a, plat) == []  # designers never see the chat
    assert chat.unread_for_user(world.session, world.support, plat) == []
    assert chat.unread_for_user(world.session, world.other_admin, world.other.id) == []

    chat.mark_read(world.session, world.o1, world.admin)
    assert [i["order_code"] for i in chat.unread_for_user(world.session, world.admin, plat)] == ["DJ4100002"]


def test_purge_removes_the_chat_of_orders_closed_long_ago_only(world):
    old = world.order("DJ4100005", state="DONE")
    recent = world.order("DJ4100006", state="DONE")
    active = world.order("DJ4100007")
    old.status_changed_at = datetime.now(UTC) - timedelta(days=40)
    recent.status_changed_at = datetime.now(UTC) - timedelta(days=5)
    world.session.commit()
    client = FakeChatClient({4100005: [_msg(50)], 4100006: [_msg(51)], 4100007: [_msg(52)]})
    for o in (old, recent, active):
        _sync(world, client, o)
    chat.mark_read(world.session, old, world.admin)

    assert chat.purge_closed_chats(world.session, retention_days=30) == 1

    left = {r.order_id for r in world.session.query(OrderChatMessage).all()}
    assert old.id not in left and {recent.id, active.id} <= left
    assert world.session.query(OrderChatRead).filter_by(order_id=old.id).count() == 0
    world.session.refresh(old)
    assert old.chat_last_message_id is None and old.chat_synced_at is None


def test_chat_api_is_admin_only_with_a_read_marker(client, world, monkeypatch):
    chat_client = FakeChatClient({4100001: [_msg(60)]})
    monkeypatch.setattr(chat, "printerval_client_for", lambda _p: chat_client)
    _sync(world, chat_client, world.o1)
    path = f"/api/orders/{world.o1.id}/chat"

    body = client.get(path, headers=_bearer(world.admin)).json()
    assert [m["id"] for m in body["messages"]] == [60] and body["last_read_external_id"] == 0
    for outsider in (world.des_a, world.des_b, world.support):  # even the assigned designer
        assert client.get(path, headers=_bearer(outsider)).status_code in (403, 404)
        assert client.post(f"{path}/read", headers=_bearer(outsider)).status_code in (403, 404)
        assert client.get("/api/chat/unread", headers=_bearer(outsider)).json()["items"] == []
    assert client.get(path, headers=_bearer(world.other_admin)).status_code == 404  # other platform

    unread = client.get("/api/chat/unread", headers=_bearer(world.admin)).json()["items"]
    assert [i["order_code"] for i in unread] == ["DJ4100001"]
    assert client.post(f"{path}/read", headers=_bearer(world.admin)).json() == {"last_read_external_id": 60}
    assert client.get("/api/chat/unread", headers=_bearer(world.admin)).json()["items"] == []

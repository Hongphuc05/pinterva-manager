from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.adapters.db.models import Order, Platform, TelegramActionLog, User
from app.application.auth import create_session_token, hash_password
from app.application.telegram_service import (
    notify_designer_new_order,
    notify_designer_payment,
    notify_designer_urgent_fix,
)
from app.domain.models import OrderState


def test_telegram_status_and_link_code(client: TestClient, db_session):
    user = User(
        username="des_tg_test",
        full_name="Designer Telegram Test",
        role="designer",
        password_hash=hash_password("pass"),
        active=True,
    )
    db_session.add(user)
    db_session.commit()

    token = create_session_token(str(user.id), user.role)

    # 1. Get status initially
    resp = client.get(
        "/api/telegram/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_linked"] is False
    assert data["telegram_chat_id"] is None

    # 2. Generate link code
    resp_code = client.post(
        "/api/telegram/link-code",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_code.status_code == 200
    code_data = resp_code.json()
    assert code_data["ok"] is True
    assert len(code_data["code"]) > 10

    # 3. Simulate Telegram webhook /start <code>
    with patch("app.application.telegram_service.send_telegram_request") as mock_send:
        mock_send.return_value = {"ok": True}
        resp_hook = client.post(
            "/api/telegram/webhook",
            json={
                "message": {
                    "chat": {"id": 987654321},
                    "text": f"/start {code_data['code']}",
                    "from": {"username": "des_telegram_nick"},
                }
            },
        )
        assert resp_hook.status_code == 200
        assert mock_send.called

    # 4. Check user is now linked
    db_session.refresh(user)
    assert user.telegram_chat_id == "987654321"
    assert user.telegram_username == "des_telegram_nick"

    # 5. Get status again
    resp2 = client.get(
        "/api/telegram/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.json()["is_linked"] is True
    assert resp2.json()["telegram_chat_id"] == "987654321"

    # 6. Unlink
    resp_unlink = client.post(
        "/api/telegram/unlink",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_unlink.status_code == 200
    db_session.refresh(user)
    assert user.telegram_chat_id is None


def test_telegram_admin_fix_callbacks(client: TestClient, db_session):
    platform = Platform(name="Plat TG", account_username="admin_tg@print.com", is_active=True)
    db_session.add(platform)
    db_session.flush()

    admin = User(
        username="admin_tg",
        full_name="Admin Telegram",
        role="admin",
        password_hash=hash_password("pass"),
        telegram_chat_id="111222333",
        active=True,
    )
    db_session.add(admin)
    db_session.flush()

    order = Order(
        external_order_id="DJ-TG-991",
        state=OrderState.REVISION.value,
        product_name="Mug Ceramic",
        platform_id=platform.id,
        fix_approved_by_admin=False,
    )
    db_session.add(order)
    db_session.flush()

    action_log = TelegramActionLog(
        order_id=order.id,
        action_type="APPROVE_FIX",
        callback_token="app_test_token_123",
        payload={"order_id": str(order.id)},
    )
    db_session.add(action_log)
    db_session.commit()

    # 1. Admin clicks Accept Fix button on Telegram
    with patch("app.application.telegram_service.send_telegram_request") as mock_send:
        mock_send.return_value = {"ok": True}
        resp = client.post(
            "/api/telegram/webhook",
            json={
                "callback_query": {
                    "id": "cb1",
                    "data": "appfix:app_test_token_123",
                    "from": {"id": 111222333},
                }
            },
        )
        assert resp.status_code == 200

    db_session.refresh(order)
    assert order.fix_approved_by_admin is True
    assert order.state == OrderState.REVISION.value
    db_session.refresh(action_log)
    assert action_log.status == "executed"


def test_telegram_notification_formatters(db_session):
    user = User(
        username="des_fmt",
        full_name="Nguyen Van Fmt",
        role="designer",
        password_hash=hash_password("pass"),
        telegram_chat_id="555666777",
        telegram_notifications_enabled=True,
        active=True,
    )
    db_session.add(user)
    db_session.flush()

    order = Order(
        external_order_id="DJ-FMT-111",
        state=OrderState.IN_PROGRESS.value,
        product_name="Custom Hoodie",
        thumbnail_url="https://example.com/thumb.jpg",
        designer_note="Front print only",
    )
    db_session.add(order)
    db_session.commit()

    with patch("app.application.telegram_service.send_telegram_request") as mock_send:
        mock_send.return_value = {"ok": True}

        # New order
        res1 = notify_designer_new_order(db_session, order.id, user.id)
        assert res1 is True
        assert mock_send.called

        # Urgent fix
        res2 = notify_designer_urgent_fix(db_session, order.id, user.id, "Please fix font size")
        assert res2 is True

        # Payment
        res3 = notify_designer_payment(db_session, user.id, 10, 400000)
        assert res3 is True

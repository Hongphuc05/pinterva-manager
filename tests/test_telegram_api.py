from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.adapters.db.models import Assignment, Order, Platform, TelegramActionLog, User
from app.application.auth import create_session_token, hash_password
from app.application.telegram_service import (
    notify_admin_new_fix,
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
    # The first click now asks Admin which note should be released; it must not
    # dispatch the Fix before that explicit choice.
    assert order.fix_approved_by_admin is False
    assert order.state == OrderState.REVISION.value
    db_session.refresh(action_log)
    assert action_log.status == "executed"

    source_action = (
        db_session.query(TelegramActionLog)
        .filter(TelegramActionLog.action_type == "APPROVE_FIX_USE_OUTSOURCE")
        .one()
    )
    order.note_outsource = "Sửa lại màu áo theo QC"
    db_session.commit()

    with patch("app.application.telegram_service.send_telegram_request") as mock_send:
        mock_send.return_value = {"ok": True}
        resp = client.post(
            "/api/telegram/webhook",
            json={
                "callback_query": {
                    "id": "cb2",
                    "data": f"appfixsource:{source_action.callback_token}",
                    "from": {"id": 111222333},
                }
            },
        )
        assert resp.status_code == 200

    db_session.refresh(order)
    assert order.fix_approved_by_admin is True
    assert order.designer_note == "Sửa lại màu áo theo QC"
    assert order.designer_note_released_for_fix is True
    sibling_write_choice = db_session.query(TelegramActionLog).filter(
        TelegramActionLog.action_type == "APPROVE_FIX_WRITE_NOTE"
    ).one()
    assert sibling_write_choice.status == "superseded"


def test_telegram_admin_fix_notification_uses_tacahu_designer_name(db_session):
    platform = Platform(name="Plat designer name", account_username="admin@print.com", is_active=True)
    admin = User(
        username="admin-for-fix-notice", full_name="Admin", role="admin",
        password_hash=hash_password("pass"), telegram_chat_id="111", active=True,
    )
    designer = User(
        username="tacahu-designer", full_name="Tên Designer Tacahu", role="designer",
        password_hash=hash_password("pass"), active=True,
    )
    order = Order(
        external_order_id="DJ-TG-DES-NAME", platform_id=platform.id,
        state=OrderState.REVISION.value, product_name="Poster", printerval_designer="Tên Trên Print",
    )
    db_session.add_all([platform, admin, designer, order])
    db_session.flush()
    db_session.add(Assignment(order_id=order.id, designer_id=designer.id, status="approved"))
    db_session.commit()

    with patch("app.application.telegram_service.send_telegram_request") as send:
        send.return_value = {"ok": True}
        assert notify_admin_new_fix(db_session, order.id) is True

    payload = send.call_args.args[1]
    message = payload.get("caption") or payload["text"]
    assert "Tên Designer Tacahu" in message
    assert "Tên Trên Print" not in message


def test_telegram_admin_can_write_note_before_fix_is_released(client: TestClient, db_session):
    platform = Platform(name="Plat custom note", account_username="admin@print.com", is_active=True)
    admin = User(
        username="admin-custom-note", full_name="Admin Custom", role="admin",
        password_hash=hash_password("pass"), telegram_chat_id="222", active=True,
    )
    order = Order(
        external_order_id="DJ-TG-CUSTOM-NOTE", platform_id=platform.id,
        state=OrderState.REVISION.value, product_name="Canvas", note_outsource="Raw QC note",
    )
    db_session.add_all([platform, admin, order])
    db_session.flush()
    original_action = TelegramActionLog(
        order_id=order.id, action_type="APPROVE_FIX", callback_token="approve-custom-note",
        payload={"order_id": str(order.id)},
    )
    db_session.add(original_action)
    db_session.commit()

    with patch("app.application.telegram_service.send_telegram_request") as send:
        send.return_value = {"ok": True}
        response = client.post(
            "/api/telegram/webhook",
            json={"callback_query": {"id": "custom-1", "data": "appfix:approve-custom-note", "from": {"id": 222}}},
        )
        assert response.status_code == 200
        write_note_token = db_session.query(TelegramActionLog.callback_token).filter(
            TelegramActionLog.action_type == "APPROVE_FIX_WRITE_NOTE"
        ).scalar()
        response = client.post(
            "/api/telegram/webhook",
            json={"callback_query": {"id": "custom-2", "data": f"appfixnote:{write_note_token}", "from": {"id": 222}}},
        )
        assert response.status_code == 200

        response = client.post(
            "/api/telegram/webhook",
            json={"message": {"chat": {"id": 222}, "text": "Đổi font và căn giữa logo.", "from": {"id": 222}}},
        )
        assert response.status_code == 200

    db_session.refresh(order)
    assert order.fix_approved_by_admin is True
    assert order.designer_note == "Đổi font và căn giữa logo."
    assert order.designer_note_released_for_fix is True


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
        urgent_payload = mock_send.call_args.args[1]
        urgent_message = urgent_payload.get("caption") or urgent_payload["text"]
        assert "Mã đơn" not in urgent_message
        assert "DJ-FMT-111" not in urgent_message

        # Payment
        res3 = notify_designer_payment(db_session, user.id, 10, 400000)
        assert res3 is True


def test_urgent_fix_telegram_never_includes_printerval_outsource_note(db_session):
    designer = User(
        username="fix-private-note-designer",
        full_name="Fix Private Note Designer",
        role="designer",
        password_hash=hash_password("pass"),
        telegram_chat_id="101010",
        telegram_notifications_enabled=True,
        active=True,
    )
    order = Order(
        external_order_id="DJ-FIX-PRIVATE",
        state=OrderState.REVISION.value,
        product_name="Hoodie",
        note_outsource="PRIVATE PRINT QC NOTE",
        designer_note="Chỉnh lại logo theo ảnh mẫu",
    )
    db_session.add_all([designer, order])
    db_session.commit()

    with patch("app.application.telegram_service.send_telegram_request") as mock_send:
        mock_send.return_value = {"ok": True}
        assert notify_designer_urgent_fix(db_session, order.id, designer.id) is True

    payload = mock_send.call_args.args[1]
    assert "Chỉnh lại logo theo ảnh mẫu" in payload["text"]
    assert "PRIVATE PRINT QC NOTE" not in payload["text"]

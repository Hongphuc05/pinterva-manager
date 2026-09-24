from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.adapters.db.models import (
    Assignment,
    Order,
    Platform,
    SupportCompareJob,
    TelegramActionLog,
    TelegramFixConversation,
    User,
)
from app.application.auth import create_session_token, hash_password
from app.application.support_compare import enqueue_scheduled_support_compare_jobs
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


def test_support_check_command_counts_scope_and_enqueues_full_scan(client: TestClient, db_session):
    platform = Platform(name="Plat support check", account_username="support-check@print.com", is_active=True)
    db_session.add(platform)
    db_session.flush()
    support = User(
        username="support-check",
        full_name="Support Check",
        role="support",
        password_hash=hash_password("pass"),
        telegram_chat_id="998877",
        active=True,
        platform_id=platform.id,
    )
    waiting_order = Order(
        external_order_id="DJ-CHECK-WAITING",
        platform_id=platform.id,
        state=OrderState.WAITING.value,
        duplicate_check_status="uncheck",
        work_domain="standard",
    )
    doing_order = Order(
        external_order_id="DJ-CHECK-DOING",
        platform_id=platform.id,
        state=OrderState.IN_PROGRESS.value,
        duplicate_check_status="uncheck",
        work_domain="standard",
    )
    completed_order = Order(
        external_order_id="DJ-CHECK-DONE",
        platform_id=platform.id,
        state=OrderState.DONE.value,
        duplicate_check_status="uncheck",
        work_domain="standard",
    )
    duplicate_domain_order = Order(
        external_order_id="DJ-CHECK-DUPLICATE-DOMAIN",
        platform_id=platform.id,
        state=OrderState.WAITING.value,
        duplicate_check_status="uncheck",
        work_domain="duplicate",
    )
    db_session.add_all([support, waiting_order, doing_order, completed_order, duplicate_domain_order])
    db_session.commit()

    with (
        patch(
            "app.api.routes.telegram_api.get_settings",
            return_value=SimpleNamespace(
                support_compare_enabled=True,
                telegram_webhook_secret=None,
            ),
        ),
        patch("app.api.routes.telegram_api.send_message", return_value={"message_id": 700}) as send_message,
        patch("app.api.routes.telegram_api.clear_message_keyboard") as clear_keyboard,
    ):
        response = client.post(
            "/api/telegram/webhook",
            json={"message": {"chat": {"id": 998877}, "from": {"id": 998877}, "text": "/check"}},
        )
        assert response.status_code == 200

        prompt = next(call for call in send_message.call_args_list if "reply_markup" in call.kwargs)
        keyboard = prompt.kwargs["reply_markup"]["inline_keyboard"][0]
        yes_callback = keyboard[0]["callback_data"]
        assert "<b>2</b>" in prompt.args[1]

        response = client.post(
            "/api/telegram/webhook",
            json={
                "callback_query": {
                    "id": "support-check-callback",
                    "data": yes_callback,
                    "from": {"id": 998877},
                }
            },
        )
        assert response.status_code == 200
        clear_keyboard.assert_called_once_with("998877", 700)

    actions = db_session.query(TelegramActionLog).filter(
        TelegramActionLog.action_type.in_(("SUPPORT_COMPARE_CHECK_YES", "SUPPORT_COMPARE_CHECK_NO"))
    ).all()
    assert {action.status for action in actions} == {"executed", "superseded"}
    executed = next(action for action in actions if action.status == "executed")
    job = db_session.query(SupportCompareJob).one()
    assert job.status == "queued"
    assert job.platform_id == platform.id
    assert job.chat_id == "998877"
    assert job.requested_count == 2
    assert executed.payload["job_id"] == str(job.id)


def test_scheduled_support_compare_creates_one_job_per_platform(db_session):
    platform = Platform(name="Plat scheduled compare", account_username="scheduled@print.com", is_active=True)
    db_session.add(platform)
    db_session.flush()
    support = User(
        username="support-scheduled",
        full_name="Support Scheduled",
        role="support",
        password_hash=hash_password("pass"),
        telegram_chat_id="998878",
        active=True,
        platform_id=platform.id,
    )
    waiting_order = Order(
        external_order_id="DJ-SCHEDULED-WAITING",
        platform_id=platform.id,
        state=OrderState.WAITING.value,
        duplicate_check_status="uncheck",
        work_domain="standard",
    )
    doing_order = Order(
        external_order_id="DJ-SCHEDULED-DOING",
        platform_id=platform.id,
        state=OrderState.IN_PROGRESS.value,
        duplicate_check_status="uncheck",
        work_domain="standard",
    )
    db_session.add_all([support, waiting_order, doing_order])
    db_session.commit()

    assert enqueue_scheduled_support_compare_jobs(db_session) == 1
    job = db_session.query(SupportCompareJob).one()
    assert job.requested_by_id is None
    assert job.chat_id == "998878"
    assert job.requested_count == 2
    assert enqueue_scheduled_support_compare_jobs(db_session) == 0


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


def test_rejected_fix_cleans_transient_chat_but_keeps_root_card(client, db_session):
    platform = Platform(name="Telegram cleanup", account_username="cleanup@example.com")
    admin = User(username="cleanup-admin", full_name="Cleanup Admin", role="admin", password_hash=hash_password("pass"), telegram_chat_id="777", active=True)
    order = Order(external_order_id="DJ-CLEANUP", platform_id=platform.id, state=OrderState.REVISION.value)
    db_session.add_all([platform, admin, order])
    db_session.flush()
    db_session.add_all([
        TelegramActionLog(order_id=order.id, action_type="REJECT_FIX", callback_token="reject-cleanup", payload={}, expires_at=None),
        TelegramFixConversation(order_id=order.id, chat_id="777", root_message_id=100, transient_message_ids=[101, 102]),
    ])
    db_session.commit()

    with patch("app.api.routes.telegram_api.clear_message_keyboard") as clear, patch("app.api.routes.telegram_api.delete_messages") as delete:
        clear.return_value = True
        delete.return_value = True
        response = client.post("/api/telegram/webhook", json={"callback_query": {"data": "rejfix:reject-cleanup", "from": {"id": 777}}})
    assert response.status_code == 200
    clear.assert_called_once_with("777", 100)
    delete.assert_called_once_with("777", [101, 102])
    conversation = db_session.query(TelegramFixConversation).one()
    assert conversation.status == "cleaned"


def test_resolve_tacahu_designer_name_and_excessive_fix_notification(db_session):
    from app.application.telegram_service import (
        notify_admin_excessive_fix,
        resolve_tacahu_designer_name,
    )

    admin = User(
        username="admin_excessive_fix",
        full_name="Admin Excessive Fix",
        role="admin",
        password_hash=hash_password("pass"),
        telegram_chat_id="999888777",
        telegram_notifications_enabled=True,
        active=True,
    )
    designer = User(
        username="huong_2d",
        full_name="Nguyễn Thị Thuý Hường",
        role="designer",
        password_hash=hash_password("pass"),
        active=True,
    )
    db_session.add_all([admin, designer])
    db_session.commit()

    # Case 1: Order with active assignment on Tacahu
    order_assigned = Order(
        external_order_id="DJ4026454",
        printerval_designer="Nguyễn Thị Thuý Hường - 2D Prin",
    )
    db_session.add(order_assigned)
    db_session.flush()
    db_session.add(Assignment(order_id=order_assigned.id, designer_id=designer.id, status="approved"))
    db_session.commit()

    name1 = resolve_tacahu_designer_name(db_session, order_assigned)
    assert name1 == "Nguyễn Thị Thuý Hường"

    # Case 2: Order unassigned on Tacahu, but printerval_designer string matches Tacahu user
    order_unassigned = Order(
        external_order_id="DJ4026455",
        printerval_designer="Nguyễn Thị Thuý Hường - 2D Prin",
    )
    db_session.add(order_unassigned)
    db_session.commit()

    name2 = resolve_tacahu_designer_name(db_session, order_unassigned)
    assert name2 == "Nguyễn Thị Thuý Hường"

    # Check Telegram notification for excessive fix uses Tacahu designer name
    with patch("app.application.telegram_service.send_telegram_request") as mock_send:
        mock_send.return_value = {"ok": True}
        assert notify_admin_excessive_fix(db_session, order_unassigned.id, designer_name="Nguyễn Thị Thuý Hường - 2D Prin", fix_count=4) is True

    assert mock_send.called
    payload = mock_send.call_args.args[1]
    assert "Nguyễn Thị Thuý Hường" in payload["text"]
    assert "- 2D Prin" not in payload["text"]

from datetime import UTC, datetime
from unittest.mock import patch

from app.adapters.db.models import Assignment, Order, User
from app.application.auth import hash_password
from app.application.telegram_service import (
    notify_admin_deadline_overdue_by_designer,
    notify_designer_new_order,
)
from app.domain.models import OrderState


def test_new_order_notification_uses_tacahu_deadline(db_session):
    designer = User(
        username="telegram_deadline_designer",
        full_name="Telegram Deadline Designer",
        role="designer",
        password_hash=hash_password("pass"),
        telegram_chat_id="555666888",
        telegram_notifications_enabled=True,
        active=True,
    )
    order = Order(
        external_order_id="DJ-DEADLINE-111",
        state=OrderState.IN_PROGRESS.value,
        product_name="Deadline test product",
        deadline_at_ext=datetime(2026, 9, 23, 16, 0, tzinfo=UTC),
        deadline_tacahu=datetime(2026, 9, 22, 9, 30, tzinfo=UTC),
    )
    db_session.add_all([designer, order])
    db_session.commit()

    with patch("app.application.telegram_service.send_telegram_request") as send:
        send.return_value = {"ok": True}

        assert notify_designer_new_order(db_session, order.id, designer.id) is True

    payload = send.call_args.args[1]
    message = payload.get("caption") or payload["text"]
    # Stored timestamps are UTC; Telegram must display the Admin-facing
    # Vietnam time rather than silently showing UTC.
    assert "22/09/2026 16:30" in message
    assert "23/09/2026 16:00" not in message
    assert "Mã đơn" not in message
    assert "DJ-DEADLINE-111" not in message


def test_overdue_notification_is_grouped_by_designer(db_session):
    admin = User(
        username="telegram_overdue_admin",
        full_name="Telegram Overdue Admin",
        role="admin",
        password_hash=hash_password("pass"),
        telegram_chat_id="999111222",
        telegram_notifications_enabled=True,
        active=True,
    )
    dan = User(
        username="telegram_overdue_dan",
        full_name="Dân",
        role="designer",
        password_hash=hash_password("pass"),
    )
    chien = User(
        username="telegram_overdue_chien",
        full_name="Chiến",
        role="designer",
        password_hash=hash_password("pass"),
    )
    orders = [
        Order(
            external_order_id=f"DJ-OVERDUE-{index}",
            state=OrderState.IN_PROGRESS.value,
            deadline_tacahu=datetime(2026, 9, 20, 6, 0, tzinfo=UTC),
        )
        for index in range(5)
    ]
    db_session.add_all([admin, dan, chien, *orders])
    db_session.flush()
    db_session.add_all(
        [
            *(Assignment(order_id=order.id, designer_id=dan.id, status="approved") for order in orders[:3]),
            *(Assignment(order_id=order.id, designer_id=chien.id, status="approved") for order in orders[3:]),
        ]
    )
    db_session.commit()

    with patch("app.application.telegram_service.send_telegram_request") as send:
        send.return_value = {"ok": True}
        notify_admin_deadline_overdue_by_designer(db_session, orders)

    assert send.call_count == 2
    messages = [call.args[1]["text"] for call in send.call_args_list]
    assert any("Designer:</b> Dân" in message and "3" in message for message in messages)
    assert any("Designer:</b> Chiến" in message and "2" in message for message in messages)
    assert all("DJ-OVERDUE" not in message for message in messages)


def test_overdue_fix_order_gets_own_message_with_send_to_designer_button(db_session):
    admin = User(username="fixover_admin", full_name="A", role="admin", password_hash=hash_password("pass"),
                 telegram_chat_id="999333", telegram_notifications_enabled=True, active=True)
    des = User(username="fixover_des", full_name="Dân", role="designer", password_hash=hash_password("pass"))
    order = Order(external_order_id="DJ-FIXOVER", state=OrderState.REVISION.value,
                  fix_deadline_at=datetime(2026, 9, 20, 6, 0, tzinfo=UTC))
    db_session.add_all([admin, des, order])
    db_session.flush()
    db_session.add(Assignment(order_id=order.id, designer_id=des.id, status="approved"))
    db_session.commit()

    with patch("app.application.telegram_service.send_telegram_request") as send:
        send.return_value = {"message_id": 5}
        notify_admin_deadline_overdue_by_designer(db_session, [order])

    payload = send.call_args.args[1]
    assert "ĐƠN FIX QUÁ 1 GIỜ" in payload["text"] and "DJ-FIXOVER" in payload["text"]
    button = payload["reply_markup"]["inline_keyboard"][0][0]
    assert button["callback_data"].startswith("remdes:")

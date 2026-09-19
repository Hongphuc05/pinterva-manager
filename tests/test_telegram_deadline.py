from datetime import UTC, datetime
from unittest.mock import patch

from app.adapters.db.models import Order, User
from app.application.auth import hash_password
from app.application.telegram_service import notify_designer_new_order
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
    assert "22/09/2026 09:30" in message
    assert "23/09/2026 16:00" not in message

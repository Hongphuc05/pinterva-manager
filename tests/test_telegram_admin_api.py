from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.adapters.db.models import Order, Platform, TelegramConfigurationAudit, User
from app.application.auth import create_session_token, hash_password
from app.application.telegram_service import (
    TelegramGroupInspection,
    notify_designer_new_order,
)
from app.domain.models import OrderState


def _auth(user: User) -> dict[str, str]:
    token = create_session_token(str(user.id), user.role)
    return {"Authorization": f"Bearer {token}"}


def _admin_and_platform(db_session, *, suffix: str = "main") -> tuple[Platform, User]:
    platform = Platform(
        name=f"Telegram platform {suffix}",
        account_username=f"telegram-{suffix}@example.com",
        is_active=True,
    )
    db_session.add(platform)
    db_session.flush()
    admin = User(
        username=f"telegram-admin-{suffix}",
        full_name="Telegram Admin",
        role="admin",
        password_hash=hash_password("pass"),
        platform_id=platform.id,
        active=True,
    )
    db_session.add(admin)
    db_session.commit()
    return platform, admin


def test_telegram_admin_overview_is_platform_scoped_and_admin_only(client: TestClient, db_session):
    platform, admin = _admin_and_platform(db_session)
    other_platform = Platform(
        name="Other Telegram platform",
        account_username="other-telegram@example.com",
        is_active=True,
    )
    db_session.add(other_platform)
    db_session.flush()
    own_designer = User(
        username="telegram-own-designer",
        full_name="Own Designer",
        role="designer",
        password_hash=hash_password("pass"),
        platform_id=platform.id,
        telegram_chat_id="1001",
    )
    own_trello_designer = User(
        username="telegram-own-trello",
        full_name="Own Trello Designer",
        role="designer-trello",
        password_hash=hash_password("pass"),
        platform_id=platform.id,
    )
    own_support = User(
        username="telegram-own-support",
        full_name="Own Support",
        role="support",
        password_hash=hash_password("pass"),
        platform_id=platform.id,
    )
    other_designer = User(
        username="telegram-other-designer",
        full_name="Other Designer",
        role="designer",
        password_hash=hash_password("pass"),
        platform_id=other_platform.id,
    )
    db_session.add_all([own_designer, own_trello_designer, own_support, other_designer])
    db_session.commit()

    response = client.get("/api/telegram/admin/overview", headers=_auth(admin))
    assert response.status_code == 200
    data = response.json()
    assert {row["username"] for row in data["designers"]} == {
        "telegram-own-designer",
        "telegram-own-trello",
    }
    assert data["private_connected_count"] == 1

    non_admin = User(
        username="telegram-non-admin",
        full_name="Non Admin",
        role="designer",
        password_hash=hash_password("pass"),
        platform_id=platform.id,
    )
    db_session.add(non_admin)
    db_session.commit()
    forbidden = client.get("/api/telegram/admin/overview", headers=_auth(non_admin))
    assert forbidden.status_code == 403


def test_admin_can_save_verify_select_and_test_group(client: TestClient, db_session):
    platform, admin = _admin_and_platform(db_session, suffix="group")
    designer = User(
        username="telegram-group-designer",
        full_name="Group Designer",
        role="designer",
        password_hash=hash_password("pass"),
        platform_id=platform.id,
        telegram_chat_id="private-2002",
    )
    db_session.add(designer)
    db_session.commit()

    headers = _auth(admin)
    save_response = client.put(
        f"/api/telegram/admin/designers/{designer.id}/group",
        headers=headers,
        json={"group_chat_id": "-1002002002"},
    )
    assert save_response.status_code == 200
    assert save_response.json()["group_verified"] is False

    with patch(
        "app.api.routes.telegram_admin_api.inspect_telegram_group",
        return_value=TelegramGroupInspection(
            ok=True,
            chat_id="-1002002002",
            chat_type="supergroup",
            title="Group Designer",
        ),
    ):
        verify_response = client.post(
            f"/api/telegram/admin/designers/{designer.id}/group/verify",
            headers=headers,
        )
    assert verify_response.status_code == 200
    assert verify_response.json()["group_verified"] is True

    mode_response = client.patch(
        f"/api/telegram/admin/designers/{designer.id}/delivery-mode",
        headers=headers,
        json={"mode": "group"},
    )
    assert mode_response.status_code == 200
    assert mode_response.json()["delivery_mode"] == "group"
    assert mode_response.json()["selected_chat_id"] == "-1002002002"

    with patch("app.api.routes.telegram_admin_api.is_telegram_configured", return_value=True), patch(
        "app.api.routes.telegram_admin_api.send_message",
        return_value={"message_id": 42},
    ) as send_message:
        test_response = client.post(
            f"/api/telegram/admin/designers/{designer.id}/test",
            headers=headers,
            json={"message": "<b>test</b>"},
        )
    assert test_response.status_code == 200
    assert test_response.json()["chat_id"] == "-1002002002"
    assert send_message.call_args.args[0] == "-1002002002"
    assert send_message.call_args.args[1] == "&lt;b&gt;test&lt;/b&gt;"

    audit_actions = {
        row.action_type
        for row in db_session.query(TelegramConfigurationAudit)
        .filter(TelegramConfigurationAudit.target_user_id == designer.id)
        .all()
    }
    assert audit_actions == {
        "SET_DESIGNER_GROUP_CHAT",
        "VERIFY_DESIGNER_GROUP_CHAT",
        "CHANGE_DESIGNER_DELIVERY_MODE",
    }


def test_duplicate_group_is_rejected_and_group_mode_has_no_private_fallback(
    client: TestClient, db_session
):
    platform, admin = _admin_and_platform(db_session, suffix="duplicate")
    first = User(
        username="telegram-first-group",
        full_name="First Group",
        role="designer",
        password_hash=hash_password("pass"),
        platform_id=platform.id,
        telegram_chat_id="private-first",
        telegram_group_chat_id="-1003003003",
        telegram_group_verified=True,
        telegram_delivery_mode="group",
    )
    second = User(
        username="telegram-second-group",
        full_name="Second Group",
        role="designer",
        password_hash=hash_password("pass"),
        platform_id=platform.id,
        telegram_chat_id="private-second",
    )
    db_session.add_all([first, second])
    db_session.commit()

    duplicate = client.put(
        f"/api/telegram/admin/designers/{second.id}/group",
        headers=_auth(admin),
        json={"group_chat_id": "-1003003003"},
    )
    assert duplicate.status_code == 409

    order = Order(
        external_order_id="DJ-TELEGRAM-NO-FALLBACK",
        state=OrderState.IN_PROGRESS.value,
        product_name="Group routing test",
    )
    db_session.add(order)
    db_session.commit()

    first.telegram_group_verified = False
    db_session.commit()
    with patch("app.application.telegram_service.send_telegram_request") as send_request:
        assert notify_designer_new_order(db_session, order.id, first.id) is False
    send_request.assert_not_called()


def test_template_update_preview_and_reset(client: TestClient, db_session):
    _, admin = _admin_and_platform(db_session, suffix="templates")
    headers = _auth(admin)

    invalid = client.put(
        "/api/telegram/admin/templates/designer_new_order",
        headers=headers,
        json={"body": "{{not_allowed}}"},
    )
    assert invalid.status_code == 422

    updated = client.put(
        "/api/telegram/admin/templates/designer_new_order",
        headers=headers,
        json={"body": "Sản phẩm: {{product_name}}"},
    )
    assert updated.status_code == 200
    assert updated.json()["body"] == "Sản phẩm: {{product_name}}"
    # The shared test fixture truncates seeded rows after each test; the API
    # recreates the first override at version 1 when no stored row remains.
    assert updated.json()["version"] == 1

    preview = client.post(
        "/api/telegram/admin/templates/designer_new_order/preview",
        headers=headers,
        json={"body": "Sản phẩm: {{product_name}}", "context": {"product_name": "Áo <test>"}},
    )
    assert preview.status_code == 200
    assert preview.json()["rendered"] == "Sản phẩm: Áo &lt;test&gt;"

    reset = client.post(
        "/api/telegram/admin/templates/designer_new_order/reset",
        headers=headers,
    )
    assert reset.status_code == 200
    assert "{{product_name}}" in reset.json()["body"]
    assert reset.json()["version"] == 1

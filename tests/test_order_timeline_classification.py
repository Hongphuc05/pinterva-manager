"""In a dispute over Support pay, the order timeline must say who classified the order and how."""

from __future__ import annotations

import uuid

from app.adapters.db.models import Order, Platform, User
from app.api.routes.orders_api import format_event_description
from app.application.auth import create_session_token, hash_password
from app.application.duplicate_board import set_orders_duplicate_status
from app.domain.models import OrderState


def test_classification_events_name_the_account_its_role_and_the_result():
    support = format_event_description(
        "WAITING", "IN_PROGRESS", "duplicate_status_changed", "nhím2", "support", None,
        evidence={"to_check_status": "duplicate"},
    )
    assert support == "Support nhím2 phân loại đơn: Trùng lặp"

    admin_domain = format_event_description(
        "OPEN", "IN_PROGRESS", "work_domain_changed", "System Administrator", "admin", None,
        evidence={"to_domain": "duplicate"},
    )
    assert admin_domain == "Admin System Administrator chuyển đơn sang Trùng lặp (Duplicate Board)"
    assert "phân công" not in admin_domain  # used to read "phân công đơn cho Designer"

    back = format_event_description(
        "IN_PROGRESS", "WAITING", "duplicate_status_changed", "System Administrator", "admin", None,
        evidence={"to_check_status": "non_duplicate"},
    )
    assert back == "Admin System Administrator phân loại đơn: Không trùng lặp"


def test_admin_sees_who_classified_the_order_on_its_timeline(client, db_session):
    platform = Platform(name="TL", account_username="tl@print.com", is_active=True)
    db_session.add(platform)
    db_session.flush()
    support = User(username=f"sp-{uuid.uuid4().hex[:5]}", full_name="Nhím", role="support",
                   password_hash=hash_password("p"), active=True, platform_id=platform.id)
    admin = User(username=f"ad-{uuid.uuid4().hex[:5]}", full_name="Admin Một", role="admin",
                 password_hash=hash_password("p"), active=True, platform_id=platform.id)
    order = Order(external_order_id="DJ-TIMELINE", platform_id=platform.id, state=OrderState.WAITING.value,
                  duplicate_check_status="uncheck", work_domain="standard")
    db_session.add_all([support, admin, order])
    db_session.commit()

    set_orders_duplicate_status(db_session, actor=support, platform_id=platform.id, order_ids=[order.id],
                                duplicate_status="duplicate")

    res = client.get(f"/api/orders/{order.id}",
                     headers={"Authorization": f"Bearer {create_session_token(str(admin.id), admin.role)}"})
    descriptions = [e["description"] for e in res.json()["history"]]
    assert "Support Nhím phân loại đơn: Trùng lặp" in descriptions

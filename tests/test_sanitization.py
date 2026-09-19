from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.adapters.db.models import Assignment, Order, Platform, User
from app.application.auth import create_session_token, hash_password
from app.application.sanitization import (
    decode_proxy_url,
    encode_proxy_url,
    sanitize_custom_config,
    sanitize_source_files,
    sanitize_text,
)


def test_encode_and_decode_proxy_url():
    raw = "https://assets.printerval.com/2026/09/18/test-image.png"
    proxied = encode_proxy_url(raw)
    assert proxied is not None
    assert "printerval" not in proxied.lower()
    assert proxied.startswith("/api/assets/proxy?u=")

    # Decode back
    u_param = proxied.split("?u=")[1]
    decoded = decode_proxy_url(u_param)
    assert decoded == raw

    # Non-printerval or local URLs remain untouched
    local_url = "/crawled_assets/123.png"
    assert encode_proxy_url(local_url) == local_url
    assert encode_proxy_url("https://drive.google.com/file/d/123") == "https://drive.google.com/file/d/123"


def test_sanitize_text_and_source_files():
    text = "Order synced from Printerval with note https://printerval.com/admin/orders?id=123"
    cleaned = sanitize_text(text, "Hệ thống mẹ")
    assert cleaned is not None
    assert "printerval" not in cleaned.lower()
    assert "Hệ thống mẹ" in cleaned

    sources = [
        {"name": "Printerval Front Design.png", "url": "https://assets.printerval.com/img1.png"},
        {"name": "Photo 2", "url": "https://drive.google.com/img2.png"},
    ]
    cleaned_sources = sanitize_source_files(sources)
    assert cleaned_sources is not None
    for s in cleaned_sources:
        assert "printerval" not in s["name"].lower()
        assert "printerval" not in s["url"].lower()


def test_sanitize_custom_config():
    config = {
        "printerval_option": "Front",
        "custom_image": "https://assets.printerval.com/preview.png",
        "note": "Created on Printerval site",
    }
    cleaned = sanitize_custom_config(config)
    assert cleaned is not None
    serialized = json.dumps(cleaned)
    assert "printerval" not in serialized.lower()


def test_designer_api_orders_list_contains_zero_printerval(client: TestClient, db_session):
    # Create platform and users
    platform = Platform(
        name="Acc Mẹ Printerval 1",
        account_username="seller_01@printerval.com",
        is_active=True,
    )
    db_session.add(platform)
    db_session.flush()

    designer = User(
        username="designer_test",
        full_name="Nguyễn Văn Designer",
        role="designer",
        password_hash=hash_password("password"),
        platform_id=platform.id,
        printerval_designer_option="nguyen van designer prin",
        active=True,
    )
    db_session.add(designer)
    db_session.flush()

    # Create order with Printerval metadata
    order = Order(
        external_order_id="PRIN-99901",
        state="IN_PROGRESS",
        product_name="T-Shirt 2D Custom Printerval",
        thumbnail_url="https://assets.printerval.com/mockups/thumb1.png",
        sku_image_url="https://assets.printerval.com/sku/sku1.png",
        product_image_urls=[
            "https://assets.printerval.com/gallery/img1.png",
            "https://assets.printerval.com/gallery/img2.png",
        ],
        external_order_url="https://printerval.com/admin/orders?id=99901",
        printerval_designer="nguyen van designer prin",
        printerval_status="doing",
        deadline_at_ext=datetime(2026, 9, 20, 10, 0),
        deadline_tacahu=datetime(2026, 9, 20, 3, 0, tzinfo=UTC),
        source_download_all_url="https://printerval.com/admin/orders/download-all?id=99901",
        source_files=[
            {"name": "Printerval Art.png", "url": "https://assets.printerval.com/files/art.png"}
        ],
        note_outsource="Printerval customer note: please hurry",
        platform_id=platform.id,
    )
    db_session.add(order)
    db_session.flush()

    assignment = Assignment(
        order_id=order.id,
        designer_id=designer.id,
        status="approved",
        sub_status="doing",
    )
    db_session.add(assignment)
    db_session.commit()

    # 1. Fetch as Designer
    token_des = create_session_token(str(designer.id), designer.role)
    resp_des = client.get(
        "/api/orders",
        headers={"Authorization": f"Bearer {token_des}", "X-Platform-Id": str(platform.id)},
    )
    assert resp_des.status_code == 200
    json_des_str = json.dumps(resp_des.json()).lower()
    assert "printerval" not in json_des_str, f"Found printerval in designer response: {json_des_str}"

    # Verify key properties for designer
    des_orders = resp_des.json()["orders"]
    assert len(des_orders) == 1
    assert "external_order_url" not in des_orders[0]
    assert "printerval_designer" not in des_orders[0]
    assert "printerval_status" not in des_orders[0]
    assert "deadline_at_ext" not in des_orders[0]
    assert des_orders[0]["deadline_tacahu"] is not None
    assert des_orders[0]["assigned_designer_name"] == designer.full_name
    assert des_orders[0]["thumbnail_url"].startswith("/api/assets/proxy?u=")

    # 2. Fetch order detail as Designer
    resp_detail = client.get(
        f"/api/orders/{order.id}",
        headers={"Authorization": f"Bearer {token_des}"},
    )
    assert resp_detail.status_code == 200
    json_detail_str = json.dumps(resp_detail.json()).lower()
    assert "printerval" not in json_detail_str, f"Found printerval in detail response: {json_detail_str}"
    detail_data = resp_detail.json()["order"]
    assert "external_order_url" not in detail_data
    assert "printerval_status" not in detail_data
    assert "deadline_at_ext" not in detail_data
    assert detail_data["deadline_tacahu"] is not None
    assert detail_data["thumbnail_url"].startswith("/api/assets/proxy?u=")
    assert len(detail_data["product_image_urls"]) == 2
    assert all(url.startswith("/api/assets/proxy?u=") for url in detail_data["product_image_urls"])

    # 3. Fetch current platform as Designer
    resp_plat = client.get(
        "/api/platforms/current",
        headers={"Authorization": f"Bearer {token_des}", "X-Platform-Id": str(platform.id)},
    )
    assert resp_plat.status_code == 200
    json_plat_str = json.dumps(resp_plat.json()).lower()
    assert "printerval" not in json_plat_str, f"Found printerval in platform response: {json_plat_str}"
    plat_data = resp_plat.json()
    assert "@gmail.com" in plat_data["account_username"]
    assert "Printerval" not in plat_data["name"]

    # 4. Fetch my-tasks as Designer
    resp_tasks = client.get(
        "/api/my-tasks",
        headers={"Authorization": f"Bearer {token_des}"},
    )
    assert resp_tasks.status_code == 200
    json_tasks_str = json.dumps(resp_tasks.json()).lower()
    assert "printerval" not in json_tasks_str, f"Found printerval in tasks response: {json_tasks_str}"

    # 5. Fetch history as Designer
    resp_history = client.get(
        f"/api/orders/{order.id}/history",
        headers={"Authorization": f"Bearer {token_des}"},
    )
    assert resp_history.status_code == 200
    json_hist_str = json.dumps(resp_history.json()).lower()
    assert "printerval" not in json_hist_str, f"Found printerval in history response: {json_hist_str}"


def test_admin_access_preserves_printerval_metadata(client: TestClient, db_session):
    platform = Platform(
        name="Acc Mẹ Printerval 2",
        account_username="seller_admin@printerval.com",
        is_active=True,
    )
    db_session.add(platform)
    db_session.flush()

    admin = User(
        username="admin_test",
        full_name="Admin User",
        role="admin",
        password_hash=hash_password("password"),
        platform_id=platform.id,
        active=True,
    )
    db_session.add(admin)
    db_session.flush()

    order = Order(
        external_order_id="PRIN-99902",
        state="IN_PROGRESS",
        product_name="T-Shirt 2D Custom Printerval",
        thumbnail_url="https://assets.printerval.com/mockups/thumb2.png",
        external_order_url="https://printerval.com/admin/orders?id=99902",
        printerval_designer="nguyen van designer prin",
        printerval_status="doing",
        platform_id=platform.id,
    )
    db_session.add(order)
    db_session.commit()

    token_adm = create_session_token(str(admin.id), admin.role)

    # 1. Orders list as Admin
    resp_adm = client.get(
        "/api/orders",
        headers={"Authorization": f"Bearer {token_adm}", "X-Platform-Id": str(platform.id)},
    )
    assert resp_adm.status_code == 200
    adm_orders = resp_adm.json()["orders"]
    assert len(adm_orders) == 1
    assert adm_orders[0]["printerval_status"] == "doing"
    assert adm_orders[0]["external_order_url"] == "https://printerval.com/admin/orders?id=99902"

    # 2. Platform as Admin
    resp_plat = client.get(
        "/api/platforms/current",
        headers={"Authorization": f"Bearer {token_adm}", "X-Platform-Id": str(platform.id)},
    )
    assert resp_plat.status_code == 200
    assert resp_plat.json()["account_username"] == "seller_admin@printerval.com"


def test_support_role_is_also_sanitized(client: TestClient, db_session):
    platform = Platform(
        name="Acc Mẹ Printerval 3",
        account_username="seller_support@printerval.com",
        is_active=True,
    )
    db_session.add(platform)
    db_session.flush()

    support_user = User(
        username="nhim_support",
        full_name="Nhim Support",
        role="support",
        password_hash=hash_password("password"),
        platform_id=platform.id,
        active=True,
    )
    db_session.add(support_user)
    db_session.flush()

    order = Order(
        external_order_id="PRIN-99903",
        state="IN_PROGRESS",
        product_name="T-Shirt 2D Custom Printerval",
        thumbnail_url="https://assets.printerval.com/mockups/thumb3.png",
        external_order_url="https://printerval.com/admin/orders?id=99903",
        printerval_designer="nguyen van designer prin",
        printerval_status="doing",
        platform_id=platform.id,
    )
    db_session.add(order)
    db_session.commit()

    token_sup = create_session_token(str(support_user.id), support_user.role)

    # 1. Orders list as Support
    resp_sup = client.get(
        "/api/orders",
        headers={"Authorization": f"Bearer {token_sup}", "X-Platform-Id": str(platform.id)},
    )
    assert resp_sup.status_code == 200
    json_sup_str = json.dumps(resp_sup.json()).lower()
    assert "printerval" not in json_sup_str, f"Found printerval in support response: {json_sup_str}"
    sup_orders = resp_sup.json()["orders"]
    assert len(sup_orders) == 1
    assert sup_orders[0]["thumbnail_url"].startswith("/api/assets/proxy?u=")
    assert "external_order_url" not in sup_orders[0]
    assert "printerval_status" not in sup_orders[0]

    # 2. Platform as Support
    resp_plat = client.get(
        "/api/platforms/current",
        headers={"Authorization": f"Bearer {token_sup}", "X-Platform-Id": str(platform.id)},
    )
    assert resp_plat.status_code == 200
    json_plat_str = json.dumps(resp_plat.json()).lower()
    assert "printerval" not in json_plat_str
    assert "@gmail.com" in resp_plat.json()["account_username"]

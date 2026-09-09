import hashlib

from app.adapters.db.models import Order, Platform, User
from app.application.auth import hash_password


def _login(client, db_session):
    user = User(
        username="gallery_token_admin",
        full_name="Gallery Admin",
        role="admin",
        password_hash=hash_password("pass123"),
        active=True,
    )
    db_session.add(user)
    db_session.commit()
    response = client.post("/api/login", json={"username": user.username, "password": "pass123"})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_extension_gallery_import_replaces_single_fallback_for_its_platform(client, db_session):
    platform = Platform(name="Platform A", account_username="a@printerval.com")
    db_session.add(platform)
    db_session.flush()
    token = "test-gallery-token"
    platform.gallery_bridge_token_hash = hashlib.sha256(token.encode()).hexdigest()
    order = Order(
        external_order_id="DJ123",
        platform_id=platform.id,
        state="OPEN",
        product_image_urls=["https://assets.printerval.com/old-thumbnail.jpg"],
    )
    db_session.add(order)
    db_session.commit()

    response = client.post(
        "/api/integrations/printerval-gallery",
        json={
            "platform_id": str(platform.id),
            "external_order_id": "DJ123",
            "image_urls": [
                "https://gdn.printerval.com/unsafe/960x960/assets.printerval.com/one.jpg",
                "https://assets.printerval.com/two.jpg",
            ],
        },
        headers={"X-Gallery-Bridge-Token": token},
    )

    assert response.status_code == 200
    assert response.json()["image_count"] == 2
    db_session.refresh(order)
    assert order.product_image_urls == [
        "https://gdn.printerval.com/unsafe/960x960/assets.printerval.com/one.jpg",
        "https://assets.printerval.com/two.jpg",
    ]


def test_extension_gallery_import_rejects_bad_token_and_cross_platform_order(client, db_session):
    platform = Platform(name="Platform A", account_username="a@printerval.com")
    other_platform = Platform(name="Platform B", account_username="b@printerval.com")
    db_session.add_all([platform, other_platform])
    db_session.flush()
    token = "valid-token"
    platform.gallery_bridge_token_hash = hashlib.sha256(token.encode()).hexdigest()
    db_session.add(Order(external_order_id="DJ999", platform_id=other_platform.id, state="OPEN"))
    db_session.commit()

    payload = {
        "platform_id": str(platform.id),
        "external_order_id": "DJ999",
        "image_urls": ["https://assets.printerval.com/one.jpg"],
    }
    assert client.post(
        "/api/integrations/printerval-gallery", json=payload, headers={"X-Gallery-Bridge-Token": "bad"}
    ).status_code == 401
    assert client.post(
        "/api/integrations/printerval-gallery", json=payload, headers={"X-Gallery-Bridge-Token": token}
    ).status_code == 404


def test_admin_can_rotate_a_platform_gallery_token(client, db_session):
    platform = Platform(name="Platform A", account_username="a@printerval.com")
    db_session.add(platform)
    db_session.commit()
    token = _login(client, db_session)

    response = client.post(
        f"/api/platforms/{platform.id}/gallery-bridge-token",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    returned_token = response.json()["token"]
    db_session.refresh(platform)
    assert platform.gallery_bridge_token_hash == hashlib.sha256(returned_token.encode()).hexdigest()

import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import Order, Platform
from app.api.deps import DEFAULT_PLATFORM_ID, get_db
from app.api.main import create_app
from app.domain.models import OrderState


@pytest.fixture()
def client(db_session):
    app = create_app()

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_platform(db_session):
    platform = Platform(
        id=DEFAULT_PLATFORM_ID,
        name="Default Platform",
        account_username="admin",
        is_active=True,
    )
    db_session.merge(platform)
    db_session.commit()
    return platform


def test_import_single_printerval_gallery_success(client, db_session):
    _seed_platform(db_session)
    order = Order(
        external_order_id="DJ1001",
        platform_id=DEFAULT_PLATFORM_ID,
        state=OrderState.OPEN.value,
        product_image_urls=["https://assets.printerval.com/unsafe/500x500/old.jpg"],
    )
    db_session.add(order)
    db_session.commit()

    payload = {
        "external_order_id": "DJ1001",
        "image_urls": [
            "https://assets.printerval.com/unsafe/960x960/img1.jpg",
            "https://assets.printerval.com/unsafe/960x960/img2.jpg",
            "https://assets.printerval.com/unsafe/960x960/img1.jpg",  # duplicate to test deduplication
        ],
        "product_url": "https://printerval.com/us/sample-product-p123",
    }
    resp = client.post("/api/integrations/printerval-gallery", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["external_order_id"] == "DJ1001"
    assert data["image_count"] == 2

    db_session.refresh(order)
    assert order.product_image_urls == [
        "https://assets.printerval.com/img1.jpg",
        "https://assets.printerval.com/img2.jpg",
    ]


def test_import_single_printerval_gallery_not_found(client, db_session):
    _seed_platform(db_session)
    payload = {
        "external_order_id": "DJ_NON_EXISTING",
        "image_urls": ["https://assets.printerval.com/unsafe/960x960/img1.jpg"],
    }
    resp = client.post("/api/integrations/printerval-gallery", json=payload)
    assert resp.status_code == 404


def test_import_single_printerval_gallery_invalid_urls(client, db_session):
    _seed_platform(db_session)
    payload = {
        "external_order_id": "DJ1001",
        "image_urls": ["javascript:alert(1)"],
    }
    resp = client.post("/api/integrations/printerval-gallery", json=payload)
    assert resp.status_code == 422


def test_import_batch_printerval_gallery_success(client, db_session):
    _seed_platform(db_session)
    o1 = Order(external_order_id="DJ2001", platform_id=DEFAULT_PLATFORM_ID, state=OrderState.OPEN.value)
    o2 = Order(external_order_id="DJ2002", platform_id=DEFAULT_PLATFORM_ID, state=OrderState.OPEN.value)
    db_session.add_all([o1, o2])
    db_session.commit()

    payload = {
        "platform_id": str(DEFAULT_PLATFORM_ID),
        "items": [
            {
                "external_order_id": "DJ2001",
                "image_urls": [
                    "https://assets.printerval.com/unsafe/960x960/o1_1.jpg",
                    "https://assets.printerval.com/unsafe/960x960/o1_2.jpg",
                ],
            },
            {
                "external_order_id": "DJ2002",
                "image_urls": [
                    "https://assets.printerval.com/unsafe/960x960/o2_1.jpg",
                    "https://assets.printerval.com/unsafe/960x960/o2_2.jpg",
                    "https://assets.printerval.com/unsafe/960x960/o2_3.jpg",
                ],
            },
            {
                "external_order_id": "DJ_IGNORED",
                "image_urls": ["https://assets.printerval.com/unsafe/960x960/ignored.jpg"],
            },
        ],
    }

    resp = client.post("/api/integrations/printerval-gallery/batch", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["synced_orders_count"] == 2
    assert data["total_images_count"] == 5

    db_session.refresh(o1)
    db_session.refresh(o2)
    assert len(o1.product_image_urls) == 2
    assert len(o2.product_image_urls) == 3


def test_import_batch_printerval_gallery_empty_items(client, db_session):
    _seed_platform(db_session)
    payload = {"items": []}
    resp = client.post("/api/integrations/printerval-gallery/batch", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["synced_orders_count"] == 0

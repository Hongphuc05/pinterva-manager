import json
from unittest.mock import MagicMock, patch

import httpx

from app.adapters.printerval.gallery_scraper import (
    extract_gallery_images_from_html,
    normalize_gallery_image_url,
)
from app.adapters.printerval.row_mapper import (
    extract_product_sales_url,
    fetch_product_gallery_images,
)


def test_normalize_gallery_image_url_converts_to_960x960():
    url = "https://gdn.printerval.com/unsafe/600x0/assets.printerval.com/2023/11/29/test.jpg"
    normalized = normalize_gallery_image_url(url)
    assert normalized == "https://gdn.printerval.com/unsafe/960x960/assets.printerval.com/2023/11/29/test.jpg"


def test_normalize_gallery_image_url_adds_https():
    url = "//assets.printerval.com/unsafe/300x300/photo.png"
    normalized = normalize_gallery_image_url(url)
    assert normalized.startswith("https://")
    assert "/unsafe/960x960/" in normalized


def test_extract_gallery_images_from_html_extracts_and_filters():
    html = """
    <div class="product-gallery">
        <div class="product-thumbnail-slide">
            <img src="https://gdn.printerval.com/unsafe/600x0/assets.printerval.com/photo1.jpg" alt="Preview 1">
        </div>
        <div class="product-thumbnail-slide">
            <img data-src="https://gdn.printerval.com/unsafe/600x0/assets.printerval.com/photo2.jpg" alt="Preview 2">
        </div>
        <div class="product-thumbnail-slide">
            <img loading-src="https://gdn.printerval.com/unsafe/600x0/assets.printerval.com/photo1.jpg" alt="Duplicate 1">
        </div>
        <div class="product-thumbnail-slide">
            <img src="https://assets.printerval.com/user/avatar.png" alt="Avatar">
        </div>
        <div class="product-thumbnail-slide">
            <img src="https://assets.printerval.com/badges/icon_free_ship.png" alt="Icon Badge">
        </div>
    </div>
    """
    images = extract_gallery_images_from_html(html)
    assert len(images) == 2
    assert images[0] == "https://gdn.printerval.com/unsafe/960x960/assets.printerval.com/photo1.jpg"
    assert images[1] == "https://gdn.printerval.com/unsafe/960x960/assets.printerval.com/photo2.jpg"


def test_extract_gallery_images_from_html_fallback():
    fallback = "https://gdn.printerval.com/fallback.jpg"
    assert extract_gallery_images_from_html("", fallback_image_url=fallback) == [fallback]
    assert extract_gallery_images_from_html("<div>No images</div>", fallback_image_url=fallback) == [fallback]
    assert extract_gallery_images_from_html(None, fallback_image_url=fallback) == [fallback]


def test_extract_product_sales_url():
    row_with_product_link = {
        "product": {
            "name": "Maya Jama 2024 Calendar",
            "url": "https://printerval.com/us/maya-jama-calendar-p3736161",
        }
    }
    assert extract_product_sales_url(row_with_product_link) == "https://printerval.com/us/maya-jama-calendar-p3736161"

    row_with_slug = {
        "product": {
            "name": "Taylor Calendar",
            "slug": "taylor-2024-calendar-p3736161",
        }
    }
    assert extract_product_sales_url(row_with_slug) == "https://printerval.com/taylor-2024-calendar-p3736161"


def test_extract_product_sales_url_builds_clickable_preview_url_from_api_ids():
    """The API separates product slug/id and SKU id, while the preview click URL
    needs both the ``-p`` suffix and the ``spid`` query parameter."""
    row = {
        "product_id": 2749120720,
        "product": {
            "slug": "sn-lax-poke-chill-mint-cartoon-bubble-style-leather-bags-gift-for-her",
            "id": 2749120720,
        },
        "meta_data": json.dumps(
            {
                "product_skus": {
                    "3419826043": {"product_sku_id": 3419826043},
                }
            }
        ),
    }

    assert extract_product_sales_url(row) == (
        "https://printerval.com/"
        "sn-lax-poke-chill-mint-cartoon-bubble-style-leather-bags-gift-for-her-p2749120720"
        "?spid=3419826043"
    )


def test_fetch_product_gallery_images_success():
    sample_html = """
    <div class="product-gallery">
        <div class="product-thumbnail-slide">
            <img src="https://gdn.printerval.com/unsafe/600x0/assets.printerval.com/calendar1.jpg">
        </div>
        <div class="product-thumbnail-slide">
            <img src="https://gdn.printerval.com/unsafe/600x0/assets.printerval.com/calendar2.jpg">
        </div>
    </div>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sample_html

    with patch.object(httpx.Client, "get", return_value=mock_resp):
        imgs = fetch_product_gallery_images("https://printerval.com/us/calendar-p123")
        assert len(imgs) == 2
        assert "calendar1.jpg" in imgs[0]
        assert "calendar2.jpg" in imgs[1]


def test_fetch_product_gallery_images_fallback_on_error():
    with patch.object(httpx.Client, "get", side_effect=Exception("Connection failed")):
        imgs = fetch_product_gallery_images("https://printerval.com/broken", fallback_image_url="https://fallback.jpg")
        assert imgs == ["https://fallback.jpg"]

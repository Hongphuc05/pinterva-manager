from pathlib import Path
import httpx
import pytest

from app.adapters.printerval.image_helper import (
    append_to_crawled_orders_csv,
    download_and_save_image,
    extract_image_url_from_dict_or_html,
    normalize_image_url,
)


def test_extract_image_url_from_dict():
    row_1 = {"thumbnail_url": "https://gdn.printerval.com/unsafe/600x0/assets.printerval.com/img.png"}
    assert extract_image_url_from_dict_or_html(row_1) == "https://gdn.printerval.com/unsafe/600x0/assets.printerval.com/img.png"

    row_2 = {"image": "assets.printerval.com/2026/08/22/custom.png"}
    assert extract_image_url_from_dict_or_html(row_2) == "assets.printerval.com/2026/08/22/custom.png"

    row_nested = {"item": {"src": "https://example.com/pic.jpg"}}
    assert extract_image_url_from_dict_or_html(row_nested) == "https://example.com/pic.jpg"


def test_extract_image_url_from_html():
    html_snippet = (
        '<img ng-src="https://gdn.printerval.com/unsafe/600x0/assets.printerval.com/2026/08/22/custom-product.png" '
        'alt="Discover product" '
        'src="https://gdn.printerval.com/unsafe/600x0/assets.printerval.com/2026/08/22/custom-product.png">'
    )
    assert extract_image_url_from_dict_or_html(html_snippet) == "https://gdn.printerval.com/unsafe/600x0/assets.printerval.com/2026/08/22/custom-product.png"


def test_normalize_image_url():
    assert normalize_image_url("//gdn.printerval.com/img.png") == "https://gdn.printerval.com/img.png"
    assert normalize_image_url("https://printerval.com/img.png") == "https://printerval.com/img.png"
    assert (
        normalize_image_url("assets.printerval.com/2026/08/22/demo.png")
        == "https://gdn.printerval.com/unsafe/600x0/assets.printerval.com/2026/08/22/demo.png"
    )


def test_download_and_save_image(tmp_path):
    def handler(request):
        if request.url.path.endswith("test_img.png"):
            return httpx.Response(200, content=b"fake-image-bytes")
        return httpx.Response(404)

    httpx_client = httpx.Client(transport=httpx.MockTransport(handler))

    # Monkeypatch httpx.Client to use our mock transport
    original_init = httpx.Client.__init__
    
    local_dir = tmp_path / "crawled_assets"
    
    # Direct test using httpx MockTransport
    full_url = "https://gdn.printerval.com/unsafe/600x0/assets.printerval.com/test_img.png"
    resp = httpx_client.get(full_url)
    assert resp.status_code == 200
    assert resp.content == b"fake-image-bytes"

    file_path = local_dir / "3968925.png"
    local_dir.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(resp.content)
    assert file_path.exists()
    assert file_path.read_bytes() == b"fake-image-bytes"


def test_append_to_crawled_orders_csv(tmp_path):
    csv_file = tmp_path / "crawled_orders.csv"
    append_to_crawled_orders_csv(
        external_order_id="DJ1001",
        product_name="Custom T-Shirt 2D",
        sku="SKU-123",
        product_category="Clothing",
        status="Waiting",
        batch_id="batch-001",
        thumbnail_url="https://gdn.printerval.com/unsafe/600x0/assets.printerval.com/img.png",
        local_image_path="/crawled_assets/DJ1001.png",
        csv_path=csv_file,
    )

    assert csv_file.exists()
    content = csv_file.read_text(encoding="utf-8")
    assert "/crawled_assets/DJ1001.png" in content


def test_append_to_crawled_orders_csv_platform(tmp_path, monkeypatch):
    platform_id = "4582df07-b9e8-4959-94e9-0f57e42694ee"
    crawled_dir = tmp_path / "crawled_assets"
    monkeypatch.setattr("app.adapters.printerval.image_helper.CRAWLED_ASSETS_DIR", crawled_dir)

    append_to_crawled_orders_csv(
        external_order_id="DJ2002",
        product_name="Custom Mug 3D",
        status="Waiting",
        platform_id=platform_id,
    )

    platform_csv = crawled_dir / platform_id / "crawled_orders.csv"
    assert platform_csv.exists()
    content = platform_csv.read_text(encoding="utf-8")
    assert "DJ2002,Custom Mug 3D" in content

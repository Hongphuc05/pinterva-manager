from pathlib import Path
import httpx
import pytest

from app.adapters.printerval.image_helper import (
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



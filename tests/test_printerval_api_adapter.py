import httpx
import pytest

from app.adapters.errors import ErrorClass
from app.adapters.printerval.api_adapter import PrintervalApiAdapter
from app.adapters.printerval.api_client import FIND_PATH, LOGIN_PATH, PrintervalApiClient
from app.adapters.printerval.fake_adapter import FakePrintervalAdapter


def _api_adapter(handler, **overrides):
    client = httpx.Client(
        base_url="https://printerval.test", transport=httpx.MockTransport(handler)
    )
    api_client = PrintervalApiClient(
        base_url="https://printerval.test",
        username="operator@example.test",
        password="password123",
        team_outsource="team-a",
        client=client,
    )
    fallback = overrides.get("fallback_adapter", FakePrintervalAdapter())
    return PrintervalApiAdapter(api_client=api_client, fallback_adapter=fallback)


def test_discover_orders_success():
    def handler(request):
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf-123">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": "/admin"})
        if request.method == "GET" and request.url.path == FIND_PATH:
            return httpx.Response(
                200,
                json={
                    "status": "successful",
                    "result": [{"code": "DJ101"}, {"code": "DJ102"}],
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    adapter = _api_adapter(handler)
    res = adapter.discover_orders(status="Waiting", limit=40)
    assert res.success is True
    assert len(res.orders) == 2
    assert [o.external_order_id for o in res.orders] == ["DJ101", "DJ102"]


def test_discover_orders_missing_config():
    api_client = PrintervalApiClient(
        base_url="https://printerval.test",
        username=None,
        password=None,
        team_outsource=None,
    )
    adapter = PrintervalApiAdapter(api_client=api_client)
    res = adapter.discover_orders(status="Waiting")
    assert res.success is False


def test_fallback_delegation():
    fake = FakePrintervalAdapter()
    fake.add_order(external_order_id="DJ999", product_name="Test", designer=None, status="waiting")
    adapter = _api_adapter(lambda req: httpx.Response(500), fallback_adapter=fake)

    # get_order_detail delegates to fallback
    detail = adapter.get_order_detail("DJ999")
    assert detail.success is True
    assert detail.external_order_id == "DJ999"

    # set_designer delegates to fallback
    write = adapter.set_designer("DJ999", "Nguyễn Thị Thuý Hường - 2D Prin")
    assert write.success is True


def test_get_order_detail_uses_the_fast_http_path_without_touching_fallback():
    def handler(request):
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": "/admin"})
        if request.method == "GET" and request.url.path == FIND_PATH:
            params = dict(request.url.params)
            if params["status"] == "doing":
                return httpx.Response(
                    200,
                    json={
                        "status": "successful",
                        "result": [{"id": 3968034, "status": "doing", "product": {"name": "Mug"}}],
                    },
                )
            return httpx.Response(200, json={"status": "successful", "result": []})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    class _ExplodingFallback:
        def __getattr__(self, name):
            raise AssertionError(f"fallback.{name} must not be called — the fast path found the row")

    adapter = _api_adapter(handler, fallback_adapter=_ExplodingFallback())
    result = adapter.get_order_detail("DJ3968034")

    assert result.success is True
    assert result.product_name == "Mug"


def test_download_asset_uses_the_fast_http_path_for_a_plain_product_order():
    def handler(request):
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": "/admin"})
        if request.method == "GET" and request.url.path == FIND_PATH:
            params = dict(request.url.params)
            if params["status"] == "doing":
                return httpx.Response(
                    200,
                    json={
                        "status": "successful",
                        "result": [{"id": 3968678, "status": "doing", "is_custom_design": None}],
                    },
                )
            return httpx.Response(200, json={"status": "successful", "result": []})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    class _ExplodingFallback:
        def __getattr__(self, name):
            raise AssertionError(f"fallback.{name} must not be called — the fast path found the row")

    adapter = _api_adapter(handler, fallback_adapter=_ExplodingFallback())
    result = adapter.download_asset("DJ3968678")

    assert result.success is True
    assert result.local_path is None  # plain product order — nothing to download

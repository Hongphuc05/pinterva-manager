import httpx

from app.adapters.printerval.api_adapter import PrintervalApiAdapter
from app.adapters.printerval.api_client import (
    DESIGNER_OPTIONS_URL,
    FIND_PATH,
    LOGIN_PATH,
    PrintervalApiClient,
)
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


def test_list_designer_options_reads_the_platform_scoped_http_endpoint():
    def handler(request):
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf-123">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": "/admin"})
        if str(request.url).startswith(DESIGNER_OPTIONS_URL):
            assert request.url.params["filters"] == "team=team-a"
            return httpx.Response(
                200,
                json={
                    "status": "successful",
                    "result": [
                        {"full_name": "Custom A"},
                        {"full_name": "Custom B"},
                        {"full_name": "Custom A"},
                    ],
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    api_client = PrintervalApiClient(
        base_url="https://printerval.test",
        username="operator@example.test",
        password="password123",
        team_outsource="team-a",
        client=httpx.Client(
            base_url="https://printerval.test",
            transport=httpx.MockTransport(handler),
        ),
    )
    assert api_client.list_designer_options() == ["Custom A", "Custom B"]


def test_discover_orders_prefixes_a_bare_numeric_row_id_with_dj():
    """Regression test for a real incident: newly-crawled orders were stored without
    the "DJ" prefix (e.g. "3971347" instead of "DJ3971347") because real rows have no
    "code"/"job_code" field, only a bare numeric `id` — discover_orders used to fall
    through straight to that unprefixed value."""
    def handler(request):
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf-123">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": "/admin"})
        if request.method == "GET" and request.url.path == FIND_PATH:
            return httpx.Response(200, json={"status": "successful", "result": [{"id": 3971347}]})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    adapter = _api_adapter(handler)
    res = adapter.discover_orders(status="Waiting", limit=40)
    assert res.success is True
    assert [o.external_order_id for o in res.orders] == ["DJ3971347"]


def test_discover_orders_forwards_date_filters_to_the_client():
    seen_params = []

    def handler(request):
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf-123">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": "/admin"})
        if request.method == "GET" and request.url.path == FIND_PATH:
            seen_params.append(dict(request.url.params))
            return httpx.Response(200, json={"status": "successful", "result": []})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    adapter = _api_adapter(handler)
    adapter.discover_orders(
        status="Waiting", date_from="2026-09-01 00:00:00", date_to="2026-09-07 23:59:59"
    )

    assert seen_params[0]["date_from"] == "2026-09-01 00:00:00"
    assert seen_params[0]["date_to"] == "2026-09-07 23:59:59"


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


def test_get_order_detail_crawls_text_only_custom_configuration_without_an_image():
    """DJ3949734 is the live shape: personalization is text configuration, not an
    uploaded resource image. It must still be imported through the HTTP path."""

    def handler(request):
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": "/admin"})
        if request.method == "GET" and request.url.path == FIND_PATH:
            if dict(request.url.params)["status"] == "doing":
                return httpx.Response(
                    200,
                    json={
                        "status": "successful",
                        "result": [
                            {
                                "id": 3949734,
                                "status": "doing",
                                "product": {"name": "Custom jacket"},
                                "meta_data": (
                                    '{"product_skus":{"sku":{"configurations":'
                                    '"{\\"Custom Name\\": \\"Sample name\\"}",'
                                    '"translated_configurations":{"Tên Tùy Chỉnh":"Sample name"}}}}'
                                ),
                            }
                        ],
                    },
                )
            return httpx.Response(200, json={"status": "successful", "result": []})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    class _ExplodingFallback:
        def __getattr__(self, name):
            raise AssertionError(f"fallback.{name} must not be called")

    adapter = _api_adapter(handler, fallback_adapter=_ExplodingFallback())
    result = adapter.get_order_detail("DJ3949734")

    assert result.success is True
    assert result.thumbnail_url is None
    assert result.custom_config is not None
    assert [entry.model_dump() for entry in result.custom_config.original] == [
        {"key": "Custom Name", "value": "Sample name"}
    ]
    assert [entry.model_dump() for entry in result.custom_config.translated_vn] == [
        {"key": "Tên Tùy Chỉnh", "value": "Sample name"}
    ]


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

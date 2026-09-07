from app.adapters.printerval.fake_adapter import FakePrintervalAdapter


def _seeded_adapter():
    adapter = FakePrintervalAdapter()
    adapter.add_order(
        external_order_id="DJ0000001",
        product_name="Mug in cứng",
        designer=None,
        status="Waiting",
    )
    adapter.add_order(
        external_order_id="DJ0000002",
        product_name="Áo thun",
        designer="Nguyễn Thị Thuý Hường - 2D Prin",
        status="Doing",
    )
    return adapter


def test_discover_orders_filters_by_status():
    adapter = _seeded_adapter()
    result = adapter.discover_orders(status="Waiting")
    assert result.success is True
    assert [o.external_order_id for o in result.orders] == ["DJ0000001"]


def test_get_order_detail_returns_full_fields():
    adapter = _seeded_adapter()
    result = adapter.get_order_detail("DJ0000002")
    assert result.success is True
    assert result.designer == "Nguyễn Thị Thuý Hường - 2D Prin"
    assert result.status == "Doing"


def test_get_order_detail_missing_order_is_validation_error():
    adapter = _seeded_adapter()
    result = adapter.get_order_detail("DJ9999999")
    assert result.success is False
    assert result.error_class == "VALIDATION"


def test_set_designer_updates_and_is_observable():
    adapter = _seeded_adapter()
    write_result = adapter.set_designer("DJ0000001", "Nguyễn Thị Thuý Hường - 2D Prin")
    assert write_result.success is True
    detail = adapter.get_order_detail("DJ0000001")
    assert detail.designer == "Nguyễn Thị Thuý Hường - 2D Prin"


def test_set_status_updates_and_is_observable():
    adapter = _seeded_adapter()
    write_result = adapter.set_status("DJ0000001", "Doing")
    assert write_result.success is True
    detail = adapter.get_order_detail("DJ0000001")
    assert detail.status == "Doing"


def test_attach_result_link_updates_observed_state():
    adapter = _seeded_adapter()
    write_result = adapter.attach_result_link(
        "DJ0000002", "https://drive.google.com/file/d/abc123/view"
    )
    assert write_result.success is True
    assert write_result.observed_state["result_link"].startswith("https://drive.google.com")
    detail = adapter.get_order_detail("DJ0000002")
    assert detail.note_outsource == "https://drive.google.com/file/d/abc123/view"


def test_download_asset_returns_local_path():
    adapter = _seeded_adapter()
    result = adapter.download_asset("DJ0000001")
    assert result.success is True
    assert result.local_path.endswith("DJ0000001.png")


def test_write_methods_reject_unknown_order():
    adapter = _seeded_adapter()
    result = adapter.set_designer("DJ_NOPE", "x")
    assert result.success is False
    assert result.error_class == "VALIDATION"

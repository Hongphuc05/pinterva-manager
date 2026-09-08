import json

from app.adapters.printerval.row_mapper import (
    extract_source_asset_url,
    extract_source_files,
    parse_external_order_id,
    parse_order_detail_from_row,
    parse_product_summary_fields,
)

# A representative row live-captured 2026-09-08 from the real `/design-job/find`
# endpoint (read-only probe, no writes) for a personalized order.
PERSONALIZED_ROW = {
    "id": 3968034,
    "status": "doing",
    "created_at": "2026-09-07 05:31:05",
    "order_created_at": "2026-09-07 05:16:07",
    "deadline_at": "2026-09-08 05:16:07",
    "order_note": "Etsy url: https://example.test/listing/123",
    "is_custom_design": 1,
    "job_type": "3D",
    "multiple_design_id": None,
    "double_sided_id": 7,
    "designs": [],
    "product": {
        "name": "Personalized Nigeria Football Jersey",
        "sku": "P2721079608-US--S-UNI-DQP70BY2",
        "image_url": "https://assets.printerval.com/product.jpg",
        "category_name": "Mesh Football Jerseys",
    },
    "meta_data": json.dumps(
        {
            "product_skus": {
                "2721079608": {
                    "configurations": json.dumps({"Your Name Here": "AVL", "Number": "25"}),
                    "translated_configurations": {"Tên của Bạn": "AVL", "Số": "25"},
                    "image_url": "https://assets.printerval.com/source.jpg",
                    "variants": "Size: L, Type: Unisex",
                }
            },
            "product_name": "Personalized Nigeria Football Jersey",
        }
    ),
    "attributes": {"outsource_note": "https://drive.google.com/drive/folders/abc"},
    "templateJobs": [{"provider_name": "C-EZ", "note": "", "psd_file": []}],
}

PLAIN_ROW = {
    "id": 3968678,
    "status": "waiting",
    "created_at": "2026-09-07 10:00:00",
    "order_created_at": "2026-09-07 09:00:00",
    "deadline_at": "2026-09-09 10:00:00",
    "order_note": "",
    "is_custom_design": None,
    "designs": [],
    "product": {"name": "Plain Mug", "sku": "P0001", "image_url": "https://assets.printerval.com/mug.jpg", "category_name": "Mugs"},
    "meta_data": "{}",
    "attributes": {},
    "templateJobs": None,
}


def test_parse_external_order_id_prefixes_a_bare_numeric_id_with_dj():
    """Regression test: real rows carry no "code"/"job_code" field already holding
    the "DJ#######" form — only a bare numeric `id`. Before this, discover_orders fell
    through straight to that bare id with no prefix, storing e.g. "3971347" for an
    order that is "DJ3971347" everywhere else (Printerval's own site, Playwright's own
    extraction) — two different identities for the same order."""
    assert parse_external_order_id({"id": 3971347}) == "DJ3971347"


def test_parse_external_order_id_prefers_an_already_prefixed_code_field():
    assert parse_external_order_id({"code": "DJ101", "id": 999}) == "DJ101"
    assert parse_external_order_id({"job_code": "202", "id": 999}) == "DJ202"


def test_parse_external_order_id_empty_when_nothing_usable():
    assert parse_external_order_id({}) == ""


def test_parse_product_summary_fields():
    name, sku, category = parse_product_summary_fields(PERSONALIZED_ROW)
    assert name == "Personalized Nigeria Football Jersey"
    assert sku == "P2721079608-US--S-UNI-DQP70BY2"
    assert category == "Mesh Football Jerseys"


def test_extract_source_asset_url_only_for_personalized_orders():
    assert extract_source_asset_url(PERSONALIZED_ROW) == "https://assets.printerval.com/source.jpg"
    assert extract_source_asset_url(PLAIN_ROW) is None


def test_extract_source_files_includes_customer_uploaded_configuration_photos():
    """Regression test: a live row (2026-09-08) whose SKU personalization is a set of
    customer-uploaded photos ("Your Photo 1".."Your Photo N", type "image") — the
    site's own "SOURCE" panel — was previously dropped entirely: extract_source_files
    only looked at `designs` (the designer's finished output) and generic attachment
    fields, never the SKU's own `configurations`."""
    row = {
        "designs": [],
        "meta_data": json.dumps(
            {
                "product_skus": {
                    "123": {
                        "configurations": json.dumps(
                            {
                                "Your Photo 1": {"type": "image", "value": "https://assets.printerval.com/p1.jpg"},
                                "Your Photo 2": {"type": "image", "value": "https://assets.printerval.com/p2.jpg"},
                                "Uploaded image count": 2,
                            }
                        ),
                    }
                }
            }
        ),
    }

    sources = extract_source_files(row)

    assert sources == [
        {"name": "Your Photo 1", "url": "https://assets.printerval.com/p1.jpg"},
        {"name": "Your Photo 2", "url": "https://assets.printerval.com/p2.jpg"},
    ]


def test_extract_source_files_text_only_configuration_yields_nothing_extra():
    """A non-photo personalization (e.g. jersey name/number, PERSONALIZED_ROW's own
    shape) must not be mistaken for a source image."""
    assert extract_source_files(PERSONALIZED_ROW) == [
        {"name": "source.jpg", "url": "https://assets.printerval.com/source.jpg"}
    ]  # falls through to the single-image fallback, same as extract_source_asset_url


def test_parse_order_detail_from_row_personalized(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.printerval.row_mapper.download_and_save_image", lambda *a, **k: None
    )
    result = parse_order_detail_from_row(PERSONALIZED_ROW, "DJ3968034")

    assert result.success is True
    assert result.product_name == "Personalized Nigeria Football Jersey"
    assert result.sku == "P2721079608-US--S-UNI-DQP70BY2"
    assert result.product_category == "Mesh Football Jerseys"
    assert result.double_sided is True
    assert result.multiple_design is False
    assert result.note_outsource == "https://drive.google.com/drive/folders/abc"
    assert result.order_note == "Etsy url: https://example.test/listing/123"
    assert result.created_at.isoformat() == "2026-09-07T05:31:05"
    assert result.order_created_at.isoformat() == "2026-09-07T05:16:07"
    assert result.deadline_at.isoformat() == "2026-09-08T05:16:07"
    assert result.has_template is True
    assert result.design_tool_url == "https://design-tool.printerval.com/?tab=design-job&code=Printerval-DJ3968034"
    assert [v.model_dump() for v in result.product_variants] == [
        {"name": "Size", "value": "L"},
        {"name": "Type", "value": "Unisex"},
    ]
    assert [e.model_dump() for e in result.custom_config.original] == [
        {"key": "Your Name Here", "value": "AVL"},
        {"key": "Number", "value": "25"},
    ]
    assert [e.model_dump() for e in result.custom_config.translated_vn] == [
        {"key": "Tên của Bạn", "value": "AVL"},
        {"key": "Số", "value": "25"},
    ]


def test_parse_order_detail_from_row_plain_product_has_no_design_tool_url_or_custom_config():
    result = parse_order_detail_from_row(PLAIN_ROW, "DJ3968678")

    assert result.success is True
    assert result.design_tool_url is None
    assert result.custom_config is None
    assert result.has_template is False
    assert result.product_variants == []

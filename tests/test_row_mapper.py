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


def test_parse_product_summary_fields_prefers_task_sku_over_generic_product_sku():
    row = {
        "product": {"name": "Raglan", "sku": "GENERIC-SKU", "category_name": "Football"},
        "meta_data": json.dumps(
            {"product_skus": {"one": {"product_sku": "P27172826-DE-UNI-XL-R-t1710IFp"}}}
        ),
    }
    _, sku, category = parse_product_summary_fields(row)
    assert sku == "P27172826-DE-UNI-XL-R-t1710IFp"
    assert category == "Football"


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


def test_extract_source_files_includes_every_image_inside_images_array():
    row = {
        "meta_data": json.dumps(
            {
                "product_skus": {
                    "sku": {
                        "configurations": json.dumps(
                            {
                                "images": [
                                    {"type": "image", "value": "https://assets.printerval.com/one.png"},
                                    {"type": "image", "value": "https://assets.printerval.com/two.png"},
                                ],
                                "texts": [{"text": "Emma"}],
                            }
                        )
                    }
                }
            }
        )
    }

    assert extract_source_files(row) == [
        {"name": "one.png", "url": "https://assets.printerval.com/one.png"},
        {"name": "two.png", "url": "https://assets.printerval.com/two.png"},
    ]


def test_extract_source_files_preserves_every_serialized_configuration_layer():
    """`layers` is the authoritative SOURCE list, including repeated uploads.

    Printerval keeps this field JSON-encoded inside the outer JSON-encoded
    `configurations` value.  The UI's SOURCE card has one row per layer, so
    duplicates must remain duplicates and option metadata must not inflate the
    count.
    """
    layers = [
        {"name": f"photo {index}", "value": f"https://assets.printerval.com/upload-{index % 2}.png"}
        for index in range(22)
    ]
    row = {
        "designs": [{"name": "finished.png", "url": "https://assets.printerval.com/finished.png"}],
        "meta_data": json.dumps(
            {
                "product_skus": {
                    "sku": {
                        "configurations": json.dumps(
                            {
                                "layers": json.dumps(layers),
                                "options": json.dumps(
                                    [{"name": "Upload", "value": "https://assets.printerval.com/upload-0.png"}]
                                ),
                            }
                        )
                    }
                }
            }
        ),
    }

    sources = extract_source_files(row)

    assert sources is not None
    assert len(sources) == 22
    assert [source["url"] for source in sources] == [layer["value"] for layer in layers]


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
    assert result.created_at.isoformat() == "2026-09-07T05:31:05"
    assert result.order_created_at.isoformat() == "2026-09-07T05:16:07"
    assert result.deadline_at.isoformat() == "2026-09-08T05:16:07"
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
    assert result.product_variants == []


def test_parse_order_detail_preserves_each_sku_and_its_variants(monkeypatch):
    monkeypatch.setattr("app.adapters.printerval.row_mapper.download_and_save_image", lambda *a, **k: None)
    row = {
        "id": 3971873,
        "product": {"name": "Raglan", "category_name": "Football Raglan Shirts"},
        "meta_data": json.dumps({"product_skus": {
            "xl": {"product_sku": "P27172826-DE-UNI-XL-R-t1710IFp", "image_url": "https://assets.example/xl.jpg", "variants": "Size: XL, Type: Unisex, Style: Rundhalsausschnitt Shirt"},
            "2xl": {"product_sku": "P27172826-DE-UNI-2XL-eQF170pk", "image_url": "https://assets.example/2xl.jpg", "variants": "Size: 2XL, Type: Unisex, Style: Rundhalsausschnitt Shirt"},
        }}),
    }

    result = parse_order_detail_from_row(row, "DJ3971873")

    assert [item.sku for item in result.product_skus] == [
        "P27172826-DE-UNI-XL-R-t1710IFp", "P27172826-DE-UNI-2XL-eQF170pk"
    ]
    assert [[variant.model_dump() for variant in item.variants] for item in result.product_skus] == [
        [{"name": "Size", "value": "XL"}, {"name": "Type", "value": "Unisex"}, {"name": "Style", "value": "Rundhalsausschnitt Shirt"}],
        [{"name": "Size", "value": "2XL"}, {"name": "Type", "value": "Unisex"}, {"name": "Style", "value": "Rundhalsausschnitt Shirt"}],
    ]


def test_extract_source_files_combines_sources_from_each_sku_configuration():
    row = {
        "meta_data": json.dumps({"product_skus": {
            "xl": {"configurations": json.dumps({"layers": json.dumps([
                {"value": "https://assets.example/xl-1.png"},
            ])})},
            "2xl": {"configurations": json.dumps({"layers": json.dumps([
                {"value": "https://assets.example/2xl-1.png"},
                {"value": "https://assets.example/2xl-2.png"},
            ])})},
        }}),
    }

    assert extract_source_files(row) == [
        {"name": "xl-1.png", "url": "https://assets.example/xl-1.png"},
        {"name": "2xl-1.png", "url": "https://assets.example/2xl-1.png"},
        {"name": "2xl-2.png", "url": "https://assets.example/2xl-2.png"},
    ]


def test_extract_source_files_customily_payload_with_16_images_and_upload():
    """DJ4005539 real-world scenario: 16 customily background/asset images in `images` array
    plus 1 user uploaded image in `options` array."""
    customily_images = [
        {"type": "image", "value": f"https://cdn.customily.com/product-images/img-{i}.jpg", "order": i}
        for i in range(16)
    ]
    options = [
        {"id": 16, "label": "Number Of Image", "value": 0, "value_name": "1"},
        {"id": 1, "label": "Choose Background Color", "value": "Image 1", "value_name": "Image 1"},
        {"id": 4, "label": "Upload Image 1", "value": "/customize/2026/09/14/user-upload-abc.png", "value_name": "Image 1"},
    ]
    row = {
        "meta_data": json.dumps({
            "product_skus": {
                "sku1": {
                    "configurations": json.dumps({
                        "disable_make_change": "true",
                        "images": json.dumps(customily_images),
                        "texts": "[]",
                        "options": json.dumps(options),
                        "canvas": json.dumps({"width": 1000, "height": 1000}),
                    })
                }
            }
        })
    }

    sources = extract_source_files(row)
    assert sources is not None
    # 16 customily images + 1 user upload
    assert len(sources) == 17
    # First 16 are customily images
    for i in range(16):
        assert sources[i]["url"] == f"https://cdn.customily.com/product-images/img-{i}.jpg"
        assert sources[i]["name"] == f"img-{i}.jpg"
    # 17th is normalized user upload
    assert sources[16]["url"] == "https://assets.printerval.com/customize/2026/09/14/user-upload-abc.png"


def test_parse_custom_config_customily_payload_cleanly():
    """DJ4005539 real-world scenario: custom_config must parse options/texts into clean key-value pairs
    and never leak raw technical keys (images, canvas, disable_make_change)."""
    options = [
        {"id": 16, "label": "Number Of Image", "value": 0, "value_name": "1"},
        {"id": 1, "label": "Choose Background Color", "value": "Image 1", "value_name": "Image 1"},
        {"id": 3, "label": "Choose Flower Color", "value": "Image 3", "value_name": "Image 3"},
        {"id": 4, "label": "Upload Image 1", "value": "/customize/2026/09/14/user-upload-abc.png", "value_name": "Image 1"},
        {"id": 15, "label": "Choose Leave Color", "value": "Image 3", "value_name": "Image 3"},
    ]
    sku_data = {
        "configurations": json.dumps({
            "disable_make_change": "true",
            "images": json.dumps([{"type": "image", "value": "https://cdn.customily.com/img.jpg"}]),
            "texts": json.dumps([{"label": "Custom Name", "text": "Olivia"}]),
            "options": json.dumps(options),
            "canvas": json.dumps({"width": 1000, "height": 1000}),
        }),
        "translated_configurations": json.dumps({
            "options": json.dumps([
                {"label": "Số Lượng Ảnh", "value_name": "1"},
                {"label": "Chọn Màu Nền", "value_name": "Ảnh 1"},
            ]),
        }),
    }

    from app.adapters.printerval.row_mapper import _parse_custom_config
    result = _parse_custom_config(sku_data)

    assert result is not None
    orig_dict = {e.key: e.value for e in result.original}
    assert orig_dict == {
        "Number Of Image": "1",
        "Choose Background Color": "Image 1",
        "Choose Flower Color": "Image 3",
        "Upload Image 1": "Image 1",
        "Choose Leave Color": "Image 3",
        "Custom Name": "Olivia",
    }
    # Ensure no technical metadata leaks
    assert "disable_make_change" not in orig_dict
    assert "images" not in orig_dict
    assert "canvas" not in orig_dict

    trans_dict = {e.key: e.value for e in result.translated_vn}
    assert trans_dict == {
        "Số Lượng Ảnh": "1",
        "Chọn Màu Nền": "Ảnh 1",
    }


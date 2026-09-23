from support_compare_image.normalizer import (
    TARGET_STATUSES,
    extract_preview_candidate,
    normalize_image_url,
    normalize_row,
)


def test_preview_extraction_matches_waiting_priority_and_records_path():
    row = {
        "id": 123,
        "status": "done",
        "thumbnail_url": "https://assets.printerval.com/preview.png",
        "product": {"image_url": "https://assets.printerval.com/product.png"},
    }

    candidate = extract_preview_candidate(row)

    assert candidate is not None
    assert candidate.raw_url == "https://assets.printerval.com/preview.png"
    assert candidate.source_path == "row.thumbnail_url"
    assert candidate.url == normalize_image_url(candidate.raw_url)


def test_nested_html_preview_is_supported():
    row = {
        "id": 124,
        "status": "review",
        "attributes": '<img ng-src="/uploads/preview.webp">',
    }

    candidate = extract_preview_candidate(row)

    assert candidate is not None
    assert candidate.raw_url == "/uploads/preview.webp"
    assert candidate.url == "https://printerval.com/uploads/preview.webp"


def test_target_row_without_preview_is_kept_and_flagged():
    normalized = normalize_row(
        {"id": 125, "status": "fix", "product": {"name": "Test product"}},
        team_outsource="thuyhuong",
    )

    assert TARGET_STATUSES == ("done", "confirm", "review", "fix")
    assert normalized.external_order_id == "DJ125"
    assert normalized.product_name == "Test product"
    assert normalized.preview_missing is True
    assert normalized.preview_url is None


def test_outsource_note_is_metadata_not_an_inclusion_predicate():
    normalized = normalize_row(
        {
            "id": 126,
            "status": "confirm",
            "attributes": {"outsource_note": "not-a-url-or-empty-note"},
            "product": {"name": "Another product"},
            "image_url": "https://assets.printerval.com/preview.png",
        },
        team_outsource="thuyhuong",
    )

    assert normalized.note_outsource == "not-a-url-or-empty-note"
    assert normalized.preview_missing is False

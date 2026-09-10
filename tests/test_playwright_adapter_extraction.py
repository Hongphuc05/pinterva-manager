from __future__ import annotations

import pytest
from playwright.sync_api import sync_playwright

from app.adapters.printerval.playwright_adapter import (
    PlaywrightPrintervalAdapter,
    _parse_deadline_datetime,
    _parse_short_datetime,
)

FIXTURES_DIR = "tests/fixtures"


@pytest.fixture()
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page()
        yield pg
        browser.close()


def _load_fixture(page, filename: str):
    with open(f"{FIXTURES_DIR}/{filename}") as f:
        page.set_content(f.read())
    return page.locator("tr").first


def test_extraction_on_plain_order_fixture(page):
    row = _load_fixture(page, "printerval_order_row_plain.html")
    adapter = PlaywrightPrintervalAdapter(page=page)
    result = adapter._extract_order_detail_from_row(row, "DJ_FIXTURE_PLAIN")

    assert result.success is True
    assert result.thumbnail_url == "https://assets.example.com/redacted-thumb-plain.webp"
    assert result.sku == "P_FIXTURE-UNI-XL-PLAIN"
    assert result.product_category == "Hawaiians"
    assert result.multiple_design is False
    assert result.double_sided is False
    assert result.priority_label is None
    assert result.custom_config is None
    assert result.design_tool_url is None
    assert result.created_at is not None
    assert result.order_created_at is not None
    assert result.created_at != result.order_created_at
    assert result.deadline_at is not None


def test_extraction_on_personalized_order_fixture(page):
    row = _load_fixture(page, "printerval_order_row_personalized.html")
    adapter = PlaywrightPrintervalAdapter(page=page)
    result = adapter._extract_order_detail_from_row(row, "DJ_FIXTURE_PERSONALIZED")

    assert result.success is True
    assert result.thumbnail_url == "https://assets.example.com/redacted-thumb-personalized.png"
    assert result.priority_label is not None
    assert "label-danger" in result.priority_label
    assert result.custom_config is not None
    assert result.custom_config.original[0].key == "Your Name Here"
    assert result.custom_config.original[0].value == "Fixture Name"
    assert result.custom_config.translated_vn[0].key == "Tên của Bạn Ở Đây"
    assert result.design_tool_url.startswith("https://design-tool.printerval.com")
    assert "redacted-source-listing" in result.order_note


def test_parse_short_datetime_valid():
    parsed = _parse_short_datetime("03:48'\n07/09/2026")
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.day, parsed.month, parsed.year) == (
        3,
        48,
        7,
        9,
        2026,
    )


def test_parse_short_datetime_garbage_returns_none():
    assert _parse_short_datetime("not a date") is None
    assert _parse_short_datetime("") is None


def test_parse_deadline_datetime_valid():
    parsed = _parse_deadline_datetime("2026-08-27 03:45:10")
    assert parsed is not None
    assert parsed.year == 2026 and parsed.month == 8 and parsed.day == 27


def test_parse_deadline_datetime_garbage_returns_none():
    assert _parse_deadline_datetime("garbage") is None

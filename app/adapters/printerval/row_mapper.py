"""Maps a raw `/design-job/find` row (dict) to our domain models.

Field mapping live-confirmed 2026-09-08 by probing the real, already-authenticated
endpoint this app's crawl already uses (read-only — same call `discover_waiting_page`
makes, just with different filter params; no write, no guessing an unverified schema).
That single endpoint turns out to carry everything `get_order_detail`/`download_asset`
previously had to scrape from the DOM via Playwright — including the 3 timestamps that
were an open question in claude.md §17 #8.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.adapters.printerval.image_helper import (
    download_and_save_image,
    extract_image_url_from_dict_or_html,
)
from app.adapters.printerval.models import (
    CustomConfig,
    CustomConfigEntry,
    OrderDetailResult,
    ProductVariant,
)

DESIGN_TOOL_URL_TEMPLATE = "https://design-tool.printerval.com/?tab=design-job&code=Printerval-{code}"


def _meta_data(row: dict[str, Any]) -> dict[str, Any]:
    """`meta_data` is a JSON-encoded string on the wire, not a nested object."""
    raw = row.get("meta_data")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return raw if isinstance(raw, dict) else {}


def _first_sku_data(meta: dict[str, Any]) -> dict[str, Any] | None:
    """This system's orders always have exactly one product per job — take it."""
    skus = meta.get("product_skus")
    if not isinstance(skus, dict) or not skus:
        return None
    sku_data = next(iter(skus.values()), None)
    return sku_data if isinstance(sku_data, dict) else None


def _parse_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _parse_variants(sku_data: dict[str, Any] | None) -> list[ProductVariant]:
    """`variants` is a single string like "Size: M, Type: Unisex" — one comma-
    separated "Name: Value" pair per variant axis."""
    if not sku_data:
        return []
    raw = sku_data.get("variants")
    if not isinstance(raw, str) or not raw.strip():
        return []
    variants: list[ProductVariant] = []
    for part in raw.split(","):
        name, sep, value = part.strip().partition(":")
        if sep:
            variants.append(ProductVariant(name=name.strip(), value=value.strip()))
    return variants


def _parse_custom_config(sku_data: dict[str, Any] | None) -> CustomConfig | None:
    if not sku_data:
        return None
    raw_config = sku_data.get("configurations")
    config = json.loads(raw_config) if isinstance(raw_config, str) else raw_config
    if not isinstance(config, dict) or not config:
        return None
    original = [CustomConfigEntry(key=str(k), value=str(v)) for k, v in config.items()]
    raw_translated = sku_data.get("translated_configurations")
    translated = (
        [CustomConfigEntry(key=str(k), value=str(v)) for k, v in raw_translated.items()]
        if isinstance(raw_translated, dict)
        else []
    )
    return CustomConfig(original=original, translated_vn=translated)


def parse_external_order_id(row: dict[str, Any]) -> str:
    """The site's own external code. Live-confirmed 2026-09-08: a real row carries no
    "code"/"job_code" field already holding the "DJ#######" form — its own numeric
    `id` IS the code, just missing the "DJ" prefix (confirmed via `search=DJ<id>`
    matching exactly that row on the same endpoint). Returns "" if the row has no
    usable id at all.

    Regression note: before this, discover_orders fell through straight to a bare
    `row.get("id")` with no prefix, so newly-crawled orders got stored as "3971347"
    while the exact same order elsewhere (Playwright, which reads the prefixed code
    straight off the page) was "DJ3971347" — two different identities for one order.
    """
    for key in ("code", "job_code", "external_order_id"):
        val = row.get(key)
        if val:
            val = str(val).strip()
            return val if val.upper().startswith("DJ") else f"DJ{val}"
    raw_id = row.get("id")
    return f"DJ{raw_id}" if raw_id else ""


def parse_product_summary_fields(row: dict[str, Any]) -> tuple[str, str | None, str | None]:
    """(product_name, sku, product_category) — the subset already used at discover
    time, factored out here so discover and detail read the same fields the same way."""
    product_info = row.get("product") if isinstance(row.get("product"), dict) else {}
    meta = _meta_data(row)
    product_name = str(
        product_info.get("name")
        or meta.get("product_name")
        or row.get("product_name")
        or row.get("name")
        or "Đơn 2D Custom"
    )
    sku = str(product_info.get("sku") or row.get("sku") or "") or None
    category = str(product_info.get("category_name") or row.get("product_category") or "") or None
    return product_name, sku, category


def extract_source_asset_url(row: dict[str, Any]) -> str | None:
    """The customer's own personalization source image — download_asset's target.
    Only present for personalized (`is_custom_design`) orders, matching the
    Playwright fallback's identical "no personalized source file" contract."""
    if not row.get("is_custom_design"):
        return None
    sku_data = _first_sku_data(_meta_data(row))
    if not sku_data:
        return None
    url = sku_data.get("image_url")
    return url.strip() if isinstance(url, str) and url.strip() else None


def parse_order_detail_from_row(
    row: dict[str, Any], external_order_id: str, platform_id: str | None = None
) -> OrderDetailResult:
    product_name, sku, category = parse_product_summary_fields(row)
    meta = _meta_data(row)
    sku_data = _first_sku_data(meta)

    raw_image_url = extract_image_url_from_dict_or_html(row)
    local_path = (
        download_and_save_image(external_order_id, raw_image_url, platform_id=platform_id)
        if raw_image_url
        else None
    )

    template_jobs = row.get("templateJobs")
    if not isinstance(template_jobs, list) or not template_jobs:
        template_jobs = None

    is_custom = bool(row.get("is_custom_design"))
    attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}

    return OrderDetailResult(
        success=True,
        external_order_id=external_order_id,
        status=row.get("status"),
        product_name=product_name,
        thumbnail_url=local_path or raw_image_url,
        sku=sku,
        product_category=category,
        product_variants=_parse_variants(sku_data),
        has_template=bool(template_jobs),
        template_jobs=template_jobs,
        multiple_design=bool(row.get("multiple_design_id")),
        double_sided=bool(row.get("double_sided_id")),
        has_uploaded_design=bool(row.get("designs")),
        note_outsource=str(attributes.get("outsource_note") or ""),
        order_note=str(row.get("order_note") or ""),
        created_at=_parse_timestamp(row.get("created_at")),
        order_created_at=_parse_timestamp(row.get("order_created_at")),
        deadline_at=_parse_timestamp(row.get("deadline_at")),
        custom_config=_parse_custom_config(sku_data),
        design_tool_url=(
            DESIGN_TOOL_URL_TEMPLATE.format(code=external_order_id) if is_custom else None
        ),
    )

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

import httpx

from app.adapters.printerval.gallery_scraper import extract_gallery_images_from_html
from app.adapters.printerval.image_helper import (
    download_and_save_image,
    extract_image_url_from_dict_or_html,
)
from app.adapters.printerval.models import (
    CustomConfig,
    CustomConfigEntry,
    OrderDetailResult,
    ProductSku,
    ProductVariant,
)

DESIGN_TOOL_URL_FORMAT = "https://design-tool.printerval.com/?tab=design-job&code=Printerval-{code}"


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
    if isinstance(raw, list):
        variants: list[ProductVariant] = []
        for item in raw:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("key") or "").strip()
                value = str(item.get("value") or "").strip()
                if name and value:
                    variants.append(ProductVariant(name=name, value=value))
        return variants
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
    if isinstance(raw_config, str):
        try:
            config = json.loads(raw_config)
        except (TypeError, ValueError):
            return None
    else:
        config = raw_config
    if not isinstance(config, dict) or not config:
        return None
    # Keep nested image/text arrays valid JSON. `str(list)` creates Python syntax,
    # which made downstream clients treat an entire configuration group as one value.
    def serialize(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)

    original = [CustomConfigEntry(key=str(k), value=serialize(v)) for k, v in config.items()]
    raw_translated = sku_data.get("translated_configurations")
    translated = (
        [CustomConfigEntry(key=str(k), value=serialize(v)) for k, v in raw_translated.items()]
        if isinstance(raw_translated, dict)
        else []
    )
    return CustomConfig(original=original, translated_vn=translated)


def extract_product_skus(row: dict[str, Any]) -> list[ProductSku]:
    """Normalize every Printerval ``meta_data.product_skus`` entry.

    Printerval puts one dictionary item here for each sellable SKU in an order.
    The old crawler selected only the first item, losing separate sizes and their
    own configuration/photo fields.  Preserve the site's order and retain each
    SKU's own image, category, variants and custom configuration.
    """
    meta = _meta_data(row)
    raw_skus = meta.get("product_skus")
    product = row.get("product") if isinstance(row.get("product"), dict) else {}
    fallback_category = str(product.get("category_name") or row.get("product_category") or "").strip() or None
    fallback_sku = str(product.get("sku") or row.get("sku") or "").strip() or None

    if not isinstance(raw_skus, dict) or not raw_skus:
        return [
            ProductSku(
                sku=fallback_sku,
                image_url=extract_sku_image_url(row),
                category=fallback_category,
            )
        ] if (fallback_sku or fallback_category or extract_sku_image_url(row)) else []

    product_skus: list[ProductSku] = []
    for key, raw_sku in raw_skus.items():
        if not isinstance(raw_sku, dict):
            continue
        sku = str(raw_sku.get("product_sku") or raw_sku.get("sku") or "").strip() or None
        # A few legacy rows do not contain product_sku.  The product's generic SKU
        # is better than exposing the opaque numeric map key when there is one SKU.
        if not sku and len(raw_skus) == 1:
            sku = fallback_sku or str(key).strip() or None
        elif not sku:
            sku = str(key).strip() or None
        image_url = str(raw_sku.get("image_url") or "").strip() or None
        category = str(raw_sku.get("category_name") or raw_sku.get("category") or "").strip() or fallback_category
        product_skus.append(
            ProductSku(
                sku=sku,
                image_url=image_url,
                category=category,
                variants=_parse_variants(raw_sku),
                custom_config=_parse_custom_config(raw_sku),
            )
        )
    return product_skus


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
    # `product_skus[*].product_sku` is the value printed beside the preview in
    # Printerval's task detail.  Prefer it over the generic product SKU so Size/Type
    # variants and the displayed SKU always describe the same task.
    product_skus = extract_product_skus(row)
    first_sku = product_skus[0] if product_skus else None
    sku = str(
        (first_sku.sku if first_sku else None) or product_info.get("sku") or row.get("sku") or ""
    ) or None
    category = (first_sku.category if first_sku else None) or str(product_info.get("category_name") or row.get("product_category") or "") or None
    return product_name, sku, category


def extract_sku_image_url(row: dict[str, Any]) -> str | None:
    meta = _meta_data(row)
    sku_data = _first_sku_data(meta)
    if sku_data:
        url = sku_data.get("image_url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    raw = row.get("sku_image_url") or row.get("image_url")
    return str(raw).strip() if isinstance(raw, str) and raw.strip() else None


def extract_external_order_url(row: dict[str, Any]) -> str | None:
    meta = _meta_data(row)
    sku_data = _first_sku_data(meta)
    order_id = (sku_data.get("order_id") if sku_data else None) or row.get("order_id") or row.get("id")
    if order_id:
        order_id_str = str(order_id).strip()
        if order_id_str.startswith("http"):
            return order_id_str
        return f"https://printerval.com/admin/orders?id={order_id_str}"
    raw = row.get("external_order_url") or row.get("order_url")
    return str(raw).strip() if isinstance(raw, str) and raw.strip() else None


def extract_product_sales_url(row: dict[str, Any]) -> str | None:
    """Extract public product sales page link from row or product info."""
    for key in ("product_url", "sales_url", "preview_url", "product_link", "url"):
        val = row.get(key)
        if val and isinstance(val, str) and ("printerval.com" in val or "/us/" in val or "-p" in val):
            return val.strip()

    prod = row.get("product")
    if isinstance(prod, dict):
        for key in ("url", "link", "product_url"):
            val = prod.get(key)
            if val and isinstance(val, str) and val.strip():
                if val.startswith("http"):
                    return val.strip()
                if val.startswith("/"):
                    return f"https://printerval.com{val}"
                return f"https://printerval.com/{val}"

        # The fast design-job API returns a slug, product id and SKU id separately.
        # The clickable product preview on Printerval combines them as
        # ``<slug>-p<product_id>?spid=<product_sku_id>``.  A bare slug loads a
        # generic page and only exposes its thumbnail, which is why gallery imports
        # previously stopped at one image.
        slug = prod.get("slug")
        product_id = prod.get("id") or row.get("product_id")
        meta = _meta_data(row)
        sku_data = _first_sku_data(meta)
        sku_id = sku_data.get("product_sku_id") if sku_data else None
        if isinstance(slug, str) and slug.strip():
            clean_slug = slug.strip().rstrip("/")
            if product_id and f"-p{product_id}" not in clean_slug:
                clean_slug = f"{clean_slug}-p{product_id}"
            url = f"https://printerval.com/{clean_slug}"
            return f"{url}?spid={sku_id}" if sku_id else url

    meta = _meta_data(row)
    sku_data = _first_sku_data(meta)
    if sku_data:
        for key in ("product_url", "url", "link", "sales_url"):
            val = sku_data.get(key)
            if val and isinstance(val, str) and val.strip():
                if val.startswith("http"):
                    return val.strip()
                if val.startswith("/"):
                    return f"https://printerval.com{val}"
                return f"https://printerval.com/{val}"

    return None


def fetch_product_gallery_images(
    sales_url: str | None,
    session_cookie: str | None = None,
    fallback_image_url: str | None = None,
) -> list[str]:
    """Fetch product page and parse gallery image URLs. Fallback to fallback_image_url if broken/blocked."""
    if not sales_url:
        return [fallback_image_url] if fallback_image_url else []
    try:
        abs_url = sales_url if sales_url.startswith("http") else f"https://printerval.com{sales_url}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if session_cookie:
            c_val = session_cookie.strip().strip('"').strip("'")
            if c_val.lower().startswith("cookie:"):
                c_val = c_val[7:].strip()
            headers["Cookie"] = c_val if ("laravel_session=" in c_val or ";" in c_val) else f"laravel_session={c_val}"

        with httpx.Client(timeout=8.0, follow_redirects=True, headers=headers) as client:
            resp = client.get(abs_url)
            if resp.status_code == 200 and resp.text:
                imgs = extract_gallery_images_from_html(resp.text, fallback_image_url)
                if imgs:
                    return imgs
    except Exception:
        pass

    return [fallback_image_url] if fallback_image_url else []


def extract_source_asset_url(row: dict[str, Any]) -> str | None:
    meta = _meta_data(row)
    raw_skus = meta.get("product_skus")
    if isinstance(raw_skus, dict):
        for sku_data in raw_skus.values():
            if isinstance(sku_data, dict) and sku_data.get("configurations"):
                url = sku_data.get("image_url")
                if isinstance(url, str) and url.strip():
                    return url.strip()
    raw = row.get("source_asset_url") or row.get("source_url")
    return str(raw).strip() if isinstance(raw, str) and raw.strip() else None


def extract_source_files(row: dict[str, Any]) -> list[dict[str, str]] | None:
    """Extract list of customer uploaded source images/files."""
    sources: list[dict[str, str]] = []

    # 1. From the SKU's own `configurations` — the customer's raw personalization
    # uploads (e.g. "Your Photo 1".."Your Photo N"), distinct from `designs` above
    # (the designer's finished/composited output). This is the block the live site's
    # own "SOURCE" panel shows — confirmed 2026-09-08 against a real row whose
    # `designs` entry was an unrelated file (api_client.find_order bug, now fixed),
    # while `configurations` held the customer's actual uploaded photos.
    meta = _meta_data(row)
    raw_skus = meta.get("product_skus")
    sku_entries = list(raw_skus.values()) if isinstance(raw_skus, dict) else []
    configs: list[dict[str, Any]] = []
    for sku_data in sku_entries:
        raw_config = sku_data.get("configurations") if isinstance(sku_data, dict) else None
        if isinstance(raw_config, str):
            try:
                config = json.loads(raw_config)
            except (TypeError, ValueError):
                config = None
        else:
            config = raw_config
        if isinstance(config, dict):
            configs.append(config)

    def source_name(url: str) -> str:
        return url.split("?", 1)[0].rstrip("/").split("/")[-1] or "source"

    def sources_from_config_list(key: str) -> list[dict[str, str]]:
        """Read the list-backed configuration fields used by Printerval SOURCE.

        The API serializes ``layers`` as a JSON string.  Each layer is one row in
        Printerval's SOURCE card, even when several rows intentionally point at
        the same upload URL.  Returning this list first preserves that cardinality;
        recursively scanning every nested URL would incorrectly count metadata
        such as ``upload_image_url`` a second time.
        """
        result: list[dict[str, str]] = []
        for config in configs:
            value = config.get(key)
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (TypeError, ValueError):
                    continue
            if not isinstance(value, list):
                continue
            for item in value:
                if not isinstance(item, dict):
                    continue
                url = item.get("value")
                if isinstance(url, str) and url.strip().lower().startswith(("http://", "https://")):
                    clean_url = url.strip()
                    result.append({"name": source_name(clean_url), "url": clean_url})
        return result

    # On the live DJ3976109 payload, `layers` contains exactly the 22 entries
    # shown in Printerval's SOURCE card.  Do not mix `options` or `designs` into
    # this result: those fields are configuration/UI metadata, not extra SOURCE rows.
    layer_sources = sources_from_config_list("layers")
    if layer_sources:
        return layer_sources

    # Some products have simple uploads but no canvas-layer configuration.  Their
    # `options` list is the equivalent authoritative source list.
    option_sources = sources_from_config_list("options")
    if option_sources:
        return option_sources

    def collect_configuration_images(entry: Any, label: str | None = None) -> None:
        """The live site uses both `{photo: {type, value}}` and
        `{images: [{type, value}, ...]}`.  SOURCE lists every image in either
        shape, including repeated filenames, so do not deduplicate here."""
        if isinstance(entry, dict):
            if entry.get("type") == "image":
                url = entry.get("value") or entry.get("src")
                if isinstance(url, str) and url.strip():
                    sources.append({"name": label or url.rstrip("/").split("/")[-1], "url": url.strip()})
            else:
                for nested_key, nested in entry.items():
                    collect_configuration_images(nested, str(nested_key))
        elif isinstance(entry, list):
            for nested in entry:
                collect_configuration_images(nested)

    for config in configs:
        for key, entry in config.items():
            collect_configuration_images(entry, str(key))

    # 2. From row.get("designs") when no configuration-level source list exists.
    designs = row.get("designs")
    if isinstance(designs, list):
        for item in designs:
            if isinstance(item, dict):
                url = item.get("url") or item.get("image_url") or item.get("file_url")
                name = item.get("name") or item.get("file_name") or (url.split("/")[-1] if url else "source.jpg")
                if url:
                    sources.append({"name": str(name), "url": str(url)})

    # 3. From custom_design_files / attachments
    attachments = row.get("custom_design_files") or row.get("attachments") or row.get("source_files")
    if isinstance(attachments, list):
        for item in attachments:
            if isinstance(item, dict):
                url = item.get("url") or item.get("file_url")
                name = item.get("name") or item.get("file_name") or (url.split("/")[-1] if url else "source.jpg")
                if url:
                    sources.append({"name": str(name), "url": str(url)})
            elif isinstance(item, str) and item.strip():
                name = item.split("/")[-1]
                sources.append({"name": name, "url": item.strip()})

    # 4. Fallback: single personalization image
    if not sources:
        single_url = extract_source_asset_url(row)
        if single_url:
            name = single_url.split("/")[-1]
            sources.append({"name": name, "url": single_url})

    return sources if sources else None


def parse_order_detail_from_row(
    row: dict[str, Any],
    external_order_id: str,
    platform_id: str | None = None,
    download_images: bool = True,
    session_cookie: str | None = None,
) -> OrderDetailResult:
    product_name, sku, category = parse_product_summary_fields(row)
    meta = _meta_data(row)
    product_skus = extract_product_skus(row)
    sku_data = _first_sku_data(meta)

    raw_image_url = extract_image_url_from_dict_or_html(row)
    local_path = (
        download_and_save_image(
            external_order_id,
            raw_image_url,
            platform_id=platform_id,
            download=download_images,
        )
        if raw_image_url
        else None
    )

    sales_url = extract_product_sales_url(row)
    gallery_images = (
        fetch_product_gallery_images(
            sales_url,
            session_cookie=session_cookie,
            fallback_image_url=local_path or raw_image_url,
        )
        if sales_url
        else ([local_path or raw_image_url] if (local_path or raw_image_url) else None)
    )

    is_custom = bool(row.get("is_custom_design"))
    attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}

    sku_img = extract_sku_image_url(row)
    ext_order_link = extract_external_order_url(row)
    source_files_list = extract_source_files(row)

    return OrderDetailResult(
        success=True,
        external_order_id=external_order_id,
        status=row.get("status"),
        product_name=product_name,
        thumbnail_url=local_path or raw_image_url,
        sku=sku,
        product_category=category,
        product_variants=_parse_variants(sku_data),
        product_skus=product_skus,
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
            DESIGN_TOOL_URL_FORMAT.format(code=external_order_id) if is_custom else None
        ),
        sku_image_url=sku_img,
        external_order_url=ext_order_link,
        source_files=source_files_list,
        product_image_urls=gallery_images,
    )

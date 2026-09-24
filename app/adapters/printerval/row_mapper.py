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


def _is_internal_or_price_key(key: str, val: Any) -> bool:
    k = str(key).lower().strip()
    if k in (
        "price_addtocart",
        "giá_thêm_vào_giỏ_hàng",
        "price",
        "prx_discount",
        "discount",
        "cart",
        "total",
        "subtotal",
        "disable_make_change",
        "tat_tinh_nang_thay_doi",
        "tắt_tính_năng_thay_đổi",
        "template_id",
        "canvas",
    ):
        return True
    if k.startswith("price_") or k.startswith("giá_thêm_") or "addtocart" in k:
        return True
    if isinstance(val, dict) and ("price" in val or "prx_discount" in val):
        return True
    if isinstance(val, str):
        val_s = val.strip()
        if (val_s.startswith("{") and val_s.endswith("}")) and ("price" in val_s or "prx_discount" in val_s):
            return True
    return False


def _is_image_config_entry(key: str, val: Any) -> bool:
    """Filter out photo/image entries from custom config text table since they belong
    in the order's source_files/gallery rather than raw JSON strings."""
    k_lower = str(key).lower().strip()
    if k_lower in ("images", "layers", "canvas", "disable_make_change", "template_id"):
        return True
    # Always keep preview URLs (e.g. url_xem_trước in Vietnamese translations)
    if "xem_trước" in k_lower or "xem_truoc" in k_lower or "preview" in k_lower:
        return False
    if isinstance(val, dict) and (val.get("type") == "image" or "maskPath" in val or "digit_image" in val):
        return True
    if isinstance(val, list):
        return True
    if isinstance(val, str):
        val_s = val.strip()
        if (val_s.startswith("{") and val_s.endswith("}")) and ('"type": "image"' in val_s or '"maskPath"' in val_s):
            return True
        if (val_s.startswith("[") and val_s.endswith("]")) and ('"type": "image"' in val_s or '"maskPath"' in val_s or '"uid"' in val_s):
            return True
        if val_s.startswith("http") and any(ext in val_s.lower() for ext in (".jpg", ".jpeg", ".png", ".webp", ".svg")):
            return True
    return False


def _clean_custom_config_value(val: Any) -> str:
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    return str(val).strip()


def _parse_custom_config_dict(raw_dict: dict[str, Any]) -> list[CustomConfigEntry]:
    results: list[CustomConfigEntry] = []

    def safe_parse_json(val: Any) -> Any:
        if isinstance(val, str):
            val_s = val.strip()
            if (val_s.startswith("{") and val_s.endswith("}")) or (val_s.startswith("[") and val_s.endswith("]")):
                try:
                    return json.loads(val_s)
                except (TypeError, ValueError):
                    return val
        return val

    # 1. Parse `options` (Customily / Canvas option selections: colors, variant options, customer uploads)
    options_raw = raw_dict.get("options")
    if options_raw:
        options = safe_parse_json(options_raw)
        if isinstance(options, list):
            for opt in options:
                if not isinstance(opt, dict):
                    continue
                label = opt.get("label") or opt.get("name") or opt.get("title")
                if not label:
                    continue
                label_str = str(label).strip()

                # Prefer human-readable value_name (e.g. "1", "Image 1", "Blonde") over raw numeric value
                val_name = opt.get("value_name")
                if val_name is not None and str(val_name).strip() != "":
                    val_str = str(val_name).strip()
                else:
                    raw_v = opt.get("value")
                    if isinstance(raw_v, dict):
                        val_str = str(raw_v.get("name") or raw_v.get("value") or "").strip()
                    else:
                        val_str = str(raw_v or "").strip()

                if not val_str or _is_internal_or_price_key(label_str, val_str):
                    continue

                # If the value is a direct upload path / url, extract clean filename
                if val_str.startswith("/customize/") or val_str.startswith("http"):
                    clean_name = val_str.split("?", 1)[0].rstrip("/").split("/")[-1]
                    val_str = clean_name if clean_name else val_str

                results.append(CustomConfigEntry(key=label_str, value=val_str))

    # 2. Parse `texts` (Custom personalized text lines: Name, Number, Year, Message)
    texts_raw = raw_dict.get("texts")
    if texts_raw:
        texts = safe_parse_json(texts_raw)
        if isinstance(texts, list):
            for idx, item in enumerate(texts):
                if not isinstance(item, dict):
                    continue
                label = item.get("label") or item.get("name") or item.get("title") or f"Custom Text {idx + 1}"
                label_str = str(label).strip()
                text_val = item.get("text") or item.get("value") or item.get("val")
                if text_val is None:
                    continue
                text_str = str(text_val).strip()
                if not text_str or _is_internal_or_price_key(label_str, text_str):
                    continue
                results.append(CustomConfigEntry(key=label_str, value=text_str))

    # 3. Direct key-value pairs (Standard / simple personalization)
    known_technical_keys = {
        "disable_make_change",
        "images",
        "texts",
        "options",
        "canvas",
        "layers",
        "template_id",
        "fonts",
        "elements",
        "preview",
        "thumbnails",
    }

    for k, v in raw_dict.items():
        k_str = str(k).strip()
        if k_str.lower() in known_technical_keys:
            continue
        if _is_internal_or_price_key(k_str, v):
            continue
        if _is_image_config_entry(k_str, v):
            continue

        val_str = _clean_custom_config_value(v)
        val_str = val_str.replace("https://assets.printerval.com", "").replace("http://assets.printerval.com", "")
        if val_str:
            results.append(CustomConfigEntry(key=k_str, value=val_str))

    return results


def _parse_custom_config(sku_data: dict[str, Any] | None) -> CustomConfig | None:
    if not sku_data:
        return None

    def safe_parse_json(val: Any) -> Any:
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (TypeError, ValueError):
                return None
        return val

    raw_config = safe_parse_json(sku_data.get("configurations"))
    if not isinstance(raw_config, dict) or not raw_config:
        return None

    original = _parse_custom_config_dict(raw_config)

    raw_translated = safe_parse_json(sku_data.get("translated_configurations"))
    translated = _parse_custom_config_dict(raw_translated) if isinstance(raw_translated, dict) else []

    if not original and not translated:
        return None

    return CustomConfig(original=original, translated_vn=translated)


def extract_custom_config(row: dict[str, Any]) -> dict[str, Any] | None:
    """The custom configuration of a raw `design-job/find` row, as stored in
    ``Order.custom_config`` (``{"original": [...], "translated_vn": [...]}``)."""
    config = _parse_custom_config(_first_sku_data(_meta_data(row)))
    return config.model_dump() if config else None


def normalize_order_custom_config_and_sources(
    custom_config: dict[str, Any] | None,
    source_files: list[dict[str, Any]] | None,
    product_skus: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
    """Repair and normalize any stored custom_config and source_files.

    Handles both clean structured configs and legacy double-encoded / unparsed
    configurations (e.g. from previously crawled Customily orders).
    """
    def safe_parse_json(val: Any) -> Any:
        if isinstance(val, str):
            val_s = val.strip()
            if (val_s.startswith("{") and val_s.endswith("}")) or (val_s.startswith("[") and val_s.endswith("]")):
                try:
                    return json.loads(val_s)
                except (TypeError, ValueError):
                    return val
        return val

    def normalize_url(raw_url: str) -> str:
        u = str(raw_url).strip()
        if u.startswith("//"):
            return f"https:{u}"
        if u.startswith("/"):
            return f"https://assets.printerval.com{u}"
        return u

    def source_name(url: str, label: str | None = None) -> str:
        if label and not label.startswith("http") and "/" not in label and len(label.strip()) <= 80:
            return label.strip()
        clean = url.split("?", 1)[0].rstrip("/")
        fname = clean.split("/")[-1]
        return fname or "source"

    # Step 1: Check if custom_config has unparsed keys in `original` or `translated_vn`
    norm_config: dict[str, Any] | None = None
    extracted_images_from_config: list[dict[str, str]] = []

    if isinstance(custom_config, dict):
        raw_orig_list = custom_config.get("original")
        raw_trans_list = custom_config.get("translated_vn")

        if isinstance(raw_orig_list, list):
            temp_dict: dict[str, Any] = {}
            for item in raw_orig_list:
                if isinstance(item, dict):
                    k = item.get("key")
                    v = item.get("value")
                    if k:
                        temp_dict[str(k)] = v

            # If it has "images", extract source files
            if "images" in temp_dict:
                parsed_imgs = safe_parse_json(temp_dict["images"])
                if isinstance(parsed_imgs, list):
                    for img in parsed_imgs:
                        if isinstance(img, dict):
                            u = img.get("value") or img.get("src") or img.get("url")
                            if u and isinstance(u, str):
                                nu = normalize_url(u)
                                extracted_images_from_config.append({"name": source_name(nu, img.get("name") or img.get("label")), "url": nu})
                        elif isinstance(img, str) and img.strip():
                            nu = normalize_url(img)
                            extracted_images_from_config.append({"name": source_name(nu), "url": nu})

            has_unparsed_structure = any(k in temp_dict for k in ("options", "images", "canvas", "disable_make_change", "texts"))
            if has_unparsed_structure:
                clean_orig_entries = _parse_custom_config_dict(temp_dict)
            else:
                clean_orig_entries = [
                    CustomConfigEntry(key=item["key"], value=item["value"])
                    for item in raw_orig_list
                    if isinstance(item, dict) and item.get("key") and not _is_internal_or_price_key(item["key"], item.get("value", "")) and str(item["key"]).lower() not in ("disable_make_change", "images", "canvas", "texts", "options", "layers", "template_id")
                ]

            clean_trans_entries: list[CustomConfigEntry] = []
            if isinstance(raw_trans_list, list):
                temp_trans_dict: dict[str, Any] = {}
                for item in raw_trans_list:
                    if isinstance(item, dict):
                        k = item.get("key")
                        v = item.get("value")
                        if k:
                            temp_trans_dict[str(k)] = v
                if any(k in temp_trans_dict for k in ("options", "texts", "tắt_tính_năng_thay_đổi")):
                    clean_trans_entries = _parse_custom_config_dict(temp_trans_dict)
                else:
                    clean_trans_entries = [
                        CustomConfigEntry(key=item["key"], value=item["value"])
                        for item in raw_trans_list
                        if isinstance(item, dict) and item.get("key") and not _is_internal_or_price_key(item["key"], item.get("value", "")) and str(item["key"]).lower() not in ("disable_make_change", "tắt_tính_năng_thay_đổi", "images", "canvas", "texts", "options", "layers", "template_id")
                    ]

            norm_config = {
                "original": [e.model_dump() for e in clean_orig_entries],
                "translated_vn": [e.model_dump() for e in clean_trans_entries],
            }
        else:
            parsed = _parse_custom_config({"configurations": custom_config})
            norm_config = parsed.model_dump() if parsed else None

    # Step 2: Source Files Normalization
    norm_sources = list(source_files) if isinstance(source_files, list) else []

    if extracted_images_from_config and (not norm_sources or len(norm_sources) < len(extracted_images_from_config)):
        norm_sources = extracted_images_from_config
    elif not norm_sources and product_skus:
        extracted = extract_source_files({"product_skus": product_skus})
        if extracted:
            norm_sources = extracted

    return norm_config if (norm_config and (norm_config.get("original") or norm_config.get("translated_vn"))) else None, norm_sources if norm_sources else None


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
    """Extract list of customer uploaded source images/files and canvas image assets."""
    sources: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    def normalize_url(raw_url: str) -> str:
        u = raw_url.strip()
        if u.startswith("//"):
            return f"https:{u}"
        if u.startswith("/"):
            return f"https://assets.printerval.com{u}"
        return u

    def source_name(url: str, label: str | None = None) -> str:
        if label and not label.startswith("http") and "/" not in label and len(label.strip()) <= 80:
            return label.strip()
        clean = url.split("?", 1)[0].rstrip("/")
        fname = clean.split("/")[-1]
        return fname or "source"

    def add_source(url: Any, label: str | None = None) -> None:
        if not isinstance(url, str) or not url.strip():
            return
        clean_url = normalize_url(url)
        clean_lower = clean_url.lower()
        if not (clean_lower.startswith("http://") or clean_lower.startswith("https://")):
            return
        if clean_url in seen_urls:
            return
        seen_urls.add(clean_url)
        sources.append({"name": source_name(clean_url, label), "url": clean_url})

    def safe_parse_json(val: Any) -> Any:
        if isinstance(val, str):
            val_s = val.strip()
            if (val_s.startswith("{") and val_s.endswith("}")) or (val_s.startswith("[") and val_s.endswith("]")):
                try:
                    return json.loads(val_s)
                except (TypeError, ValueError):
                    return val
        return val

    # 1. From the SKU's own `configurations`
    meta = _meta_data(row)
    raw_skus = meta.get("product_skus")
    sku_entries = list(raw_skus.values()) if isinstance(raw_skus, dict) else []

    # Check `layers` first (authoritative when present e.g. DJ3976109)
    has_layers = False
    for sku_data in sku_entries:
        if not isinstance(sku_data, dict):
            continue
        raw_config = safe_parse_json(sku_data.get("configurations"))
        if not isinstance(raw_config, dict):
            continue
        layers = safe_parse_json(raw_config.get("layers"))
        if isinstance(layers, list) and layers:
            has_layers = True
            for layer in layers:
                if isinstance(layer, dict):
                    url = layer.get("value") or layer.get("src") or layer.get("url")
                    if isinstance(url, str) and url.strip():
                        clean_url = normalize_url(url)
                        sources.append({"name": source_name(clean_url, layer.get("name")), "url": clean_url})
                elif isinstance(layer, str) and layer.strip():
                    clean_url = normalize_url(layer)
                    sources.append({"name": source_name(clean_url), "url": clean_url})

    if has_layers:
        return sources if sources else None

    for sku_data in sku_entries:
        if not isinstance(sku_data, dict):
            continue
        raw_config = safe_parse_json(sku_data.get("configurations"))
        if not isinstance(raw_config, dict):
            continue

        # 1a. Images array (e.g. Customily 16 images in DJ4005539)
        images = safe_parse_json(raw_config.get("images"))
        if isinstance(images, list):
            for img_item in images:
                if isinstance(img_item, dict):
                    img_url = img_item.get("value") or img_item.get("src") or img_item.get("url")
                    add_source(img_url, img_item.get("name") or img_item.get("label"))
                elif isinstance(img_item, str):
                    add_source(img_item)

        # 1b. Options array (e.g. Customer uploaded image in option)
        options = safe_parse_json(raw_config.get("options"))
        if isinstance(options, list):
            for opt in options:
                if isinstance(opt, dict):
                    opt_val = opt.get("value")
                    opt_thumb = opt.get("thumb_image") or opt.get("preview")
                    opt_label = opt.get("label") or opt.get("name")
                    if isinstance(opt_val, str) and (opt_val.startswith("http") or opt_val.startswith("/customize/") or any(ext in opt_val.lower() for ext in (".jpg", ".jpeg", ".png", ".webp"))):
                        add_source(opt_val, opt_label)
                    elif isinstance(opt_thumb, str) and opt_thumb.startswith("http"):
                        add_source(opt_thumb, opt_label)

        # 1c. Direct key-values (e.g. {"Your Photo 1": {"type": "image", "value": "..."}})
        def collect_configuration_images(entry: Any, label: str | None = None) -> None:
            parsed = safe_parse_json(entry)
            if isinstance(parsed, dict):
                if parsed.get("type") == "image" or "value" in parsed or "src" in parsed:
                    url = parsed.get("value") or parsed.get("src") or parsed.get("url")
                    if isinstance(url, str) and (url.startswith("http") or url.startswith("/customize/")):
                        add_source(url, label)
                for nested_k, nested_v in parsed.items():
                    if nested_k in ("canvas", "disable_make_change", "texts", "template_id"):
                        continue
                    collect_configuration_images(nested_v, str(nested_k))
            elif isinstance(parsed, list):
                for nested_v in parsed:
                    collect_configuration_images(nested_v)

        for key, entry in raw_config.items():
            if key in ("images", "layers", "options", "canvas", "disable_make_change", "texts", "template_id"):
                continue
            collect_configuration_images(entry, str(key))

    # 2. From `designs` in row
    designs = row.get("designs")
    if isinstance(designs, list):
        for item in designs:
            if isinstance(item, dict):
                url = item.get("url") or item.get("image_url") or item.get("file_url")
                name = item.get("name") or item.get("file_name")
                add_source(url, name)
            elif isinstance(item, str):
                add_source(item)

    # 3. From `custom_design_files` / `attachments` / `source_files` in row
    attachments = row.get("custom_design_files") or row.get("attachments") or row.get("source_files")
    if isinstance(attachments, list):
        for item in attachments:
            if isinstance(item, dict):
                url = item.get("url") or item.get("file_url")
                name = item.get("name") or item.get("file_name")
                add_source(url, name)
            elif isinstance(item, str):
                add_source(item)

    # 4. Fallback: single personalization image
    if not sources:
        single_url = extract_source_asset_url(row)
        if single_url:
            add_source(single_url)

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

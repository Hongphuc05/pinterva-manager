from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

TARGET_STATUSES = ("done", "confirm", "review", "fix")
_PREVIEW_KEYS = (
    "thumbnail_url",
    "thumbnail",
    "thumb",
    "product_image",
    "product_thumbnail",
    "image",
    "image_url",
    "mockup_url",
    "mockup",
    "design_url",
    "artwork_url",
    "picture",
    "photo",
    "src",
    "ng_src",
    "avatar",
)
_NESTED_KEYS = ("item", "product", "attributes", "meta_data", "design", "mockup", "design_job")
_HTML_IMAGE_RE = re.compile(r'(?:ng-src|src)=["\']([^"\']+)["\']', re.IGNORECASE)


class RowNormalizationError(ValueError):
    def __init__(self, code: str, message: str, *, source_job_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.source_job_id = source_job_id


@dataclass(frozen=True)
class PreviewCandidate:
    raw_url: str
    url: str
    source_path: str


@dataclass(frozen=True)
class NormalizedJob:
    source_system: str
    source_job_id: str
    external_order_id: str
    status: str
    team_outsource: str
    job_type: str
    order_id: str | None
    product_name: str
    sku: str | None
    product_category: str | None
    note_outsource: str | None
    raw_preview_url: str | None
    preview_url: str | None
    preview_source_path: str | None
    preview_missing: bool
    source_payload_hash: str


def _meta_data(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("meta_data")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _looks_like_image_url(value: str) -> bool:
    value = value.strip()
    if not value or any(token in value.lower() for token in ("flag", "us-flag", "us.png", "icon")):
        return False
    return value.startswith(("http://", "https://", "//", "/")) or "assets.printerval.com" in value.lower()


def normalize_image_url(raw_url: str) -> str:
    """Mirror the URL normalization used by the current Waiting asset helper."""
    url = raw_url.strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith(("http://", "https://")):
        return url

    clean = url.lstrip("/")
    if "assets.printerval.com" in clean:
        return f"https://gdn.printerval.com/unsafe/600x0/{clean}"
    return f"https://printerval.com/{clean}"


def _candidate_from_string(value: str, path: str) -> PreviewCandidate | None:
    text = value.strip()
    if not text:
        return None

    html_match = _HTML_IMAGE_RE.search(text)
    if html_match and _looks_like_image_url(html_match.group(1)):
        raw_url = html_match.group(1).strip()
        return PreviewCandidate(raw_url, normalize_image_url(raw_url), f"{path}.html")

    if text.startswith(("{", "[")):
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            return _find_preview(parsed, path)

    if _looks_like_image_url(text):
        return PreviewCandidate(text, normalize_image_url(text), path)
    return None


def _find_preview(value: Any, path: str = "row") -> PreviewCandidate | None:
    if isinstance(value, str):
        return _candidate_from_string(value, path)

    if isinstance(value, dict):
        keys_by_lower = {str(key).lower(): key for key in value}
        for preferred in _PREVIEW_KEYS:
            actual_key = keys_by_lower.get(preferred)
            if actual_key is None:
                continue
            candidate = _find_preview(value[actual_key], f"{path}.{actual_key}")
            if candidate:
                return candidate

        for nested_key in _NESTED_KEYS:
            actual_key = keys_by_lower.get(nested_key)
            if actual_key is None:
                continue
            candidate = _find_preview(value[actual_key], f"{path}.{actual_key}")
            if candidate:
                return candidate

        return None

    if isinstance(value, list):
        for index, item in enumerate(value):
            candidate = _find_preview(item, f"{path}[{index}]")
            if candidate:
                return candidate
    return None


def extract_preview_candidate(row: dict[str, Any]) -> PreviewCandidate | None:
    """Extract the same preview candidate used by the production Waiting crawl."""
    return _find_preview(row)


def _external_order_id(row: dict[str, Any]) -> tuple[str, str]:
    for key in ("code", "job_code", "external_order_id"):
        value = row.get(key)
        if value is not None and str(value).strip():
            code = str(value).strip()
            source_job_id = code[2:] if code.upper().startswith("DJ") else code
            return code if code.upper().startswith("DJ") else f"DJ{code}", source_job_id

    raw_id = row.get("id")
    if raw_id is None or not str(raw_id).strip():
        raise RowNormalizationError("missing_source_job_id", "Printerval row has no usable id")
    source_job_id = str(raw_id).strip()
    return f"DJ{source_job_id}", source_job_id


def _product_fields(row: dict[str, Any]) -> tuple[str, str | None, str | None]:
    product = row.get("product") if isinstance(row.get("product"), dict) else {}
    meta = _meta_data(row)
    product_name = str(
        product.get("name")
        or meta.get("product_name")
        or row.get("product_name")
        or row.get("name")
        or "Đơn 2D Custom"
    ).strip()
    sku = product.get("sku") or row.get("sku")
    category = product.get("category_name") or product.get("category") or row.get("product_category")
    return product_name, str(sku).strip() if sku is not None and str(sku).strip() else None, (
        str(category).strip() if category is not None and str(category).strip() else None
    )


def _order_id(row: dict[str, Any]) -> str | None:
    meta = _meta_data(row)
    raw_skus = meta.get("product_skus")
    sku_rows = list(raw_skus.values()) if isinstance(raw_skus, dict) else []
    for value in sku_rows:
        if isinstance(value, dict) and value.get("order_id") is not None:
            return str(value["order_id"]).strip() or None
    for key in ("order_id", "external_order_id"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _note_outsource(row: dict[str, Any]) -> str | None:
    attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
    for value in (
        attributes.get("outsource_note"),
        row.get("note_outsource"),
        row.get("outsource_note"),
    ):
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _payload_hash(row: dict[str, Any]) -> str:
    encoded = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalize_row(row: dict[str, Any], *, team_outsource: str, job_type: str = "all") -> NormalizedJob:
    if not isinstance(row, dict):
        raise RowNormalizationError("invalid_row", "Printerval result item is not an object")

    external_order_id, source_job_id = _external_order_id(row)
    status = str(row.get("status") or "").strip().lower()
    if status not in TARGET_STATUSES:
        raise RowNormalizationError(
            "unexpected_status",
            f"Row status {status!r} is outside the historical target set",
            source_job_id=source_job_id,
        )

    product_name, sku, category = _product_fields(row)
    preview = extract_preview_candidate(row)
    return NormalizedJob(
        source_system="printerval",
        source_job_id=source_job_id,
        external_order_id=external_order_id,
        status=status,
        team_outsource=team_outsource,
        job_type=job_type,
        order_id=_order_id(row),
        product_name=product_name,
        sku=sku,
        product_category=category,
        note_outsource=_note_outsource(row),
        raw_preview_url=preview.raw_url if preview else None,
        preview_url=preview.url if preview else None,
        preview_source_path=preview.source_path if preview else None,
        preview_missing=preview is None,
        source_payload_hash=_payload_hash(row),
    )

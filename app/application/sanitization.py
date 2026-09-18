from __future__ import annotations

import base64
import json
import re
from typing import Any
from pydantic import BaseModel


def encode_proxy_url(raw_url: str | None) -> str | None:
    if not raw_url or not isinstance(raw_url, str):
        return raw_url
    url = raw_url.strip()
    if not url:
        return url
    if url.startswith(("/crawled_assets/", "/order_assets/", "/assets/")):
        return url
    if "printerval" in url.lower():
        encoded = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii")
        return f"/api/assets/proxy?u={encoded}"
    return url


def decode_proxy_url(encoded_u: str | None) -> str | None:
    if not encoded_u or not isinstance(encoded_u, str):
        return None
    try:
        raw = base64.urlsafe_b64decode(encoded_u.encode("ascii")).decode("utf-8")
        if raw.startswith(("http://", "https://")):
            return raw
    except Exception:
        pass
    return None


def sanitize_text(text: str | None, replacement: str = "Hệ thống mẹ") -> str | None:
    if text is None or not isinstance(text, str):
        return text
    # Replace Printerval with neutral terms
    cleaned = re.sub(r"printerval", replacement, text, flags=re.IGNORECASE)
    cleaned = re.sub(r"https?://[^\s]*printerval[^\s]*", "", cleaned, flags=re.IGNORECASE)
    return cleaned


def sanitize_source_files(source_files: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not source_files or not isinstance(source_files, list):
        return source_files
    cleaned_sources = []
    for item in source_files:
        if isinstance(item, dict):
            name = item.get("name") or "source"
            name = sanitize_text(str(name), "source")
            url = encode_proxy_url(item.get("url"))
            cleaned_sources.append({"name": name, "url": url or ""})
        else:
            cleaned_sources.append(item)
    return cleaned_sources


def sanitize_custom_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    if not config or not isinstance(config, dict):
        return config

    def _sanitize_val(val: Any) -> Any:
        if isinstance(val, str):
            if "printerval" in val.lower():
                if val.strip().startswith(("http://", "https://")):
                    return encode_proxy_url(val)
                return sanitize_text(val, "Web mẹ")
            return val
        elif isinstance(val, dict):
            return {
                sanitize_text(str(k), "tùy_chọn"): _sanitize_val(v)
                for k, v in val.items()
            }
        elif isinstance(val, list):
            return [_sanitize_val(item) for item in val]
        return val

    return _sanitize_val(config)


class DesignerOrderSummaryOut(BaseModel):
    id: Any
    external_order_id: str
    state: str
    work_domain: str = "standard"
    batch_id: Any | None = None
    product_name: str | None = None
    sku: str | None = None
    thumbnail_url: str | None = None
    assigned_designer_name: str | None = None
    assigned_designer_id: Any | None = None
    assignment_id: Any | None = None
    product_skus: list[dict] | None = None
    order_created_at_ext: Any | None = None
    deadline_at_ext: Any | None = None
    created_at: Any | None = None
    status_changed_at: Any | None = None
    note_outsource: str = ""
    previous_note_outsource: str | None = None
    fix_approved_by_admin: bool = False
    fix_rejected_by_admin: bool = False
    designer_note: str = ""
    template_missing: bool = False
    duplicate_check_status: str = "uncheck"
    sku_image_url: str | None = None
    source_files: list[dict] | None = None
    product_image_urls: list[str] | None = None
    is_paid: bool = False
    paid_at: Any | None = None
    review_submitted_at: Any | None = None


class DesignerOrderDetailOut(BaseModel):
    id: Any
    external_order_id: str
    state: str
    work_domain: str = "standard"
    batch_id: Any | None = None
    product_name: str | None = None
    sku: str | None = None
    product_category: str | None = None
    product_variants: list[dict] | None = None
    multiple_design: bool = False
    double_sided: bool = False
    priority_label: str | None = None
    deadline_at_ext: Any | None = None
    order_created_at_ext: Any | None = None
    created_at_ext: Any | None = None
    created_at: Any | None = None
    status_changed_at: Any | None = None
    note_outsource: str = ""
    previous_note_outsource: str | None = None
    fix_approved_by_admin: bool = False
    fix_rejected_by_admin: bool = False
    designer_note: str = ""
    template_missing: bool = False
    duplicate_check_status: str = "uncheck"
    custom_config: dict | None = None
    product_skus: list[dict] | None = None
    assigned_designer_name: str | None = None
    assignment_id: Any | None = None
    sub_status: str | None = None
    result_versions: list[Any] = []
    sku_image_url: str | None = None
    thumbnail_url: str | None = None
    source_files: list[dict] | None = None
    product_image_urls: list[str] | None = None


def sanitize_order_summary_for_designer(item: Any) -> Any:
    """Sanitizes an OrderSummaryOut instance or dict for designer view."""
    item_dict = item.model_dump() if isinstance(item, BaseModel) else dict(item)
    for k in [
        "external_order_url",
        "printerval_designer",
        "printerval_status",
        "printerval_status_synced_at",
        "printerval_assignment_lifecycle",
        "printerval_assignment_error",
        "source_download_all_url",
        "design_tool_url",
    ]:
        item_dict.pop(k, None)

    if item_dict.get("product_name"):
        item_dict["product_name"] = sanitize_text(item_dict["product_name"], "")
    if item_dict.get("sku"):
        item_dict["sku"] = sanitize_text(item_dict["sku"], "")
    if item_dict.get("thumbnail_url"):
        item_dict["thumbnail_url"] = encode_proxy_url(item_dict["thumbnail_url"])
    if item_dict.get("sku_image_url"):
        item_dict["sku_image_url"] = encode_proxy_url(item_dict["sku_image_url"])
    if item_dict.get("product_image_urls"):
        item_dict["product_image_urls"] = [
            encode_proxy_url(u) for u in item_dict["product_image_urls"] if u
        ]
    if item_dict.get("source_files"):
        item_dict["source_files"] = sanitize_source_files(item_dict["source_files"])
    if item_dict.get("note_outsource"):
        item_dict["note_outsource"] = sanitize_text(item_dict["note_outsource"], "Web mẹ")
    if item_dict.get("previous_note_outsource"):
        item_dict["previous_note_outsource"] = sanitize_text(
            item_dict["previous_note_outsource"], "Web mẹ"
        )
    return DesignerOrderSummaryOut(**item_dict)


def sanitize_order_detail_for_designer(item: Any) -> Any:
    """Sanitizes an OrderDetailOut instance for designer view."""
    item_dict = item.model_dump() if isinstance(item, BaseModel) else dict(item)
    for k in [
        "external_order_url",
        "printerval_designer",
        "printerval_status",
        "source_download_all_url",
        "design_tool_url",
    ]:
        item_dict.pop(k, None)

    if item_dict.get("product_name"):
        item_dict["product_name"] = sanitize_text(item_dict["product_name"], "")
    if item_dict.get("sku"):
        item_dict["sku"] = sanitize_text(item_dict["sku"], "")
    if item_dict.get("thumbnail_url"):
        item_dict["thumbnail_url"] = encode_proxy_url(item_dict["thumbnail_url"])
    if item_dict.get("sku_image_url"):
        item_dict["sku_image_url"] = encode_proxy_url(item_dict["sku_image_url"])
    if item_dict.get("product_image_urls"):
        item_dict["product_image_urls"] = [
            encode_proxy_url(u) for u in item_dict["product_image_urls"] if u
        ]
    if item_dict.get("source_files"):
        item_dict["source_files"] = sanitize_source_files(item_dict["source_files"])
    if item_dict.get("custom_config"):
        item_dict["custom_config"] = sanitize_custom_config(item_dict["custom_config"])
    if item_dict.get("note_outsource"):
        item_dict["note_outsource"] = sanitize_text(item_dict["note_outsource"], "Web mẹ")
    if item_dict.get("previous_note_outsource"):
        item_dict["previous_note_outsource"] = sanitize_text(
            item_dict["previous_note_outsource"], "Web mẹ"
        )
    return DesignerOrderDetailOut(**item_dict)


def sanitize_workflow_event_for_designer(event: Any) -> Any:
    """Sanitizes a WorkflowEventOut instance or dict for designer view."""
    if isinstance(event, BaseModel):
        if event.actor_name and "printerval" in event.actor_name.lower():
            event.actor_name = "Hệ thống mẹ"
        if event.description:
            event.description = sanitize_text(event.description, "Hệ thống mẹ")
        if event.evidence and isinstance(event.evidence, dict):
            clean_ev = {}
            for k, v in event.evidence.items():
                if "printerval" in str(k).lower():
                    continue
                if isinstance(v, str):
                    if "printerval" in v.lower():
                        v = sanitize_text(v, "Hệ thống mẹ")
                clean_ev[k] = v
            event.evidence = clean_ev
    elif isinstance(event, dict):
        if event.get("actor_name") and "printerval" in str(event["actor_name"]).lower():
            event["actor_name"] = "Hệ thống mẹ"
        if event.get("description"):
            event["description"] = sanitize_text(event["description"], "Hệ thống mẹ")
        if event.get("evidence") and isinstance(event["evidence"], dict):
            clean_ev = {}
            for k, v in event["evidence"].items():
                if "printerval" in str(k).lower():
                    continue
                if isinstance(v, str):
                    if "printerval" in v.lower():
                        v = sanitize_text(v, "Hệ thống mẹ")
                clean_ev[k] = v
            event["evidence"] = clean_ev
    return event


def sanitize_platform_for_designer(platform_out: Any) -> Any:
    """Sanitizes PlatformOut instance or dict for designer view."""
    if isinstance(platform_out, BaseModel):
        if platform_out.account_username:
            platform_out.account_username = re.sub(
                r"@.*printerval.*", "@gmail.com", platform_out.account_username, flags=re.IGNORECASE
            )
        if platform_out.name:
            platform_out.name = sanitize_text(platform_out.name, "Acc Mẹ") or platform_out.name
        platform_out.team_outsource = None
    elif isinstance(platform_out, dict):
        if platform_out.get("account_username"):
            platform_out["account_username"] = re.sub(
                r"@.*printerval.*", "@gmail.com", str(platform_out["account_username"]), flags=re.IGNORECASE
            )
        if platform_out.get("name"):
            platform_out["name"] = sanitize_text(str(platform_out["name"]), "Acc Mẹ") or platform_out["name"]
        platform_out["team_outsource"] = None
    return platform_out

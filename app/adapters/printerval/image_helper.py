from __future__ import annotations

import csv
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CRAWLED_ASSETS_DIR = Path("crawled_assets")
CSV_FILE_PATH = Path("crawled_orders.csv")


def extract_image_url_from_dict_or_html(data: dict[str, Any] | str | None) -> str | None:
    """Extract image URL from API dictionary or HTML markup string."""
    if not data:
        return None

    if isinstance(data, dict):
        for key in (
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
        ):
            val = data.get(key)
            if val and isinstance(val, str) and val.strip():
                if not any(ignored in val.lower() for ignored in ["flag", "us-flag", "us.png", "icon"]):
                    return val.strip()

        for sub_key in ("item", "product", "attributes", "meta_data", "templateJobs", "design", "mockup", "design_job"):
            sub_val = data.get(sub_key)
            if isinstance(sub_val, dict):
                res = extract_image_url_from_dict_or_html(sub_val)
                if res:
                    return res
            elif isinstance(sub_val, list):
                for elem in sub_val:
                    if isinstance(elem, (dict, str)):
                        res = extract_image_url_from_dict_or_html(elem)
                        if res:
                            return res
            elif isinstance(sub_val, str) and sub_val.strip():
                # 1. Try HTML regex extraction first
                res = extract_image_url_from_dict_or_html(sub_val)
                if res:
                    return res
                # 2. Try JSON parsing if string contains JSON
                if "{" in sub_val or "image" in sub_val or "http" in sub_val:
                    try:
                        import json
                        meta_dict = json.loads(sub_val)
                        res = extract_image_url_from_dict_or_html(meta_dict)
                        if res:
                            return res
                    except Exception:
                        pass
        return None

    if isinstance(data, str):
        match = re.search(r'(?:ng-src|src)=["\']([^"\']+)["\']', data, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        if data.strip().startswith("http") or "assets.printerval.com" in data:
            return data.strip()
    return None


def normalize_image_url(raw_url: str) -> str:
    """Normalize raw URL or relative asset path into a downloadable HTTP/HTTPS URL."""
    url = raw_url.strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("http://") or url.startswith("https://"):
        return url

    url_clean = url.lstrip("/")
    if "assets.printerval.com" in url_clean:
        return f"https://gdn.printerval.com/unsafe/600x0/{url_clean}"

    return f"https://printerval.com/{url_clean}"


def download_and_save_image(
    external_order_id: str,
    raw_url: str,
    assets_dir: Path = CRAWLED_ASSETS_DIR,
    platform_id: str | None = None,
) -> str | None:
    """Download image from raw_url, save to assets_dir/[platform_id/]{external_order_id}.png,
    and return web access path '/crawled_assets/[platform_id/]{external_order_id}.png'."""
    if not external_order_id or not raw_url:
        return None

    # If it's already a local web path, return it directly
    if raw_url.startswith("/crawled_assets/"):
        return raw_url

    target_dir = assets_dir / str(platform_id) if platform_id else assets_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    full_url = normalize_image_url(raw_url)

    ext = ".png"
    lower_url = full_url.lower()
    if ".jpg" in lower_url or ".jpeg" in lower_url:
        ext = ".jpg"
    elif ".webp" in lower_url:
        ext = ".webp"

    file_path = target_dir / f"{external_order_id}{ext}"
    web_path = (
        f"/crawled_assets/{platform_id}/{external_order_id}{ext}"
        if platform_id
        else f"/crawled_assets/{external_order_id}{ext}"
    )

    try:
        with httpx.Client(
            timeout=15.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            },
        ) as client:
            resp = client.get(full_url)
            if resp.status_code == 200 and resp.content:
                file_path.write_bytes(resp.content)
                logger.info(
                    "Successfully downloaded image for order %s to %s",
                    external_order_id,
                    file_path,
                )
                return web_path
    except Exception as exc:
        logger.warning(
            "Failed to download image for order %s from %s: %s",
            external_order_id,
            full_url,
            exc,
        )

    return None


def append_to_crawled_orders_csv(
    external_order_id: str,
    product_name: str | None = None,
    sku: str | None = None,
    product_category: str | None = None,
    status: str | None = None,
    batch_id: str | None = None,
    thumbnail_url: str | None = None,
    local_image_path: str | None = None,
    csv_path: Path = CSV_FILE_PATH,
    platform_id: str | None = None,
) -> None:
    """Append order crawl metadata and local image path to platform-specific CSV."""
    if not external_order_id:
        return

    if platform_id:
        target_dir = CRAWLED_ASSETS_DIR / str(platform_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_csv_path = target_dir / "crawled_orders.csv"
    else:
        target_csv_path = csv_path

    file_exists = target_csv_path.exists()
    fieldnames = [
        "external_order_id",
        "product_name",
        "sku",
        "product_category",
        "status",
        "batch_id",
        "thumbnail_url",
        "local_image_path",
        "crawled_at",
    ]

    try:
        with open(target_csv_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(
                {
                    "external_order_id": external_order_id,
                    "product_name": product_name or "",
                    "sku": sku or "",
                    "product_category": product_category or "",
                    "status": status or "",
                    "batch_id": batch_id or "",
                    "thumbnail_url": thumbnail_url or "",
                    "local_image_path": local_image_path or "",
                    "crawled_at": datetime.now().isoformat(),
                }
            )
    except Exception as exc:
        logger.warning("Failed to write order %s to CSV: %s", external_order_id, exc)

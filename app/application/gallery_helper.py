from __future__ import annotations

import re
from urllib.parse import urlparse


_MALFORMED_PRINTERVAL_PLACEHOLDER_URL = re.compile(
    r"^https?://(?:www\.)?printerval\.com(?:data:|blob:|javascript:|about:)",
    re.IGNORECASE,
)


def is_allowed_gallery_url(raw_url: str) -> bool:
    """Accept displayable gallery URLs and reject lazy-load placeholders.

    A browser page can expose an ``img`` whose ``src`` is a ``data:`` or ``blob:``
    placeholder.  Older gallery extractors prefixed that value with the product
    host, producing URLs such as ``https://printerval.comdata:image/...``.  They
    look like HTTP URLs but can never resolve to an image.
    """
    url = raw_url.strip()
    if not url:
        return False

    lowered = url.lower()
    if lowered.startswith(("/crawled_assets/", "/assets/", "/order_assets/")):
        return True
    if lowered.startswith("data:image/"):
        return True
    if _MALFORMED_PRINTERVAL_PLACEHOLDER_URL.match(url):
        return False

    parsed = urlparse(url)
    return parsed.scheme in ("https", "http") and bool(parsed.hostname)


def canonicalize_gallery_url(raw_url: str) -> tuple[str, str]:
    """Return (canonical_dedup_key, standardized_url) for any image URL.

    Normalizes Printerval and eBay URLs to valid, high-resolution direct asset links,
    and returns a canonical key to eliminate proxy/thumbnail duplicates.
    """
    url = raw_url.strip()
    if not url:
        return ("", "")

    # 1. Printerval asset
    prin_match = re.search(
        r"(?:https?:)?(?://)?(?:assets\.printerval\.com|printervalcdn\.com|cdn\.printerval\.com)/(?:unsafe/[^/]+/)?(?:assets\.printerval\.com/)?(.+)",
        url,
        re.IGNORECASE,
    )
    if prin_match:
        rel_path = prin_match.group(1).lstrip("/")
        rel_path = re.sub(r"^unsafe/[^/]+/", "", rel_path)
        rel_path = re.sub(r"^assets\.printerval\.com/", "", rel_path)
        rel_path = rel_path.split("?")[0].split("#")[0]
        canonical_key = f"prin:{rel_path.lower()}"

        if rel_path.startswith("asset/"):
            standard_url = f"https://cdn.printerval.com/unsafe/960x960/{rel_path}"
        elif rel_path.startswith("image/") or rel_path.startswith("sticker/"):
            standard_url = f"https://cdn.printerval.com/{rel_path}"
        else:
            # Direct original asset on assets.printerval.com
            standard_url = f"https://assets.printerval.com/{rel_path}"
        return (canonical_key, standard_url)

    # 2. eBay asset
    ebay_match = re.search(r"i\.ebayimg\.com/(?:thumbs/)?images/([^/]+/[^/]+)", url, re.IGNORECASE)
    if ebay_match:
        img_path = ebay_match.group(1)
        canonical_key = f"ebay:{img_path.lower()}"
        standard_url = f"https://i.ebayimg.com/images/{img_path}/s-l1600.webp"
        return (canonical_key, standard_url)

    # 3. Generic URL
    clean = url.split("?")[0].split("#")[0]
    return (clean.lower(), url)


def deduplicate_gallery_urls(urls: list[str] | None) -> list[str]:
    """Deduplicate a list of image URLs preserving order, using canonical image signatures."""
    if not urls:
        return []
    seen = set()
    result = []
    for u in urls:
        if not isinstance(u, str) or not u.strip():
            continue
        if not is_allowed_gallery_url(u):
            continue
        key, standard_url = canonicalize_gallery_url(u)
        if key and key not in seen:
            seen.add(key)
            result.append(standard_url)
    return result

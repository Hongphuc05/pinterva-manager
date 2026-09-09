from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from typing import Any

logger = logging.getLogger(__name__)

JUNK_KEYWORDS = ("avatar", "gift", "banner", "icon", "badge", "flag")
GALLERY_SELECTORS = (
    ".product-gallery-item-image",
    ".product-thumbnail-slide img",
    ".product-image-container img",
    ".main-image img",
)


def normalize_gallery_image_url(src: str) -> str:
    clean = src.strip()
    if clean.startswith("//"):
        clean = f"https:{clean}"
    elif not clean.startswith("http"):
        clean = f"https://printerval.com{clean}" if clean.startswith("/") else f"https://{clean}"
    # Upgrade thumbnail resolution to 960x960 as done in CopyImage extension
    clean = re.sub(r"/unsafe/[^/]+/", "/unsafe/960x960/", clean)
    return clean


class _GalleryHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.image_urls: list[str] = []
        self._tag_stack: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        tag_classes = attr_dict.get("class", "").split()
        self._tag_stack.append({"tag": tag, "classes": tag_classes})

        if tag == "img":
            # Check if this img or any parent has relevant gallery classes
            is_gallery_candidate = False
            for cls in (
                "product-gallery-item-image",
                "product-thumbnail-slide",
                "product-image-container",
                "main-image",
                "gallery",
            ):
                if any(cls in frame["classes"] for frame in self._tag_stack):
                    is_gallery_candidate = True
                    break

            # Also check if image src is an assets.printerval.com URL
            src_val = (
                attr_dict.get("data-src")
                or attr_dict.get("loading-src")
                or attr_dict.get("src")
                or attr_dict.get("ng-src")
            )
            if src_val:
                src_str = src_val.strip()
                if "assets.printerval.com" in src_str or "gdn.printerval.com" in src_str:
                    is_gallery_candidate = True

                if is_gallery_candidate:
                    src_lower = src_str.lower()
                    if not any(k in src_lower for k in JUNK_KEYWORDS):
                        self.image_urls.append(normalize_gallery_image_url(src_str))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._tag_stack) - 1, -1, -1):
            if self._tag_stack[i]["tag"] == tag:
                self._tag_stack.pop(i)
                break


def extract_gallery_images_from_html(
    html: str | None,
    fallback_image_url: str | None = None,
) -> list[str]:
    """Extract and deduplicate gallery image URLs from product page HTML.
    Mirrors the exact extraction & cleaning algorithm in the CopyImage extension.
    """
    if not html or not html.strip():
        return [fallback_image_url] if fallback_image_url else []

    try:
        parser = _GalleryHTMLParser()
        parser.feed(html)
        images = parser.image_urls

        # If parser found none through strict class checks, fallback to regex for assets.printerval
        if not images:
            raw_matches = re.findall(
                r'(?:src|data-src|loading-src|ng-src)=["\']([^"\']*(?:assets\.printerval\.com|gdn\.printerval\.com)[^"\']*)["\']',
                html,
                re.IGNORECASE,
            )
            for m in raw_matches:
                m_clean = m.strip()
                m_lower = m_clean.lower()
                if not any(k in m_lower for k in JUNK_KEYWORDS):
                    images.append(normalize_gallery_image_url(m_clean))

        # Deduplicate preserving order
        unique_urls = list(dict.fromkeys(images))
        if unique_urls:
            return unique_urls
    except Exception as exc:
        logger.warning("Error parsing gallery images from HTML: %s", exc)

    return [fallback_image_url] if fallback_image_url else []


PLAYWRIGHT_EXTRACT_GALLERY_SNIPPET = """
async (salesUrl) => {
    try {
        const absoluteUrl = salesUrl.startsWith('http') ? salesUrl : ('https://printerval.com' + salesUrl);
        const res = await fetch(absoluteUrl, { method: 'GET', credentials: 'include' });
        if (!res.ok) {
            return { success: false, status: res.status, images: [] };
        }
        const html = await res.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        const imgElements = doc.querySelectorAll('.product-gallery-item-image, .product-thumbnail-slide img, .product-image-container img, .main-image img');
        
        let rawImgs = [];
        imgElements.forEach(img => {
            const src = img.getAttribute('src') || img.getAttribute('data-src') || img.getAttribute('loading-src') || img.getAttribute('ng-src');
            if (src) rawImgs.push(src);
        });

        const junkKeywords = ['avatar', 'gift', 'banner', 'icon', 'badge', 'flag'];
        let normalizedImgs = [];
        rawImgs.forEach(src => {
            const hasJunk = junkKeywords.some(k => src.toLowerCase().includes(k));
            if (!hasJunk) {
                let cleanSrc = src.startsWith('http') ? src : (src.startsWith('//') ? 'https:' + src : 'https://printerval.com' + src);
                cleanSrc = cleanSrc.replace(/\\/unsafe\\/[^\\/]+\\//, '/unsafe/960x960/');
                normalizedImgs.push(cleanSrc);
            }
        });

        const uniqueImgs = [...new Set(normalizedImgs)];
        return { success: true, images: uniqueImgs };
    } catch (e) {
        return { success: false, error: String(e), images: [] };
    }
}
"""

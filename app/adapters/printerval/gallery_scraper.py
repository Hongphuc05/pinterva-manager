from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from typing import Any

logger = logging.getLogger(__name__)

JUNK_KEYWORDS = (
    "avatar",
    "gift",
    "banner",
    "icon",
    "badge",
    "flag",
    "product-ads",
    "logo",
    "paypal",
    "screenshot-",
    "files/2020-",
    "files/product/",
)
GALLERY_SELECTORS = (
    'img[data-loading*="ProductGallery"]',
    'img[data-loading*="fancyLoadingProductGallery"]',
    ".product-gallery-item-image",
    ".product-thumbnail-slide img",
    ".product-image-container img",
    ".main-image img",
    ".product-gallery img",
)


def normalize_gallery_image_url(src: str) -> str:
    clean = src.strip()
    if clean.startswith("//"):
        clean = f"https:{clean}"
    elif not clean.startswith("http"):
        clean = f"https://printerval.com{clean}" if clean.startswith("/") else f"https://{clean}"
    # Upgrade thumbnail resolution to 960x960 for crystal-clear preview
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
            data_loading = str(attr_dict.get("data-loading") or "").strip().lower()
            is_gallery_candidate = "productgallery" in data_loading or "fancyloadingproductgallery" in data_loading

            if not is_gallery_candidate:
                # Check if this img or any parent has relevant gallery classes
                for cls in (
                    "product-gallery-item-image",
                    "product-thumbnail-slide",
                    "product-image-container",
                    "main-image",
                    "gallery",
                    "product-gallery",
                    "product-images",
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
                src_lower = src_str.lower()
                if ("assets.printerval.com" in src_str or "gdn.printerval.com" in src_str or "cdn.printerval.com" in src_str):
                    if "custom-product" in src_lower or is_gallery_candidate:
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
    """Extract and deduplicate gallery image URLs from product page HTML."""
    if not html or not html.strip():
        return [fallback_image_url] if fallback_image_url else []

    try:
        parser = _GalleryHTMLParser()
        parser.feed(html)
        images = parser.image_urls

        # If parser found none through strict class checks, fallback to regex for assets.printerval
        if not images:
            raw_matches = re.findall(
                r'(?:src|data-src|loading-src|ng-src)=["\']([^"\']*(?:assets\.printerval\.com|gdn\.printerval\.com|cdn\.printerval\.com)[^"\']*)["\']',
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

        let rawImgs = [];

        // 1. Primary: Match gallery images by specific data-loading attribute in order
        const galleryImgs = doc.querySelectorAll('img[data-loading*="fancyLoadingProductGallery"], img[data-loading*="ProductGallery"]');
        galleryImgs.forEach(img => {
            const src = img.getAttribute('src') || img.getAttribute('data-src') || img.getAttribute('loading-src') || img.getAttribute('ng-src');
            if (src) rawImgs.push(src);
        });

        // 2. Secondary: If none found, match standard gallery container elements
        if (rawImgs.length === 0) {
            const containerImgs = doc.querySelectorAll('.product-gallery-item-image, .product-thumbnail-slide img, .product-image-container img, .main-image img, .product-gallery img');
            containerImgs.forEach(img => {
                const src = img.getAttribute('src') || img.getAttribute('data-src') || img.getAttribute('loading-src') || img.getAttribute('ng-src');
                if (src) rawImgs.push(src);
            });
        }

        // 3. Fallback: Search for custom-product images or product assets
        if (rawImgs.length === 0) {
            doc.querySelectorAll('img').forEach(img => {
                const src = img.getAttribute('src') || img.getAttribute('data-src') || img.getAttribute('loading-src') || img.getAttribute('ng-src') || '';
                if (src.includes('custom-product') || (src.includes('assets.printerval.com') && !src.includes('product-ads') && !src.includes('logo'))) {
                    rawImgs.push(src);
                }
            });
        }

        const junkKeywords = ['avatar', 'gift', 'banner', 'icon', 'badge', 'flag', 'product-ads', 'logo', 'paypal', 'screenshot-'];
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

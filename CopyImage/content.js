// Tacahu POD - Printerval Gallery Sync & Copy Tool
// Content Script

(function () {
    'use strict';

    let scanIntervalId = null;
    let isBatchRunning = false;
    let cachedSettings = {
        apiBaseUrl: "https://tacahu.fun",
        autoScanOnLoad: false,
        maxConcurrency: 5,
    };

    function getEnvBadgeHtml(apiUrl) {
        const raw = (apiUrl || '').trim();
        const isLocal = !raw || raw.includes('localhost') || raw.includes('127.0.0.1');
        if (isLocal) {
            return `<span id="tacahu-env-badge" style="
                font-size: 11px;
                font-weight: 700;
                padding: 2px 7px;
                border-radius: 6px;
                background: rgba(56, 189, 248, 0.15);
                color: #38bdf8;
                border: 1px solid rgba(56, 189, 248, 0.35);
                display: inline-flex;
                align-items: center;
                gap: 4px;
                white-space: nowrap;
            " title="${raw || 'http://localhost:8000'}">💻 Local</span>`;
        }
        let host = 'tacahu.fun';
        try {
            const u = new URL(raw.startsWith('http') ? raw : 'https://' + raw);
            host = u.host;
        } catch (e) {
            host = raw.replace(/^https?:\/\//, '').split('/')[0];
        }
        return `<span id="tacahu-env-badge" style="
            font-size: 11px;
            font-weight: 700;
            padding: 2px 7px;
            border-radius: 6px;
            background: rgba(74, 222, 128, 0.15);
            color: #4ade80;
            border: 1px solid rgba(74, 222, 128, 0.35);
            display: inline-flex;
            align-items: center;
            gap: 4px;
            white-space: nowrap;
        " title="${raw}">🌐 VPS: ${host}</span>`;
    }

    function updateEnvBadge() {
        const badgeEl = document.getElementById('tacahu-env-badge');
        if (badgeEl) {
            const temp = document.createElement('div');
            temp.innerHTML = getEnvBadgeHtml(cachedSettings.apiBaseUrl);
            const newBadge = temp.firstElementChild;
            if (newBadge) {
                badgeEl.replaceWith(newBadge);
            }
        }
    }

    // Load initial settings
    try {
        if (isExtensionAlive()) {
            chrome.runtime.sendMessage({ action: "GET_SETTINGS" }, (res) => {
                if (res && res.success && res.data) {
                    cachedSettings = { ...cachedSettings, ...res.data };
                    updateEnvBadge();
                    if (cachedSettings.autoScanOnLoad) {
                        setTimeout(() => {
                            runBatchScan();
                        }, 2500);
                    }
                }
            });
        }
    } catch (e) { }

    // Initialize UI
    setTimeout(() => {
        injectControlBar();
        injectButtonsToRows();
        scanIntervalId = setInterval(() => {
            if (!document.getElementById('tacahu-control-bar')) {
                injectControlBar();
            }
            injectButtonsToRows();
        }, 2000);
    }, 1200);

    // Listen to background triggers
    try {
        chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
            if (message.action === "TRIGGER_BATCH_SCAN") {
                runBatchScan();
                sendResponse({ success: true });
            }
        });
    } catch (e) { }

    function isExtensionAlive() {
        return !!(window.chrome && chrome.runtime && chrome.runtime.id);
    }

    let isControlBarCollapsed = sessionStorage.getItem('tacahu_sync_collapsed') === '1';

    function applyControlBarState(bar) {
        if (!bar) return;
        const fullContent = bar.querySelector('#tacahu-bar-full');
        const miniContent = bar.querySelector('#tacahu-bar-mini');

        if (isControlBarCollapsed) {
            bar.style.width = '42px';
            bar.style.height = '42px';
            bar.style.padding = '0';
            bar.style.borderRadius = '50%';
            bar.style.cursor = 'pointer';
            bar.style.border = '2px solid #3b82f6';
            bar.style.boxShadow = '0 6px 20px rgba(0, 0, 0, 0.5), 0 0 12px rgba(59, 130, 246, 0.6)';
            bar.title = 'Tacahu Sync - Click để mở rộng';
            if (fullContent) fullContent.style.display = 'none';
            if (miniContent) miniContent.style.display = 'flex';
        } else {
            bar.style.width = 'auto';
            bar.style.height = 'auto';
            bar.style.padding = '6px 12px';
            bar.style.borderRadius = '30px';
            bar.style.cursor = 'default';
            bar.style.border = '1px solid #3b82f6';
            bar.style.boxShadow = '0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5)';
            bar.title = '';
            if (fullContent) fullContent.style.display = 'flex';
            if (miniContent) miniContent.style.display = 'none';
        }
    }

    // ---------------------------------------------------------
    // Bottom Center Control Bar Injection
    // ---------------------------------------------------------
    function injectControlBar() {
        if (!isExtensionAlive()) return;
        if (document.getElementById('tacahu-control-bar')) return;

        const bar = document.createElement('div');
        bar.id = 'tacahu-control-bar';
        bar.style.cssText = `
            position: fixed;
            bottom: 12px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 999999;
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border: 1px solid #3b82f6;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5);
            border-radius: 30px;
            padding: 6px 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            color: #f8fafc;
            font-size: 13px;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            user-select: none;
        `;

        bar.innerHTML = `
            <!-- Expanded Full Bar -->
            <div id="tacahu-bar-full" style="display: flex; align-items: center; gap: 8px;">
                <div style="display: flex; align-items: center; gap: 6px;">
                    <div style="width: 9px; height: 9px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 8px #22c55e;" id="tacahu-status-dot"></div>
                    <span style="font-weight: 700; font-size: 12px; background: linear-gradient(90deg, #60a5fa, #a855f7); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">Tacahu Sync</span>
                    ${getEnvBadgeHtml(cachedSettings.apiBaseUrl)}
                </div>
                <div style="height: 16px; width: 1px; background: #334155;"></div>
                <button id="tacahu-btn-batch-scan" style="
                    background: #2563eb;
                    color: #ffffff;
                    border: none;
                    padding: 5px 12px;
                    border-radius: 6px;
                    font-weight: 600;
                    font-size: 12px;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    gap: 5px;
                    transition: transform 0.1s, background 0.2s;
                ">
                    <span id="tacahu-batch-text">Quét & Đồng Bộ Bộ Ảnh</span>
                </button>
                <span id="tacahu-scan-counter" style="color: #4ade80; font-size: 11.5px; font-weight: 600; display: none;"></span>
                <button id="tacahu-btn-collapse" title="Thu gọn thành nút tròn" style="
                    background: rgba(255, 255, 255, 0.08);
                    border: 1px solid rgba(255, 255, 255, 0.15);
                    color: #94a3b8;
                    width: 20px;
                    height: 20px;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 11px;
                    cursor: pointer;
                    padding: 0;
                    line-height: 1;
                    transition: all 0.2s;
                    margin-left: 2px;
                ">✕</button>
            </div>

            <!-- Collapsed Mini Round Circle -->
            <div id="tacahu-bar-mini" style="display: none; width: 100%; height: 100%; align-items: center; justify-content: center; position: relative;">
                <div style="width: 12px; height: 12px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 10px #22c55e;"></div>
                <span style="position: absolute; top: -1px; right: -1px; font-size: 8px;">⚡</span>
            </div>
        `;

        document.body.appendChild(bar);
        applyControlBarState(bar);

        const batchBtn = bar.querySelector('#tacahu-btn-batch-scan');
        if (batchBtn) {
            batchBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                runBatchScan();
            });
            batchBtn.addEventListener('mouseover', () => { batchBtn.style.transform = 'scale(1.02)'; });
            batchBtn.addEventListener('mouseout', () => { batchBtn.style.transform = 'scale(1)'; });
        }

        const collapseBtn = bar.querySelector('#tacahu-btn-collapse');
        if (collapseBtn) {
            collapseBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                isControlBarCollapsed = true;
                sessionStorage.setItem('tacahu_sync_collapsed', '1');
                applyControlBarState(bar);
            });
            collapseBtn.addEventListener('mouseover', () => {
                collapseBtn.style.background = 'rgba(239, 68, 68, 0.2)';
                collapseBtn.style.color = '#f87171';
                collapseBtn.style.borderColor = 'rgba(239, 68, 68, 0.4)';
            });
            collapseBtn.addEventListener('mouseout', () => {
                collapseBtn.style.background = 'rgba(255, 255, 255, 0.08)';
                collapseBtn.style.color = '#94a3b8';
                collapseBtn.style.borderColor = 'rgba(255, 255, 255, 0.15)';
            });
        }

        // Click on circular button to expand
        bar.addEventListener('click', () => {
            if (isControlBarCollapsed) {
                isControlBarCollapsed = false;
                sessionStorage.setItem('tacahu_sync_collapsed', '0');
                applyControlBarState(bar);
            }
        });

        bar.addEventListener('mouseover', () => {
            if (isControlBarCollapsed) {
                bar.style.transform = 'translateX(-50%) scale(1.08)';
            }
        });

        bar.addEventListener('mouseout', () => {
            if (isControlBarCollapsed) {
                bar.style.transform = 'translateX(-50%) scale(1)';
            }
        });
    }

    // ---------------------------------------------------------
    // Row Inspection & Buttons Injection
    // ---------------------------------------------------------
    function injectButtonsToRows() {
        if (!isExtensionAlive()) {
            if (scanIntervalId) {
                clearInterval(scanIntervalId);
                scanIntervalId = null;
            }
            return;
        }

        const orderRows = document.querySelectorAll('tr');
        if (!orderRows.length) return;

        orderRows.forEach(tr => {
            const orderIdEl = tr.querySelector('td:first-child');
            if (!orderIdEl) return;
            const rawText = orderIdEl.innerText || '';
            const match = rawText.match(/([A-Z]{2}\d{5,})/i) || rawText.match(/DJ\w+/i);
            if (!match) return;
            const orderId = match[0].trim().toUpperCase();

            if (orderIdEl.querySelector('.tacahu-gallery-zone')) return;

            const targetSalesUrl = findProductSalesUrl(tr);

            const rowZone = document.createElement('div');
            rowZone.className = 'tacahu-gallery-zone';
            rowZone.dataset.orderId = orderId;
            rowZone.dataset.salesUrl = targetSalesUrl || '';
            rowZone.style.cssText = 'margin-top: 6px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap;';

            if (targetSalesUrl) {
                const scanBtn = document.createElement('button');
                scanBtn.className = 'tacahu-row-scan-btn';
                scanBtn.innerText = 'Quét ảnh';
                scanBtn.style.cssText = `
                    padding: 3px 8px;
                    background: #f97316;
                    color: #fff;
                    border: none;
                    cursor: pointer;
                    font-weight: 600;
                    font-size: 11px;
                    border-radius: 4px;
                    display: inline-flex;
                    align-items: center;
                    gap: 3px;
                `;

                scanBtn.onclick = function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    if (!isExtensionAlive()) return;

                    scanBtn.disabled = true;
                    scanBtn.innerText = 'Đang quét...';
                    fetchAndProcessSingleRow(orderId, targetSalesUrl, rowZone, scanBtn);
                };
                rowZone.appendChild(scanBtn);
            } else {
                rowZone.innerHTML = '<span style="color:#ef4444;font-size:10px;">(K tìm thấy link sales)</span>';
            }

            orderIdEl.appendChild(rowZone);
        });
    }

    // Comprehensive extractor for product sales URL from row
    function findProductSalesUrl(tr) {
        if (!tr) return null;

        // Priority 1: Check all <a> elements inside the row
        const links = Array.from(tr.querySelectorAll('a'));
        for (const a of links) {
            const rawHref = a.getAttribute('href') || a.getAttribute('ng-href') || a.getAttribute('data-href') || a.getAttribute('data-url') || (a.href && !a.href.startsWith('javascript:') && !a.href.endsWith('#') ? a.href : '') || '';
            const href = rawHref.trim();
            if (!href || href === '#' || href.startsWith('javascript:')) continue;

            // Exclude admin / tool / download / copy actions
            if (
                href.includes('/design-tool') ||
                href.includes('/download') ||
                href.includes('drive.google.com') ||
                href.includes('trello.com') ||
                href.includes('/asset') ||
                href.includes('copy')
            ) {
                continue;
            }

            // Check if link matches a product page format
            if (
                href.includes('printerval.com') ||
                href.includes('ebay.com') ||
                href.includes('vincustom.com') ||
                href.match(/-p\d+/i) ||
                href.match(/\/p\d+/i) ||
                href.includes('/us/') ||
                href.includes('/product/') ||
                href.includes('/item/')
            ) {
                if (href.startsWith('http')) return href;
                return `https://printerval.com${href.startsWith('/') ? '' : '/'}${href}`;
            }
        }

        // Priority 2: Look for <a> tags specifically in the Product column (td:nth-child(2))
        const col2Links = Array.from(tr.querySelectorAll('td:nth-child(2) a, td:nth-child(3) a'));
        for (const a of col2Links) {
            const rawHref = a.getAttribute('href') || a.getAttribute('ng-href') || a.getAttribute('data-href') || (a.href && !a.href.startsWith('javascript:') ? a.href : '') || '';
            const href = rawHref.trim();
            if (!href || href === '#' || href.startsWith('javascript:') || href.includes('copy')) continue;
            if (!href.includes('/design') && !href.includes('/download') && !href.includes('drive.google')) {
                if (href.startsWith('http')) return href;
                return `https://printerval.com${href.startsWith('/') ? '' : '/'}${href}`;
            }
        }

        // Priority 3: Regex match inside tr.innerHTML for product links
        const html = tr.innerHTML || '';
        const prinMatch = html.match(/https?:\/\/(?:www\.)?printerval\.com\/[a-zA-Z0-9_-]+-p\d+(?:\?[^\s"'<>]+)?/i)
            || html.match(/(?:href|ng-href|data-href)=["'](\/(?:[a-zA-Z0-9_-]+-p\d+|us\/[^\s"'<>]+|\-p\d+)(?:\?[^\s"'<>]+)?)["']/i);
        if (prinMatch) {
            let url = prinMatch[1] || prinMatch[0];
            if (!url.startsWith('http')) {
                url = `https://printerval.com${url.startsWith('/') ? '' : '/'}${url}`;
            }
            return url;
        }

        // Priority 4: External supplier URL in notes (vincustom, ebay, etc.)
        const supplierMatch = html.match(/https?:\/\/(?:www\.)?(?:ebay\.com\/itm\/|vincustom\.com\/product\/)[^\s"'<>]+/i);
        if (supplierMatch) {
            return supplierMatch[0];
        }

        // Priority 5: Fallback extract SKU ID from row text (e.g., P1768239282-L-MEN-002 -> https://printerval.com/-p1768239282)
        const rowText = tr.innerText || '';
        const skuMatch = rowText.match(/\bP(\d{6,})(?:-[A-Z0-9-]+)?\b/i);
        if (skuMatch && skuMatch[1]) {
            return `https://printerval.com/-p${skuMatch[1]}`;
        }

        return null;
    }

    function canonicalizeUrl(rawUrl) {
        const url = rawUrl.trim();
        if (!url) return { key: '', standardUrl: '' };

        // 1. Printerval asset
        const prinMatch = url.match(/(?:assets\.printerval\.com|printervalcdn\.com|cdn\.printerval\.com)\/(?:unsafe\/[^/]+\/)?(?:assets\.printerval\.com\/)?(.+)/i);
        if (prinMatch) {
            let relPath = prinMatch[1].replace(/^\/+/, '');
            relPath = relPath.replace(/^unsafe\/[^/]+\//, '');
            relPath = relPath.replace(/^assets\.printerval\.com\//, '');
            relPath = relPath.split('?')[0].split('#')[0];

            let standardUrl = `https://assets.printerval.com/${relPath}`;
            if (relPath.startsWith('asset/')) {
                standardUrl = `https://cdn.printerval.com/unsafe/960x960/${relPath}`;
            } else if (relPath.startsWith('image/') || relPath.startsWith('sticker/')) {
                standardUrl = `https://cdn.printerval.com/${relPath}`;
            }

            return {
                key: `prin:${relPath.toLowerCase()}`,
                standardUrl: standardUrl,
            };
        }

        // 2. eBay asset
        const ebayMatch = url.match(/i\.ebayimg\.com\/(?:thumbs\/)?images\/([^/]+\/[^/]+)/i);
        if (ebayMatch) {
            const imgPath = ebayMatch[1];
            return {
                key: `ebay:${imgPath.toLowerCase()}`,
                standardUrl: `https://i.ebayimg.com/images/${imgPath}/s-l1600.webp`,
            };
        }

        const clean = url.split('?')[0].split('#')[0];
        return { key: clean.toLowerCase(), standardUrl: clean };
    }

    function toAbsoluteProductImageUrl(rawUrl) {
        const raw = String(rawUrl || '').trim();
        if (!raw || /^(?:data|blob|javascript|about):/i.test(raw)) return null;
        if (/^https?:\/\//i.test(raw)) return raw;
        if (raw.startsWith('//')) return `https:${raw}`;
        return `https://printerval.com${raw.startsWith('/') ? '' : '/'}${raw}`;
    }

    // ---------------------------------------------------------
    // HTML Parsing & Gallery Extraction
    // ---------------------------------------------------------
    function extractGalleryFromHtml(html) {
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const junkKeywords = ['avatar', 'gift', 'banner', 'icon', 'badge', 'logo', 'trust', 'payment', 'star', 'review', 'placeholder', 'blank.gif', 'loading', 'shipping'];
        const result = [];
        const seenKeys = new Set();

        // Selectors strictly targeting product media & gallery elements
        const selectors = [
            '.product-gallery-item-image',
            '.product-thumbnail-slide img',
            '.product-image-container img',
            '.main-image img',
            '.image-gallery-thumbnail-image',
            '.image-gallery-slide img',
            '.slider-item img',
            '.ux-image-filmstrip-carousel img',
            '.ux-image-carousel img',
            '.slick-slide img',
            '.swiper-slide img',
            '.thumbnail-item img',
            '.product-media img',
            '.product-detail-media img',
            '[data-slider] img',
            'img[data-zoom-image]',
            'img[data-zoom-src]',
            'img[data-large-img-url]',
            'img[data-high-res-src]'
        ];

        doc.querySelectorAll(selectors.join(', ')).forEach(img => {
            const raw = img.getAttribute('data-zoom-src') ||
                        img.getAttribute('data-zoom-image') ||
                        img.getAttribute('data-large-img-url') ||
                        img.getAttribute('data-high-res-src') ||
                        img.getAttribute('data-src') ||
                        img.getAttribute('loading-src') ||
                        img.getAttribute('src');
            if (!raw) return;

            const absolute = toAbsoluteProductImageUrl(raw);
            if (!absolute) return;
            const { key, standardUrl } = canonicalizeUrl(absolute);
            if (!key || seenKeys.has(key)) return;

            const lower = standardUrl.toLowerCase();
            if (!junkKeywords.some(keyword => lower.includes(keyword))) {
                seenKeys.add(key);
                result.push(standardUrl);
            }
        });

        // Fallback: If no images found from selectors, inspect JSON-LD / product scripts
        if (result.length === 0) {
            const jsonLdScripts = doc.querySelectorAll('script[type="application/ld+json"]');
            jsonLdScripts.forEach(script => {
                try {
                    const parsed = JSON.parse(script.textContent || '{}');
                    const imgList = Array.isArray(parsed.image) ? parsed.image : (parsed.image ? [parsed.image] : []);
                    imgList.forEach(imgUrl => {
                        if (typeof imgUrl === 'string') {
                            const { key, standardUrl } = canonicalizeUrl(imgUrl);
                            if (key && !seenKeys.has(key)) {
                                seenKeys.add(key);
                                result.push(standardUrl);
                            }
                        }
                    });
                } catch (e) {}
            });
        }

        return result;
    }

    // ---------------------------------------------------------
    // Single Row Processing & Sync
    // ---------------------------------------------------------
    function fetchAndProcessSingleRow(orderId, salesUrl, container, btn) {
        if (!isExtensionAlive()) return;
        const absoluteUrl = salesUrl.startsWith('http') ? salesUrl : 'https://printerval.com' + salesUrl;

        chrome.runtime.sendMessage({ action: "FETCH_PRODUCT_PAGE", url: absoluteUrl }, (response) => {
            if (!isExtensionAlive()) return;

            if (!response || !response.success || !response.data) {
                if (btn) {
                    btn.innerText = 'Lỗi!';
                    btn.style.background = '#ef4444';
                    btn.disabled = false;
                }
                return;
            }

            const uniqueImgs = extractGalleryFromHtml(response.data);

            if (uniqueImgs.length > 0) {
                renderGalleryPreviews(container, uniqueImgs, orderId);

                // Auto-sync single row to backend
                chrome.runtime.sendMessage({
                    action: "SYNC_GALLERY_SINGLE",
                    payload: {
                        external_order_id: orderId,
                        image_urls: uniqueImgs,
                        product_url: absoluteUrl,
                    }
                }, (syncRes) => {
                    if (syncRes && syncRes.success) {
                        showRowBadge(container, `✓ Sync ${uniqueImgs.length} ảnh`, '#22c55e');
                    } else {
                        showRowBadge(container, `Sync lỗi`, '#f59e0b');
                    }
                });
            } else {
                if (btn) {
                    btn.innerText = '0 ảnh';
                    btn.style.background = '#94a3b8';
                }
            }
        });
    }

    // ---------------------------------------------------------
    // Render Gallery Previews & Click-to-Copy
    // ---------------------------------------------------------
    function renderGalleryPreviews(container, images, orderId) {
        container.innerHTML = '';

        images.forEach((imgUrl, index) => {
            const imgWrapper = document.createElement('div');
            imgWrapper.title = `Ảnh ${index + 1} - Click để copy!`;
            imgWrapper.style.cssText = `
                position: relative;
                width: 36px;
                height: 36px;
                border-radius: 4px;
                overflow: hidden;
                border: 1px solid #cbd5e1;
                cursor: pointer;
                background: #f1f5f9;
                transition: transform 0.15s, border-color 0.15s;
            `;

            const thumbImg = document.createElement('img');
            thumbImg.src = imgUrl;
            thumbImg.style.cssText = 'width: 100%; height: 100%; object-fit: cover; display: block;';
            imgWrapper.appendChild(thumbImg);

            const numBadge = document.createElement('span');
            numBadge.innerText = (index + 1).toString();
            numBadge.style.cssText = `
                position: absolute;
                bottom: 0;
                right: 0;
                background: rgba(15, 23, 42, 0.75);
                color: #fff;
                font-size: 8px;
                font-weight: 700;
                padding: 1px 3px;
                border-top-left-radius: 3px;
            `;
            imgWrapper.appendChild(numBadge);

            // Enlarged Hover Preview Box
            const previewBox = document.createElement('div');
            previewBox.style.cssText = `
                position: fixed;
                display: none;
                width: 280px;
                height: 280px;
                border: 2px solid #3b82f6;
                border-radius: 8px;
                background: #ffffff;
                z-index: 1000000;
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4);
                pointer-events: none;
                overflow: hidden;
            `;
            previewBox.innerHTML = `<img src="${imgUrl}" style="width:100%; height:100%; object-fit:contain;">`;
            document.body.appendChild(previewBox);

            imgWrapper.onmousemove = function (e) {
                previewBox.style.display = 'block';
                previewBox.style.left = (e.clientX + 20) + 'px';
                previewBox.style.top = Math.max(10, (e.clientY - 140)) + 'px';
            };

            imgWrapper.onmouseleave = function () {
                previewBox.style.display = 'none';
            };

            // Click-to-copy handler
            imgWrapper.onclick = function (e) {
                e.preventDefault();
                e.stopPropagation();
                if (!isExtensionAlive()) return;

                imgWrapper.style.opacity = '0.5';
                numBadge.innerText = '...';
                numBadge.style.background = '#f97316';

                chrome.runtime.sendMessage({ action: "FETCH_IMAGE_BLOB", url: imgUrl }, (res) => {
                    if (!isExtensionAlive()) return;

                    if (!res || !res.success || !res.data) {
                        fallbackTextCopy(imgUrl, imgWrapper, numBadge, index + 1);
                        return;
                    }

                    try {
                        const u8Array = new Uint8Array(res.data);
                        const blob = new Blob([u8Array], { type: 'image/png' });
                        const item = new ClipboardItem({ [blob.type]: blob });
                        navigator.clipboard.write([item]).then(() => {
                            numBadge.innerText = '✓';
                            numBadge.style.background = '#22c55e';
                            setTimeout(() => {
                                imgWrapper.style.opacity = '1';
                                numBadge.innerText = (index + 1).toString();
                                numBadge.style.background = 'rgba(15, 23, 42, 0.75)';
                            }, 1000);
                        }).catch(() => fallbackTextCopy(imgUrl, imgWrapper, numBadge, index + 1));
                    } catch (err) {
                        fallbackTextCopy(imgUrl, imgWrapper, numBadge, index + 1);
                    }
                });
            };

            container.appendChild(imgWrapper);
        });
    }

    function fallbackTextCopy(url, wrapper, badge, originalIndex) {
        if (!isExtensionAlive()) return;
        navigator.clipboard.writeText(url).then(() => {
            badge.innerText = 'URL';
            badge.style.background = '#3b82f6';
        }).catch(() => {
            badge.innerText = 'Err';
            badge.style.background = '#ef4444';
        });
        setTimeout(() => {
            wrapper.style.opacity = '1';
            badge.innerText = originalIndex.toString();
            badge.style.background = 'rgba(15, 23, 42, 0.75)';
        }, 1200);
    }

    function showRowBadge(container, text, bg) {
        let badge = container.querySelector('.tacahu-row-status-badge');
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'tacahu-row-status-badge';
            container.appendChild(badge);
        }
        badge.innerText = text;
        badge.style.cssText = `
            font-size: 10px;
            font-weight: 600;
            padding: 2px 6px;
            border-radius: 4px;
            background: ${bg};
            color: #ffffff;
            margin-left: 4px;
        `;
    }

    // ---------------------------------------------------------
    // Batch Scanning & Concurrency Pipeline
    // ---------------------------------------------------------
    async function runBatchScan() {
        if (isBatchRunning) return;
        if (!isExtensionAlive()) return;

        const zones = Array.from(document.querySelectorAll('.tacahu-gallery-zone')).filter(z => z.dataset.salesUrl);
        if (!zones.length) {
            alert("Không tìm thấy đơn hàng nào có link sản phẩm trên trang hiện tại!");
            return;
        }

        isBatchRunning = true;
        const batchBtn = document.getElementById('tacahu-btn-batch-scan');
        const batchText = document.getElementById('tacahu-batch-text');
        const counter = document.getElementById('tacahu-scan-counter');

        if (batchBtn) batchBtn.style.opacity = '0.7';
        if (batchText) batchText.innerText = 'Đang quét...';
        if (counter) {
            counter.style.display = 'inline-block';
            counter.innerText = `0 / ${zones.length}`;
        }

        let completed = 0;
        const batchPayloadItems = [];
        const concurrency = cachedSettings.maxConcurrency || 5;

        // Worker queue for concurrency
        let index = 0;
        async function worker() {
            while (index < zones.length) {
                const currentIndex = index++;
                const zone = zones[currentIndex];
                const orderId = zone.dataset.orderId;
                const salesUrl = zone.dataset.salesUrl;
                const absoluteUrl = salesUrl.startsWith('http') ? salesUrl : 'https://printerval.com' + salesUrl;

                try {
                    const htmlRes = await new Promise(resolve => {
                        chrome.runtime.sendMessage({ action: "FETCH_PRODUCT_PAGE", url: absoluteUrl }, resolve);
                    });

                    if (htmlRes && htmlRes.success && htmlRes.data) {
                        const images = extractGalleryFromHtml(htmlRes.data);
                        if (images.length > 0) {
                            renderGalleryPreviews(zone, images, orderId);
                            batchPayloadItems.push({
                                external_order_id: orderId,
                                image_urls: images,
                                product_url: absoluteUrl,
                            });
                        }
                    }
                } catch (e) { }

                completed++;
                if (counter) counter.innerText = `${completed} / ${zones.length}`;
            }
        }

        const workers = [];
        for (let i = 0; i < Math.min(concurrency, zones.length); i++) {
            workers.push(worker());
        }
        await Promise.all(workers);

        // Send bulk payload to Tacahu backend
        if (batchPayloadItems.length > 0) {
            if (batchText) batchText.innerText = 'Đang đồng bộ về Tacahu...';
            chrome.runtime.sendMessage({
                action: "SYNC_GALLERY_BATCH",
                payload: {
                    items: batchPayloadItems
                }
            }, (res) => {
                isBatchRunning = false;
                if (batchBtn) batchBtn.style.opacity = '1';
                if (batchText) batchText.innerText = 'Quét & Đồng Bộ Bộ Ảnh';

                if (res && res.success) {
                    const syncedCount = typeof res.data?.synced_orders_count === 'number' ? res.data.synced_orders_count : batchPayloadItems.length;
                    const totalImgs = res.data?.total_images_count || 0;
                    if (counter) {
                        counter.innerText = `✓ Đã sync ${syncedCount} đơn (${totalImgs} ảnh)`;
                        counter.style.color = '#4ade80';
                    }
                    showToast(`🎉 Đã đồng bộ thành công ${syncedCount} đơn (${totalImgs} ảnh) về Tacahu Ops!`);
                } else {
                    if (counter) {
                        counter.innerText = `Lỗi sync`;
                        counter.style.color = '#ef4444';
                    }
                    showToast(`⚠️ Không thể kết nối tới Tacahu Ops: ${res?.error || 'Lỗi không xác định'}`);
                }
            });
        } else {
            isBatchRunning = false;
            if (batchBtn) batchBtn.style.opacity = '1';
            if (batchText) batchText.innerText = 'Quét & Đồng Bộ Bộ Ảnh';
            if (counter) counter.innerText = `0 ảnh tìm thấy`;
        }
    }

    // ---------------------------------------------------------
    // Toast Notification
    // ---------------------------------------------------------
    function showToast(msg) {
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed;
            top: 24px;
            right: 24px;
            z-index: 10000000;
            background: #1e293b;
            color: #f8fafc;
            border-left: 4px solid #3b82f6;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
            padding: 14px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            animation: fadeIn 0.3s ease;
        `;
        toast.innerText = msg;
        document.body.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.5s';
            setTimeout(() => toast.remove(), 500);
        }, 4000);
    }

})();

(function () {
  'use strict';
  let scanIntervalId = null;
  setTimeout(() => { injectButtonsToRows(); scanIntervalId = setInterval(injectButtonsToRows, 2000); }, 1500);
  chrome.runtime.onMessage.addListener((message) => { if (message.action === 'AUTO_INIT') injectButtonsToRows(); });

  function isExtensionAlive() { return !!(window.chrome && chrome.runtime && chrome.runtime.id); }
  function absoluteUrl(url) { return url.startsWith('http') ? url : `https://printerval.com${url}`; }
  function setButtonState(button, label, color, disabled) { button.innerText = label; button.style.background = color; button.disabled = !!disabled; }

  function extractGallery(html) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const junkKeywords = ['avatar', 'gift', 'banner', 'icon', 'badge'];
    const result = [];
    doc.querySelectorAll('.product-gallery-item-image, .product-thumbnail-slide img, .product-image-container img, .main-image img').forEach((img) => {
      const raw = img.getAttribute('src') || img.getAttribute('data-src') || img.getAttribute('loading-src');
      if (!raw) return;
      const url = (raw.startsWith('http') ? raw : `https:${raw}`).replace(/\/unsafe\/[^/]+\//, '/unsafe/960x960/');
      if (!junkKeywords.some((keyword) => url.toLowerCase().includes(keyword)) && !result.includes(url)) result.push(url);
    });
    return result;
  }

  function injectButtonsToRows() {
    if (!isExtensionAlive()) { if (scanIntervalId) clearInterval(scanIntervalId); return; }
    document.querySelectorAll('tr').forEach((tr) => {
      const orderIdEl = tr.querySelector('td:first-child');
      const orderId = orderIdEl && orderIdEl.innerText && orderIdEl.innerText.trim();
      if (!orderId || !orderId.startsWith('DJ') || orderIdEl.querySelector('.printerval-row-zone')) return;
      const salesLink = tr.querySelector('a[href*="/us/"], a[ng-href*="/us/"], a[href*="-p"]');
      const salesUrl = salesLink && (salesLink.getAttribute('href') || salesLink.getAttribute('ng-href'));
      const zone = document.createElement('div');
      zone.className = 'printerval-row-zone';
      zone.style = 'margin-top:5px;display:flex;gap:6px;align-items:center;flex-wrap:wrap;';
      if (!salesUrl) {
        zone.innerHTML = '<span style="color:#777;font-size:10px;">Không tìm thấy link sản phẩm</span>';
      } else {
        const button = document.createElement('button');
        setButtonState(button, 'Quét & đồng bộ ảnh', '#2563eb', false);
        button.style.cssText += 'padding:2px 5px;color:#fff;border:none;cursor:pointer;font-weight:bold;font-size:10px;border-radius:2px;';
        button.onclick = (event) => { event.preventDefault(); event.stopPropagation(); setButtonState(button, 'Đang quét…', '#64748b', true); fetchAndSyncGallery(orderId, salesUrl, zone, button); };
        zone.appendChild(button);
      }
      orderIdEl.appendChild(zone);
    });
  }

  function fetchAndSyncGallery(orderId, salesUrl, container, button) {
    const productUrl = absoluteUrl(salesUrl);
    chrome.runtime.sendMessage({ action: 'FETCH_DETAIL_PAGE', url: productUrl }, (response) => {
      if (!response || !response.success) { setButtonState(button, 'Lỗi tải trang', '#dc2626', false); return; }
      const images = extractGallery(response.data);
      if (!images.length) { setButtonState(button, 'Không có ảnh', '#64748b', false); return; }
      chrome.runtime.sendMessage({ action: 'SYNC_GALLERY', externalOrderId: orderId, imageUrls: images, productUrl }, (sync) => {
        if (!sync || !sync.success) { setButtonState(button, sync && sync.error === 'NOT_CONFIGURED' ? 'Cần cấu hình CopyImage' : 'Không đồng bộ được', '#dc2626', false); return; }
        setButtonState(button, `Đã đồng bộ ${sync.imageCount} ảnh`, '#16a34a', false);
        renderPreviews(images, container);
      });
    });
  }

  function renderPreviews(images, container) {
    container.querySelectorAll('.printerval-gallery-preview').forEach((node) => node.remove());
    images.forEach((url, index) => {
      const image = document.createElement('img');
      image.className = 'printerval-gallery-preview'; image.src = url; image.title = `Ảnh ${index + 1} — click để sao chép link`;
      image.style = 'width:28px;height:28px;object-fit:cover;border:1px solid #cbd5e1;cursor:pointer;';
      image.onclick = (event) => { event.preventDefault(); event.stopPropagation(); navigator.clipboard.writeText(url); };
      container.appendChild(image);
    });
  }
})();

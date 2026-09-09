chrome.action.onClicked.addListener((tab) => {
  if (!tab.id) return;
  chrome.tabs.sendMessage(tab.id, { action: 'AUTO_INIT' }).catch(() => {
    chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content.js'] }).then(() => {
      chrome.tabs.sendMessage(tab.id, { action: 'AUTO_INIT' });
    });
  });
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'FETCH_DETAIL_PAGE') {
    fetch(request.url)
      .then((response) => response.text())
      .then((html) => sendResponse({ success: true, data: html }))
      .catch((error) => sendResponse({ success: false, error: error.toString() }));
    return true;
  }

  if (request.action === 'FETCH_IMAGE_BLOB') {
    fetch(request.url)
      .then((response) => response.arrayBuffer())
      .then((buffer) => sendResponse({ success: true, data: Array.from(new Uint8Array(buffer)) }))
      .catch((error) => sendResponse({ success: false, error: error.toString() }));
    return true;
  }

  if (request.action === 'SYNC_GALLERY') {
    chrome.storage.sync.get(['apiBaseUrl', 'platformId', 'galleryBridgeToken'], (settings) => {
      if (!settings.apiBaseUrl || !settings.platformId || !settings.galleryBridgeToken) {
        sendResponse({ success: false, error: 'NOT_CONFIGURED' });
        return;
      }
      const apiBaseUrl = settings.apiBaseUrl.replace(/\/$/, '').replace(/\/api$/, '');
      fetch(`${apiBaseUrl}/api/integrations/printerval-gallery`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Gallery-Bridge-Token': settings.galleryBridgeToken },
        body: JSON.stringify({
          platform_id: settings.platformId,
          external_order_id: request.externalOrderId,
          image_urls: request.imageUrls,
          product_url: request.productUrl,
        }),
      })
        .then(async (response) => {
          const payload = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
          sendResponse({ success: true, imageCount: payload.image_count });
        })
        .catch((error) => sendResponse({ success: false, error: error.message }));
    });
    return true;
  }
});

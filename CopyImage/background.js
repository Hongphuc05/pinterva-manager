// Tacahu POD - Printerval Gallery Sync & Copy Tool
// Service Worker (Manifest V3)

const DEFAULT_SETTINGS = {
    apiBaseUrl: "http://localhost:8000",
    autoScanOnLoad: false,
    maxConcurrency: 5,
};

// Initialize settings on install
chrome.runtime.onInstalled.addListener(() => {
    chrome.storage.sync.get(DEFAULT_SETTINGS, (stored) => {
        chrome.storage.sync.set(stored);
    });
});

// Extension icon click handler
chrome.action.onClicked.addListener((tab) => {
    if (tab && tab.id) {
        chrome.tabs.sendMessage(tab.id, { action: "TRIGGER_BATCH_SCAN" }).catch(() => {
            chrome.scripting.executeScript({
                target: { tabId: tab.id },
                files: ["content.js"]
            }).then(() => {
                chrome.tabs.sendMessage(tab.id, { action: "TRIGGER_BATCH_SCAN" }).catch(() => {});
            }).catch(() => {});
        });
    }
});

// Helper: Get API base URL
async function getApiBaseUrl() {
    return new Promise((resolve) => {
        chrome.storage.sync.get(DEFAULT_SETTINGS, (items) => {
            let url = (items.apiBaseUrl || DEFAULT_SETTINGS.apiBaseUrl).trim();
            if (url.endsWith("/")) {
                url = url.slice(0, -1);
            }
            resolve(url);
        });
    });
}

// Runtime message dispatcher
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "GET_SETTINGS") {
        chrome.storage.sync.get(DEFAULT_SETTINGS, (items) => {
            sendResponse({ success: true, data: items });
        });
        return true;
    }

    if (request.action === "SAVE_SETTINGS") {
        chrome.storage.sync.set(request.settings || {}, () => {
            sendResponse({ success: true });
        });
        return true;
    }

    if (request.action === "TEST_CONNECTION") {
        (async () => {
            try {
                const baseUrl = request.apiBaseUrl || await getApiBaseUrl();
                const res = await fetch(`${baseUrl}/docs`, { method: "HEAD", cache: "no-cache" });
                if (res.ok || res.status === 200 || res.status === 304 || res.status === 404) {
                    sendResponse({ success: true, status: res.status });
                } else {
                    sendResponse({ success: false, status: res.status, error: `HTTP ${res.status}` });
                }
            } catch (err) {
                sendResponse({ success: false, error: err.message || "Connection refused" });
            }
        })();
        return true;
    }

    if (request.action === "FETCH_DETAIL_PAGE" || request.action === "FETCH_PRODUCT_PAGE") {
        fetch(request.url, {
            credentials: "include",
            headers: {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
            }
        })
            .then(res => res.text())
            .then(html => sendResponse({ success: true, data: html }))
            .catch(err => sendResponse({ success: false, error: err.toString() }));
        return true;
    }

    if (request.action === "FETCH_IMAGE_BLOB") {
        fetch(request.url)
            .then(response => response.arrayBuffer())
            .then(buffer => {
                const array = Array.from(new Uint8Array(buffer));
                sendResponse({ success: true, data: array });
            })
            .catch(error => sendResponse({ success: false, error: error.toString() }));
        return true;
    }

    if (request.action === "SYNC_GALLERY_BATCH") {
        (async () => {
            try {
                const baseUrl = await getApiBaseUrl();
                const res = await fetch(`${baseUrl}/api/integrations/printerval-gallery/batch`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify(request.payload),
                });
                const data = await res.json();
                if (res.ok) {
                    sendResponse({ success: true, data });
                } else {
                    sendResponse({ success: false, error: data.detail || `HTTP ${res.status}` });
                }
            } catch (err) {
                sendResponse({ success: false, error: err.message || "Lỗi kết nối tới Tacahu API" });
            }
        })();
        return true;
    }

    if (request.action === "SYNC_GALLERY_SINGLE") {
        (async () => {
            try {
                const baseUrl = await getApiBaseUrl();
                const res = await fetch(`${baseUrl}/api/integrations/printerval-gallery`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify(request.payload),
                });
                const data = await res.json();
                if (res.ok) {
                    sendResponse({ success: true, data });
                } else {
                    sendResponse({ success: false, error: data.detail || `HTTP ${res.status}` });
                }
            } catch (err) {
                sendResponse({ success: false, error: err.message || "Lỗi kết nối tới Tacahu API" });
            }
        })();
        return true;
    }
});
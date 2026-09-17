// Tacahu POD - Options Controller

document.addEventListener('DOMContentLoaded', () => {
    const apiBaseUrlInput = document.getElementById('apiBaseUrl');
    const maxConcurrencySelect = document.getElementById('maxConcurrency');
    const autoScanOnLoadCheckbox = document.getElementById('autoScanOnLoad');
    const btnSave = document.getElementById('btnSave');
    const btnTest = document.getElementById('btnTest');
    const testStatus = document.getElementById('testStatus');
    const saveStatus = document.getElementById('saveStatus');

    // Load stored settings
    chrome.runtime.sendMessage({ action: 'GET_SETTINGS' }, (res) => {
        if (res && res.success && res.data) {
            const data = res.data;
            if (data.apiBaseUrl) apiBaseUrlInput.value = data.apiBaseUrl;
            if (data.maxConcurrency) maxConcurrencySelect.value = data.maxConcurrency.toString();
            if (data.autoScanOnLoad !== undefined) autoScanOnLoadCheckbox.checked = data.autoScanOnLoad;
        }
    });

    // Test Connection
    btnTest.addEventListener('click', () => {
        const url = apiBaseUrlInput.value.trim() || 'http://localhost:8000';
        testStatus.className = 'status-badge';
        testStatus.style.display = 'block';
        testStatus.innerText = 'Đang kiểm tra kết nối...';
        testStatus.style.backgroundColor = 'rgba(59, 130, 246, 0.2)';
        testStatus.style.color = '#60a5fa';

        chrome.runtime.sendMessage({ action: 'TEST_CONNECTION', apiBaseUrl: url }, (res) => {
            if (res && res.success) {
                testStatus.className = 'status-badge status-success';
                testStatus.innerText = `✓ Kết nối thành công tới Tacahu Ops!`;
            } else {
                testStatus.className = 'status-badge status-error';
                testStatus.innerText = `✕ Kết nối thất bại: ${res?.error || 'Không thể liên lạc'}`;
            }
        });
    });

    // Save Settings
    btnSave.addEventListener('click', () => {
        let url = apiBaseUrlInput.value.trim() || 'http://localhost:8000';
        if (url.endsWith('/')) url = url.slice(0, -1);

        const settings = {
            apiBaseUrl: url,
            maxConcurrency: parseInt(maxConcurrencySelect.value, 10) || 5,
            autoScanOnLoad: autoScanOnLoadCheckbox.checked,
        };

        chrome.runtime.sendMessage({ action: 'SAVE_SETTINGS', settings }, (res) => {
            if (res && res.success) {
                saveStatus.className = 'status-badge status-success';
                saveStatus.innerText = '✓ Đã lưu cài đặt thành công!';
                setTimeout(() => {
                    saveStatus.style.display = 'none';
                }, 3000);
            } else {
                saveStatus.className = 'status-badge status-error';
                saveStatus.innerText = '✕ Lỗi lưu cài đặt.';
            }
        });
    });
});

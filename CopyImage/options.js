const ids = ['apiBaseUrl', 'platformId', 'galleryBridgeToken'];
chrome.storage.sync.get(ids, (saved) => ids.forEach((id) => { document.getElementById(id).value = saved[id] || ''; }));
document.getElementById('save').addEventListener('click', () => {
  const settings = Object.fromEntries(ids.map((id) => [id, document.getElementById(id).value.trim()]));
  chrome.storage.sync.set(settings, () => {
    document.getElementById('status').textContent = 'Đã lưu';
    setTimeout(() => { document.getElementById('status').textContent = ''; }, 1500);
  });
});

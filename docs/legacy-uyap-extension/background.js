/* Tüm çerçevelerden (iframe dahil) belge bağlantılarını toplar. */
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type !== "jurisai-collect-all") return;
  const tabId = sender.tab?.id;
  if (tabId == null) {
    sendResponse({ links: [] });
    return true;
  }
  (async () => {
    let frames = [];
    try {
      frames = (await chrome.webNavigation.getAllFrames({ tabId })) || [];
    } catch (_) {
      frames = [{ frameId: 0 }];
    }
    const seen = new Map();
    const files = new Map();
    const requests = new Map();
    await Promise.all(
      frames.map(
        (f) =>
          new Promise((resolve) => {
            chrome.tabs.sendMessage(
              tabId,
              { type: "jurisai-collect-frame" },
              { frameId: f.frameId },
              (res) => {
                void chrome.runtime.lastError;
                (res?.links || []).forEach(([url, label]) => {
                  if (!seen.has(url)) seen.set(url, label);
                });
                (res?.files || []).forEach(([key, file]) => {
                  if (!files.has(key)) files.set(key, file);
                });
                (res?.requests || []).forEach(([url, request]) => {
                  if (!requests.has(url)) requests.set(url, request);
                });
                resolve();
              },
            );
          }),
      ),
    );
    sendResponse({
      links: [...seen.entries()],
      files: [...files.entries()],
      requests: [...requests.entries()],
    });
  })();
  return true;
});

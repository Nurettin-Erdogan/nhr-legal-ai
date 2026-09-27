/* Juris AI popup - API adresi ve anahtarını chrome.storage.sync üzerinde tutar. */

const DEFAULTS = {
  apiUrl: "http://localhost:8766/api/public/v1/documents/upload",
  apiKey: "",
  throttleMs: 1500,
};

const el = (id) => document.getElementById(id);
const status = el("status");

function say(message, kind = "") {
  status.textContent = message;
  status.className = `status ${kind}`;
}

async function load() {
  try {
    const stored = await chrome.storage.sync.get(Object.keys(DEFAULTS));
    const settings = { ...DEFAULTS, ...stored };
    if (!settings.apiUrl || /api\.jurisai\.local/i.test(settings.apiUrl)) {
      settings.apiUrl = DEFAULTS.apiUrl;
      await chrome.storage.sync.set({ apiUrl: settings.apiUrl });
    }
    el("apiUrl").value = settings.apiUrl;
    el("apiKey").value = settings.apiKey;
    el("throttleMs").value = settings.throttleMs;
  } catch (error) {
    say(`Ayarlar okunamadı: ${error.message}`, "err");
  }
}

el("save").addEventListener("click", async () => {
  const apiUrl = el("apiUrl").value.trim();
  const apiKey = el("apiKey").value.trim();
  const throttleMs = Math.min(10000, Math.max(500, Number(el("throttleMs").value) || 1500));
  if (!/^https?:\/\//i.test(apiUrl)) return say("Geçerli bir API adresi gir.", "err");
  if (apiKey.length < 20) return say("API anahtarı çok kısa görünüyor.", "err");
  try {
    await chrome.storage.sync.set({ apiUrl, apiKey, throttleMs });
    say("Ayarlar kaydedildi.", "ok");
  } catch (error) {
    say(`Kaydedilemedi: ${error.message}`, "err");
  }
});

el("test").addEventListener("click", async () => {
  const apiUrl = el("apiUrl").value.trim();
  const apiKey = el("apiKey").value.trim();
  if (!/^https?:\/\//i.test(apiUrl)) return say("Geçerli bir API adresi gir.", "err");
  if (apiKey.length < 20) return say("Önce bağlantı anahtarını yapıştır.", "err");
  say("Deneniyor…");
  try {
    await chrome.storage.sync.set({ apiUrl, apiKey });
    const res = await chrome.runtime.sendMessage({ type: "JURISAI_TEST" });
    if (res?.ok) say("JURISAI bağlantısı hazır ✓", "ok");
    else say(`Ulaşılamadı: ${res?.error || res?.status || "bilinmeyen"}`, "err");
  } catch (error) {
    say(`Ulaşılamadı: ${error.message}`, "err");
  }
});

el("rescan").addEventListener("click", async () => {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return say("Sekme bulunamadı.", "err");
    const res = await chrome.tabs.sendMessage(tab.id, { type: "JURISAI_RESCAN" });
    say(`${res?.count ?? 0} evrak düğmesi hazır.`, "ok");
  } catch (_) {
    say("Sayfa okunamadı. UYAP sekmesini yenile.", "err");
  }
});

load();

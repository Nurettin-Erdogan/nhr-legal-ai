/* JurisAI popup - ayarları chrome.storage.sync üzerinde tutar.
   Gizlilik: "otomatik aktarım" ve "yerel kopya" varsayılan olarak kapalıdır; otomatik aktarım
   yalnızca kullanıcı bilgilendirme metnini onaylayarak açabilir. */

const DEFAULTS = {
  apiUrl: "http://localhost:8766/api/public/v1/documents/upload",
  apiKey: "",
  throttleMs: 1500,
  autoSync: false,
  saveLocal: false,
};

const el = (id) => document.getElementById(id);
const status = el("status");

const AUTO_SYNC_CONSENT =
  "Otomatik aktarım açılsın mı?\n\n" +
  "UYAP'ta bir dosyayı görüntülediğinde, dosyanın evrakları ve künyesi (mahkeme, esas no, taraf adı) " +
  "JurisAI hesabına kendiliğinden gönderilecek. Bu veriler müvekkil bilgisi içerebilir.\n\n" +
  "Yalnızca yetkili olduğun dosyalarda ve müvekkil bilgilendirmesini yaptıysan aç.";

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
    el("autoSync").checked = settings.autoSync === true;
    el("saveLocal").checked = settings.saveLocal === true;
  } catch (error) {
    say(`Ayarlar okunamadı: ${error.message}`, "err");
  }
}

// Otomatik aktarım açılırken bilgilendirme onayı alınır; reddedilirse kutu geri kapanır.
el("autoSync").addEventListener("change", (event) => {
  if (event.target.checked && !window.confirm(AUTO_SYNC_CONSENT)) {
    event.target.checked = false;
  }
});

el("save").addEventListener("click", async () => {
  const apiUrl = el("apiUrl").value.trim();
  const apiKey = el("apiKey").value.trim();
  const throttleMs = Math.min(10000, Math.max(500, Number(el("throttleMs").value) || 1500));
  if (!/^https?:\/\//i.test(apiUrl)) return say("Geçerli bir API adresi gir.", "err");
  if (apiKey.length < 20) return say("API anahtarı çok kısa görünüyor.", "err");
  const autoSync = el("autoSync").checked;
  const saveLocal = el("saveLocal").checked;
  try {
    await chrome.storage.sync.set({
      apiUrl,
      apiKey,
      throttleMs,
      autoSync,
      saveLocal,
      ...(autoSync ? { autoSyncConsentAt: new Date().toISOString() } : {}),
    });
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
    if (res?.ok) say("JurisAI bağlantısı hazır ✓", "ok");
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

// Sayfa tanısı: isim, metin ya da bağlantı değeri içermez; yalnız yapı sayıları ve maskeli yol biçimleri.
el("diagnose").addEventListener("click", async () => {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return say("Sekme bulunamadı.", "err");
    const frames = await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func: () => (typeof window.__jurisaiDiagnose === "function" ? window.__jurisaiDiagnose() : null),
    });
    const reports = frames.map((frame) => frame.result).filter(Boolean);
    if (!reports.length) return say("Bu sekmede UYAP sayfası bulunamadı.", "err");
    const payload = { reports };
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    // Ayrıca dosyaya da yazılır: pano başka bir şeyle değişirse kaybolmaz, geliştiriciye dosya olarak iletilebilir.
    const saved = await chrome.runtime.sendMessage({ type: "JURISAI_SAVE_DIAGNOSIS", report: payload });
    say(
      `Tanı panoya kopyalandı${saved?.ok ? ` ve İndirilenler\\${saved.file.replace("/", "\\")} dosyasına kaydedildi` : ""} (${reports.length} çerçeve). Kişisel veri içermez.`,
      "ok",
    );
  } catch (error) {
    // UYAP dışındaki bir sekmede tarayıcı betik çalıştırmayı reddeder: kullanıcıya anlaşılır söyle.
    const blocked = /Cannot access|permission|host/i.test(String(error?.message));
    say(
      blocked
        ? "Bu sekme bir UYAP sayfası değil. UYAP'ta dosyanın evrak listesini aç ve tekrar dene."
        : `Tanı alınamadı: ${error.message}`,
      "err",
    );
  }
});

// Tıklama kaydı: UYAP'ta bir evrak yaprağına tıklayınca sayfanın ne yaptığını (ağ isteği, indirme, yeni sekme,
// eklenen iframe) kaydeder; metin/ad/değer içermez. Bitince dosya İndirilenler\NHR-Hukuk-UYAP içine yazılır.
async function activeTabId() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab?.id;
}
el("record").addEventListener("click", async () => {
  try {
    const tabId = await activeTabId();
    if (!tabId) return say("Sekme bulunamadı.", "err");
    await chrome.tabs.sendMessage(tabId, { type: "JURISAI_RECORD_START", seconds: 60 }, { frameId: 0 });
    say("Kayıt başladı (60 sn). UYAP'ta evrak yaprağına tıkla; bitince dosya otomatik kaydedilir.", "ok");
  } catch (_) {
    say("Bu sekme bir UYAP sayfası değil ya da sayfa yenilenmeli (F5).", "err");
  }
});
el("recordStop").addEventListener("click", async () => {
  try {
    const tabId = await activeTabId();
    const result = await chrome.tabs.sendMessage(tabId, { type: "JURISAI_RECORD_STOP" }, { frameId: 0 });
    say(
      result?.ok ? "Kayıt bitti ve dosyaya yazıldı." : `Kayıt yok ya da kaydedilemedi: ${result?.error || ""}`,
      result?.ok ? "ok" : "err",
    );
  } catch (_) {
    say("Bu sekmede kayıt başlatılmamış.", "err");
  }
});

// Açık dosya penceresindeki evrakları klasör yapısıyla çeker (onay ister, yavaş çalışır, durdurulabilir).
el("pull").addEventListener("click", async () => {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return say("Sekme bulunamadı.", "err");
    say("Çekme başladı; UYAP sayfasındaki onay penceresini bekle…", "ok");
    const result = await chrome.tabs.sendMessage(tab.id, { type: "JURISAI_PULL_DOSYA" }, { frameId: 0 });
    if (!result?.ok) return say(result?.error || "Çekme başlatılamadı.", "err");
    say(
      result.cancelled
        ? "Çekme iptal edildi."
        : `${result.sent} evrak aktarıldı${result.failed ? `, ${result.failed} hata` : ""}.`,
      result.failed ? "err" : "ok",
    );
  } catch (_) {
    say("Bu sekme bir UYAP sayfası değil ya da sayfa yenilenmeli (F5).", "err");
  }
});
el("pullStop").addEventListener("click", async () => {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    await chrome.tabs.sendMessage(tab.id, { type: "JURISAI_PULL_STOP" }, { frameId: 0 });
    say("Durdurma istendi; sürmekte olan evrak bitince duracak.", "ok");
  } catch (_) {
    say("Bu sekmede çalışan bir çekme yok.", "err");
  }
});

load();

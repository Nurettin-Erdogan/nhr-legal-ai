/* UYAP Dosya Çekici - service worker (Manifest V3)
   Toplama, sayfalama, hız sınırlama ve Chrome Downloads API ile indirme burada yürür.
   Popup kapansa bile iş devam eder; durum chrome.storage.local'da tutulur. */

const DEFAULTS = {
  folder: "UYAP",
  delayMs: 700, // istekler arası bekleme (rate limiting)
  timeoutMs: 30000, // tek indirme için üst sınır
  maxPages: 50, // sayfalama üst sınırı
  apiKey: "",
  apiUrl: "", // opsiyonel: https://vatandas.uyap.gov.tr/api/v1/documents
  retries: 2,
  jurisaiToken: "", // JURISAI bağlantı anahtarı (Belge İşleme akışı için)
  jurisaiApiUrl: "http://localhost:8766",
};

let state = {
  running: false,
  cancelled: false,
  total: 0,
  done: 0,
  ok: 0,
  failed: 0,
  logs: [],
  files: [], // { url, name, status: "waiting"|"sending"|"sent"|"error", error }
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function getSettings() {
  const stored = await chrome.storage.local.get(Object.keys(DEFAULTS));
  return { ...DEFAULTS, ...stored };
}

function log(level, message) {
  const entry = { at: new Date().toISOString(), level, message: String(message).slice(0, 400) };
  state.logs.push(entry);
  if (state.logs.length > 500) state.logs.splice(0, state.logs.length - 500);
  broadcast();
}

function broadcast() {
  chrome.storage.local.set({ uyapState: state });
  chrome.runtime.sendMessage({ type: "UYAP_STATE", state }).catch(() => {});
}

function safeName(url, label) {
  let base = (label || "").replace(/[\\/:*?"<>|]+/g, " ").trim();
  let ext = "";
  try {
    const path = decodeURIComponent(new URL(url).pathname.split("/").pop() || "");
    const match = /\.([a-z0-9]{2,5})$/i.exec(path);
    if (match) ext = `.${match[1].toLowerCase()}`;
    if (!base) base = path.replace(/\.[a-z0-9]{2,5}$/i, "") || "uyap-belge";
  } catch (_) {
    base = base || "uyap-belge";
  }
  if (!ext) ext = ".pdf"; // UYAP belgeleri uzantısız adreslerde çoğunlukla PDF döner
  const stamp = Math.abs(hash(url)).toString(36).slice(0, 6);
  return `${base.slice(0, 80) || "uyap-belge"}-${stamp}${ext}`;
}

function hash(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Chrome Downloads API ile tek dosya indir; timeout ve retry uygular. */
function downloadOne(url, filename, timeoutMs) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        reject(new Error("zaman aşımı (30 sn)"));
      }
    }, timeoutMs);

    chrome.downloads.download({ url, filename, conflictAction: "uniquify" }, (id) => {
      if (chrome.runtime.lastError || !id) {
        if (!settled) {
          settled = true;
          clearTimeout(timer);
          reject(new Error(chrome.runtime.lastError?.message || "indirme başlatılamadı"));
        }
        return;
      }
      const listener = (delta) => {
        if (delta.id !== id) return;
        if (delta.state?.current === "complete") {
          finish(() => resolve(id));
        } else if (delta.state?.current === "interrupted") {
          finish(() => reject(new Error(delta.error?.current || "indirme kesildi")));
        }
      };
      const finish = (action) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        chrome.downloads.onChanged.removeListener(listener);
        action();
      };
      chrome.downloads.onChanged.addListener(listener);
    });
  });
}

/** Opsiyonel API kaynağından sayfalı belge listesi çeker. */
async function fetchFromApi(settings) {
  if (!settings.apiUrl) return [];
  const results = [];
  for (let page = 1; page <= settings.maxPages; page++) {
    if (state.cancelled) break;
    const url = `${settings.apiUrl}${settings.apiUrl.includes("?") ? "&" : "?"}page=${page}&limit=50`;
    try {
      const headers = { Accept: "application/json" };
      if (settings.apiKey) headers["Authorization"] = `Bearer ${settings.apiKey}`;
      const res = await fetch(url, { credentials: "include", headers });
      if (!res.ok) {
        log("warn", `API sayfa ${page}: HTTP ${res.status}`);
        break;
      }
      const data = await res.json();
      const items = Array.isArray(data) ? data : data.items || data.data || data.content || [];
      if (!items.length) break;
      items.forEach((item) => {
        const link = item.url || item.link || item.downloadUrl || item.dosyaUrl;
        if (link) results.push({ url: link, name: item.name || item.dosyaAdi || item.title || "" });
      });
      log("info", `API sayfa ${page}: ${items.length} kayıt`);
      await sleep(settings.delayMs);
    } catch (error) {
      log("error", `API sayfa ${page} hatası: ${error.message}`);
      break;
    }
  }
  return results;
}

/** Aktif sekmede sayfalama yaparak DOM'dan belge toplar. */
async function collectFromTab(tabId, settings) {
  const map = new Map();
  for (let page = 1; page <= settings.maxPages; page++) {
    if (state.cancelled) break;
    let response;
    try {
      response = await chrome.tabs.sendMessage(tabId, { type: "UYAP_COLLECT" });
    } catch (error) {
      log("error", `Sayfa okunamadı: ${error.message}. UYAP sekmesini yenileyip tekrar dene.`);
      break;
    }
    (response?.documents || []).forEach((doc) => {
      if (!map.has(doc.url)) map.set(doc.url, doc.name);
    });
    log("info", `Sayfa ${page}: toplam ${map.size} belge adresi bulundu`);

    let next;
    try {
      next = await chrome.tabs.sendMessage(tabId, { type: "UYAP_NEXT_PAGE" });
    } catch (_) {
      next = { moved: false };
    }
    if (!next?.moved) break;
    await sleep(Math.max(settings.delayMs, 1000)); // yeni sayfanın yüklenmesini bekle
  }
  return [...map.entries()].map(([url, name]) => ({ url, name }));
}

async function start() {
  if (state.running) return { ok: false, error: "İşlem zaten sürüyor." };
  const settings = await getSettings();
  state = {
    running: true,
    cancelled: false,
    total: 0,
    done: 0,
    ok: 0,
    failed: 0,
    logs: [],
    files: state.files || [],
  };
  log("info", "Tarama başladı.");

  const tab = await resolveUyapTab();
  if (!tab) {
    log("error", "Aktif sekme UYAP değil. UYAP Vatandaş Portalı sekmesini açıp tekrar dene.");
    state.running = false;
    broadcast();
    return { ok: false, error: "UYAP sekmesi bulunamadı." };
  }

  try {
    const fromDom = await collectFromTab(tab.id, settings);
    const fromApi = await fetchFromApi(settings);
    const merged = new Map();
    [...fromDom, ...fromApi].forEach((doc) => {
      if (doc.url && !merged.has(doc.url)) merged.set(doc.url, doc.name);
    });
    const docs = [...merged.entries()].map(([url, name]) => ({ url, name }));

    state.total = docs.length;
    log("info", `${docs.length} belge indirilecek.`);
    broadcast();

    for (const doc of docs) {
      if (state.cancelled) {
        log("warn", "Kullanıcı işlemi durdurdu.");
        break;
      }
      const filename = `${settings.folder}/${safeName(doc.url, doc.name)}`;
      let lastError = null;
      for (let attempt = 0; attempt <= settings.retries; attempt++) {
        try {
          await downloadOne(doc.url, filename, settings.timeoutMs);
          lastError = null;
          break;
        } catch (error) {
          lastError = error;
          if (attempt < settings.retries) await sleep(settings.delayMs);
        }
      }
      state.done++;
      if (lastError) {
        state.failed++;
        log("error", `${filename} indirilemedi: ${lastError.message}`);
      } else {
        state.ok++;
        log("success", `${filename} indirildi.`);
      }
      broadcast();
      await sleep(settings.delayMs); // rate limiting
    }

    log("info", `Bitti. ${state.ok} başarılı, ${state.failed} hatalı.`);
  } catch (error) {
    log("error", `Beklenmeyen hata: ${error.message}`);
  } finally {
    state.running = false;
    broadcast();
  }
  return { ok: true };
}

/* ---------- Dosya listesi: teker teker oku ve JURISAI'ye gönder ---------- */

function bytesToBase64(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function setFileStatus(url, status, error) {
  const item = state.files.find((f) => f.url === url);
  if (item) {
    item.status = status;
    item.error = error || null;
  }
  broadcast();
}

/** Aktif UYAP sekmesini gezerek belge listesini çıkarır (indirmeden). */
async function scanOnly() {
  const settings = await getSettings();
  const tab = await resolveUyapTab();
  if (!tab) {
    log("error", "Aktif sekme UYAP değil. UYAP sekmesini açıp tekrar dene.");
    return { ok: false, error: "UYAP sekmesi bulunamadı." };
  }
  const docs = await collectFromTab(tab.id, settings);
  state.files = docs.map((doc) => ({
    url: doc.url,
    name: safeName(doc.url, doc.name),
    status: "waiting",
    error: null,
  }));
  log("info", `${state.files.length} belge listelendi. Her belgeyi tek tek gönderebilirsin.`);
  broadcast();
  return { ok: true, files: state.files };
}

/** Tek belgeyi indirip JURISAI hesabına aktarır. */
async function sendOne(url) {
  const settings = await getSettings();
  const token = (settings.jurisaiToken || "").trim();
  const base = (settings.jurisaiApiUrl || DEFAULTS.jurisaiApiUrl).replace(/\/$/, "");
  const item = state.files.find((f) => f.url === url);
  const name = item?.name || safeName(url, "");
  if (token.length < 8) {
    setFileStatus(url, "error", "Bağlantı anahtarı yok");
    log("error", "JURISAI bağlantı anahtarını Ayarlar bölümüne kaydet.");
    return { ok: false, error: "Bağlantı anahtarı yok" };
  }
  setFileStatus(url, "sending");
  try {
    const res = await fetch(url.replace(/^http:\/\//i, "https://"), { credentials: "include" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const type = res.headers.get("content-type") || "";
    const buf = new Uint8Array(await res.arrayBuffer());
    if (!buf.length) throw new Error("boş yanıt");
    if (/text\/html/i.test(type)) throw new Error("belge değil (sayfa)");

    const upload = await fetch(`${base}/api/public/uyap-ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token,
        source: "uyap-dosya-cekici",
        files: [{ name, contentBase64: bytesToBase64(buf), mimeType: type || "application/pdf" }],
      }),
    });
    const out = await upload.json().catch(() => ({}));
    if (!upload.ok) throw new Error(out.error || `aktarım hatası (${upload.status})`);
    setFileStatus(url, "sent");
    log("success", `${name} JURISAI'ye aktarıldı (OCR için hazır).`);
    return { ok: true };
  } catch (error) {
    setFileStatus(url, "error", error.message);
    log("error", `${name} aktarılamadı: ${error.message}`);
    return { ok: false, error: error.message };
  }
}

/** Tek belgeyi bilgisayara indirir. */
async function downloadSingle(url) {
  const settings = await getSettings();
  const item = state.files.find((f) => f.url === url);
  const name = item?.name || safeName(url, "");
  try {
    await downloadOne(url, `${settings.folder}/${name}`, settings.timeoutMs);
    log("success", `${name} indirildi.`);
    return { ok: true };
  } catch (error) {
    log("error", `${name} indirilemedi: ${error.message}`);
    return { ok: false, error: error.message };
  }
}

/** UYAP oturum durumunu döndürür. */
/** Açık UYAP sekmesini bulur: önce aktif sekme, sonra diğer pencerelerdeki UYAP sekmeleri. */
async function resolveUyapTab() {
  const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (active && /uyap\.gov\.tr/i.test(active.url || "")) return active;
  const tabs = await chrome.tabs.query({ url: ["https://*.uyap.gov.tr/*"] });
  return tabs[0] || null;
}

async function sessionInfo() {
  const tab = await resolveUyapTab();
  if (!tab) return { ok: true, active: false, user: "", reason: "UYAP sekmesi açık değil" };

  const ask = async (options) => {
    try {
      return await chrome.tabs.sendMessage(tab.id, { type: "UYAP_SESSION" }, options);
    } catch (_) {
      return null;
    }
  };

  let res = (await ask({ frameId: 0 })) || (await ask(undefined));

  if (!res) {
    try {
      const [out] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => {
          const text = document.body?.innerText || "";
          const hasLoginForm =
            !!document.querySelector("input[type='password']") ||
            /e-devlet ile giriş yap|giriş yapınız|kullanıcı adı ve şifre/i.test(text);
          const hasPortal =
            /güvenli çıkış|çıkış yap|portal|uyap işlemlerim|dosya sorgula|menü ara|duyurular/i.test(
              text,
            ) || document.querySelectorAll("a,button,table").length > 10;
          return { ok: true, active: !hasLoginForm && hasPortal, user: "" };
        },
      });
      res = out?.result || null;
    } catch (_) {
      return {
        ok: true,
        active: false,
        user: "",
        reason: "Sayfa okunamadı, UYAP sekmesini yenile",
      };
    }
  }

  if (!res)
    return { ok: true, active: false, user: "", reason: "Sayfa okunamadı, UYAP sekmesini yenile" };
  return {
    ok: true,
    active: !!res.active,
    user: res.user || "",
    reason: res.active ? "" : "UYAP'ta oturum açık görünmüyor",
  };
}

/** TEK TUŞ: UYAP'ı tara, tüm belgeleri JURISAI'ye aktar, sonra otomatik dilekçe akışını aç. */
async function autoRun() {
  if (state.running) return { ok: false, error: "İşlem zaten sürüyor." };
  const settings = await getSettings();
  state = {
    running: true,
    cancelled: false,
    total: 0,
    done: 0,
    ok: 0,
    failed: 0,
    logs: [],
    files: [],
  };
  log("info", "Otomatik akış başladı.");

  const session = await sessionInfo();
  if (!session.active) {
    log("error", session.reason || "UYAP oturumu bulunamadı. UYAP'ta oturum aç.");
    state.running = false;
    broadcast();
    return { ok: false, error: "UYAP oturumu yok" };
  }
  log("success", `UYAP oturumu aktif${session.user ? ` (${session.user})` : ""}.`);

  const scan = await scanOnly();
  if (!scan.ok) {
    state.running = false;
    broadcast();
    return scan;
  }
  state.total = state.files.length;
  broadcast();

  for (let i = 0; i < state.files.length; i++) {
    if (state.cancelled) {
      log("warn", "Otomasyon durduruldu.");
      break;
    }
    const item = state.files[i];
    log("info", `[${i + 1}/${state.total}] ${item.name} aktarılıyor…`);
    const res = await sendOne(item.url);
    state.done = i + 1;
    if (res.ok) state.ok++;
    else state.failed++;
    broadcast();
    await sleep(settings.delayMs);
  }

  log("info", `Aktarım bitti: ${state.ok} başarılı, ${state.failed} hatalı.`);
  state.running = false;
  broadcast();

  if (state.ok > 0) {
    const base = (settings.jurisaiApiUrl || DEFAULTS.jurisaiApiUrl).replace(/\/$/, "");
    chrome.tabs.create({ url: `${base}/dashboard/automation?auto=1` });
    log("success", "JURISAI açıldı; OCR ve dilekçe yazımı otomatik başlıyor.");
  }
  return { ok: true, sent: state.ok, failed: state.failed };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "UYAP_START") {
    start().then(sendResponse);
    return true;
  }
  if (message?.type === "UYAP_STOP") {
    state.cancelled = true;
    log("warn", "Durdurma isteği alındı.");
    sendResponse({ ok: true });
    return true;
  }
  if (message?.type === "UYAP_GET_STATE") {
    sendResponse({ ok: true, state });
    return true;
  }
  if (message?.type === "UYAP_AUTO_START") {
    autoRun().then(sendResponse);
    return true;
  }
  if (message?.type === "UYAP_SESSION_INFO") {
    sessionInfo().then(sendResponse);
    return true;
  }
  if (message?.type === "UYAP_SCAN") {
    scanOnly().then(sendResponse);
    return true;
  }
  if (message?.type === "UYAP_SEND_ONE") {
    sendOne(message.url).then(sendResponse);
    return true;
  }
  if (message?.type === "UYAP_DOWNLOAD_ONE") {
    downloadSingle(message.url).then(sendResponse);
    return true;
  }
  if (message?.type === "UYAP_CLEAR_LOGS") {
    state.logs = [];
    broadcast();
    sendResponse({ ok: true });
    return true;
  }
  return false;
});

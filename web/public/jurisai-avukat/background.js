/* JurisAI - service worker (Manifest V3)
   Content script'ten gelen aktarım isteğini alır, belgeyi UYAP oturum çerezleriyle
   indirir ve multipart/form-data olarak JurisAI API'sine POST eder.

   Gizlilik varsayılanları: otomatik aktarım ve bilgisayara yerel kopya KAPALIDIR.
   Biri yalnızca kullanıcı ayar penceresinde açıkça açarsa çalışır. */

const DEFAULTS = {
  apiUrl: "http://localhost:8766/api/public/v1/documents/upload",
  apiKey: "",
  throttleMs: 1500,
  timeoutMs: 45000,
  autoSync: false,
  saveLocal: false,
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let lastRequestAt = 0;

async function getSettings() {
  const stored = await chrome.storage.sync.get(Object.keys(DEFAULTS));
  const settings = { ...DEFAULTS, ...stored };
  if (!settings.apiUrl || /api\.jurisai\.local/i.test(settings.apiUrl)) {
    settings.apiUrl = DEFAULTS.apiUrl;
    await chrome.storage.sync.set({ apiUrl: settings.apiUrl });
  }
  return settings;
}

/** İstekler arasına gecikme koyar (portal oturumunu korumak için). */
async function throttle(gap) {
  const wait = lastRequestAt + gap - Date.now();
  if (wait > 0) await sleep(wait);
  lastRequestAt = Date.now();
}

function fileNameFor(meta, contentType) {
  let base = (meta.evrakAdi || "uyap-evrak").replace(/[\\/:*?"<>|]+/g, " ").trim() || "uyap-evrak";
  if (/\.(pdf|udf|odt|docx?|tiff?|jpe?g|png|eyp|txt)$/i.test(base)) return base.slice(0, 160);
  const map = {
    "application/pdf": ".pdf",
    "application/zip": ".udf",
    "application/vnd.oasis.opendocument.text": ".odt",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/tiff": ".tif",
  };
  const fromUrl = /\.(pdf|udf|odt|docx?|tiff?|jpe?g|png|eyp)(\?|#|$)/i.exec(meta.url || "");
  const ext = fromUrl
    ? `.${fromUrl[1].toLowerCase()}`
    : map[(contentType || "").split(";")[0]] || ".pdf";
  return `${base.slice(0, 140)}${ext}`;
}

/** Belgeyi kullanıcının UYAP oturumuyla indirir. */
/* Savunma katmanı (içerik betiği zaten süzer): yalnız UYAP'ın kendi alan adından belge indirilir. */
const SITE_HOST_RE = /(^|\.)(uyap|adalet)\.gov\.tr$/i;
function assertUyapUrl(url) {
  let host = "";
  try {
    host = new URL(url).hostname;
  } catch (_) {
    /* aşağıda reddedilir */
  }
  if (!SITE_HOST_RE.test(host)) throw new Error("UYAP dışı bir adresten belge indirilmez");
}

/* OTOMATİK aktarımda aynı içerik (SHA-256) bu oturumda bir kez gönderilir: sayfadaki sabit bir dosya
   farklı adlarla defalarca gönderilmesin. Servis çalışanı yeniden başlarsa kayıt sıfırlanır. */
const sentHashes = new Set();
async function sha256Hex(blob) {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function fetchDocument(url, timeoutMs) {
  assertUyapUrl(url);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      credentials: "include",
      signal: controller.signal,
      headers: { Accept: "application/pdf,application/octet-stream,*/*" },
    });
    if (!res.ok) throw new Error(`UYAP yanıtı HTTP ${res.status}`);
    const type = res.headers.get("content-type") || "";
    const blob = await res.blob();
    if (!blob.size) throw new Error("boş belge");
    if (/text\/html/i.test(type))
      throw new Error("belge yerine sayfa döndü (oturum kapanmış olabilir)");
    return { blob, type };
  } finally {
    clearTimeout(timer);
  }
}

/** Belgeyi kullanıcının bilgisayarına indirir (JurisAI klasörüne). Yalnız `saveLocal` açıksa. */
async function saveLocally(blob, name, contentType, enabled = false) {
  if (!enabled) return false;
  try {
    const buffer = new Uint8Array(await blob.arrayBuffer());
    let binary = "";
    const chunk = 0x8000;
    for (let i = 0; i < buffer.length; i += chunk) {
      binary += String.fromCharCode(...buffer.subarray(i, i + chunk));
    }
    const dataUrl = `data:${(contentType || "application/octet-stream").split(";")[0]};base64,${btoa(binary)}`;
    await chrome.downloads.download({
      url: dataUrl,
      filename: `NHR-Hukuk-UYAP/${name.replace(/[\\/]+/g, "_")}`,
      saveAs: false,
      conflictAction: "uniquify",
    });
    return true;
  } catch (_) {
    return false;
  }
}

/** Belgeyi Juris AI API'sine multipart/form-data ile yükler. */
async function uploadDocument(settings, meta, blob, contentType) {
  const form = new FormData();
  const name = fileNameFor(meta, contentType);
  form.append("file", blob, name);
  form.append("evrakAdi", name);
  form.append("evrakId", meta.evrakId || "");
  form.append("evrakTuru", meta.evrakTuru || "");
  form.append("dosyaEsasNo", meta.dosyaEsasNo || "");
  form.append("birim", meta.birim || "");
  form.append("kaynakUrl", meta.url || "");
  form.append("klasorYolu", meta.klasorYolu || "");
  form.append("source", "uyap-avukat-eklentisi");

  const res = await fetch(settings.apiUrl, {
    method: "POST",
    headers: { Authorization: `Bearer ${settings.apiKey}` },
    body: form,
  });
  const out = await res.json().catch(() => ({}));
  if (res.status === 401)
    throw new Error("JurisAI bağlantı anahtarı geçersiz: UYAP'a Bağlan sayfasında anahtarı yenile ve eklentiye yapıştır");
  if (!res.ok) throw new Error(out.error || `aktarım hatası (HTTP ${res.status})`);
  return out;
}

async function handleUpload(meta) {
  try {
    const settings = await getSettings();
    if (!settings.apiUrl) throw new Error("API adresi ayarlanmadı");
    if ((settings.apiKey || "").trim().length < 20) throw new Error("API anahtarı ayarlanmadı");
    if (!meta?.url) throw new Error("indirme adresi bulunamadı");

    await throttle(Number(settings.throttleMs) || DEFAULTS.throttleMs);
    const { blob, type } = await fetchDocument(
      meta.url,
      Number(settings.timeoutMs) || DEFAULTS.timeoutMs,
    );
    // Elle (düğmeye basarak) gönderim her zaman yapılır: kullanıcı belgeyi sildikten sonra yeniden
    // göndermek isteyebilir. İçerik özeti yinelenen denetimi yalnız otomatik aktarımda uygulanır.
    const saved = await saveLocally(blob, fileNameFor(meta, type), type, settings.saveLocal === true);
    const out = await uploadDocument(settings, meta, blob, type);
    return { ok: true, duplicate: !!out.duplicate, id: out.id || null, saved };
  } catch (error) {
    return { ok: false, error: error.message || "bilinmeyen hata" };
  }
}

/** Dosya detayındaki meta veriyi + evrakları tek seferde Juris AI'ya aktarır. */
async function handleAutoIngest(payload) {
  try {
    const settings = await getSettings();
    // Savunma katmanı: içerik betiği kapalıyken göndermese de, ayar kapalıysa burada da reddedilir.
    if (settings.autoSync !== true) throw new Error("Otomatik aktarım kapalı");
    if (!settings.apiUrl) throw new Error("API adresi ayarlanmadı");
    if ((settings.apiKey || "").trim().length < 20) throw new Error("API anahtarı ayarlanmadı");

    const meta = {
      evrakAdi: payload.mahkeme || payload.dosyaEsasNo || "UYAP Dosyası",
      evrakTuru: payload.evrakTuru || "",
      dosyaEsasNo: payload.dosyaEsasNo || "",
      birim: payload.mahkeme || "",
      url: payload.url || "",
    };

    const urls = [...new Set(payload.docUrls || [])].slice(0, 20);
    const timeoutMs = Number(settings.timeoutMs) || DEFAULTS.timeoutMs;
    const gap = Number(settings.throttleMs) || DEFAULTS.throttleMs;

    let sent = 0;
    let duplicates = 0;
    const errors = [];
    for (const url of urls) {
      try {
        await throttle(gap);
        const { blob, type } = await fetchDocument(url, timeoutMs);
        const digest = await sha256Hex(blob);
        if (sentHashes.has(digest)) {
          duplicates++; // aynı içerik bu oturumda zaten gönderildi
          continue;
        }
        await saveLocally(blob, fileNameFor({ ...meta, url }, type), type, settings.saveLocal === true);
        await uploadDocument(
          settings,
          { ...meta, url, evrakId: `${meta.dosyaEsasNo}-${sent}` },
          blob,
          type,
        );
        sentHashes.add(digest);
        sent++;
      } catch (error) {
        errors.push(error.message);
      }
    }

    // Evrak indirilemediyse en azından dosya künyesini metin olarak aktar. Yalnız gerçek bir dosyaya
    // (esas numarası belli) ve indirilmeye çalışılmış evraka bağlıysa: evrakı olmayan liste sayfasında ya
    // da yinelenen evrak atlandığında künye gönderilmez (canlıda her tıklamada sahte künye gelmişti).
    if (!sent && !duplicates && urls.length && payload.dosyaEsasNo) {
      const summary = [
        `Mahkeme/Birim: ${payload.mahkeme || "-"}`,
        `Dosya/Esas No: ${payload.dosyaEsasNo || "-"}`,
        `Duruşma Tarihi: ${payload.durusmaTarihi || "-"}`,
        `Taraf: ${payload.taraf || "-"}`,
        `Kaynak: ${payload.url || "-"}`,
        "",
        payload.ozet || "",
      ].join("\n");
      const name = `${(payload.dosyaEsasNo || "uyap-dosya").replace(/[^\w.-]+/g, "_")}-kunye.txt`;
      await throttle(gap);
      await uploadDocument(
        settings,
        { ...meta, evrakAdi: name, evrakId: `${meta.dosyaEsasNo}-kunye` },
        new Blob([summary], { type: "text/plain" }),
        "text/plain",
      );
      sent = 1;
    }

    return { ok: true, files: sent, errors: errors.slice(0, 3) };
  } catch (error) {
    return { ok: false, error: error.message || "bilinmeyen hata" };
  }
}

/* ---------- Tıklama kaydı (tanı) ----------
   İçerik betiği kaydı başlatınca indirme ve yeni sekme olayları da toplanır (oturum belleğinde, servis
   çalışanı kapansa da kaybolmaz). Yalnız YOL BİÇİMLERİ ve uzantı/MIME türü saklanır; ad ve içerik yok. */
const RECORD_KEY = "jurisaiRecording";
const maskDigits = (value) => String(value || "").replace(/\d+/g, "#");
function shapeOf(raw) {
  if (!raw) return "";
  if (/^blob:/i.test(raw)) return "blob:";
  if (/^data:/i.test(raw)) return `data:${(raw.slice(5).split(/[;,]/)[0] || "").slice(0, 40)}`;
  try {
    const url = new URL(raw);
    const keys = [...url.searchParams.keys()].slice(0, 8).join(",");
    return `${url.hostname}${maskDigits(url.pathname).slice(0, 80)}${keys ? "?" + keys : ""}`;
  } catch (_) {
    return "(çözümlenemedi)";
  }
}
async function recordingState() {
  const stored = await chrome.storage.session.get(RECORD_KEY);
  return stored[RECORD_KEY] || null;
}
async function recordBackgroundEvent(_state, event) {
  queueRecord(event);
}

/* Olaylar tek bir sırada yazılır (webRequest çok sayıda olayı aynı anda üretir; okuma-yazma yarışı olay kaybettirir). */
let recordQueue = Promise.resolve();
function queueRecord(event) {
  recordQueue = recordQueue
    .then(async () => {
      const state = await recordingState();
      if (!state) return;
      if (state.events.length < 500) state.events.push({ t: Date.now() - state.startedAt, ...event });
      await chrome.storage.session.set({ [RECORD_KEY]: state });
    })
    .catch(() => {});
}

/* Tarayıcı düzeyinde ağ kaydı (yalnız gözlem, hiçbir isteği değiştirmez/engellemez): iframe içindeki
   istekler dahil sekmenin istekleri. Saklananlar: yöntem, tür, çerçeve, YOL BİÇİMİ, form alan ADLARI,
   durum kodu, içerik türü ve "attachment/inline". Değerler, adlar ve sorgu değerleri saklanmaz. */
let recordingTabs = new Set();
chrome.storage.session.get(RECORD_KEY).then((stored) => {
  const state = stored[RECORD_KEY];
  if (state?.tabId != null) recordingTabs = new Set([state.tabId, ...(state.openedTabs || [])]);
});
const NET_FILTER = { urls: ["*://*.uyap.gov.tr/*", "*://*.adalet.gov.tr/*", "*://*.e-devlet.gov.tr/*"] };
const NET_STATIC_TYPES = new Set(["image", "stylesheet", "script", "font", "ping", "csp_report"]);
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (!recordingTabs.has(details.tabId) || NET_STATIC_TYPES.has(details.type)) return;
    const body = details.requestBody;
    queueRecord({
      kind: "request",
      id: details.requestId,
      method: details.method,
      type: details.type,
      frameId: details.frameId,
      parentFrameId: details.parentFrameId,
      url: shapeOf(details.url),
      bodyFields: body?.formData ? Object.keys(body.formData).slice(0, 12) : [],
      bodyRawBytes: body?.raw ? body.raw.reduce((sum, part) => sum + (part.bytes?.byteLength || 0), 0) : 0,
    });
  },
  NET_FILTER,
  ["requestBody"],
);
chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (!recordingTabs.has(details.tabId) || NET_STATIC_TYPES.has(details.type)) return;
    const header = (name) =>
      (details.responseHeaders || []).find((item) => item.name.toLowerCase() === name)?.value || "";
    queueRecord({
      kind: "response",
      id: details.requestId,
      status: details.statusCode,
      type: details.type,
      contentType: header("content-type").split(";")[0].slice(0, 60),
      disposition: (header("content-disposition").split(";")[0] || "").toLowerCase().slice(0, 20),
      length: Number(header("content-length")) || 0,
    });
  },
  NET_FILTER,
  ["responseHeaders"],
);
chrome.downloads.onCreated.addListener(async (item) => {
  const state = await recordingState();
  if (!state || item.byExtensionId === chrome.runtime.id) return;
  const source = item.finalUrl || item.url || "";
  await recordBackgroundEvent(state, {
    kind: "download",
    url: shapeOf(source),
    mime: item.mime || "",
    extension: (/\.([a-z0-9]{2,5})(\?|#|$)/i.exec(item.filename || source) || [])[1] || "",
    bytes: item.totalBytes || 0,
  });
});
chrome.tabs.onCreated.addListener(async (tab) => {
  const state = await recordingState();
  if (!state || tab.openerTabId !== state.tabId) return;
  state.openedTabs = [...(state.openedTabs || []), tab.id];
  recordingTabs.add(tab.id);
  await chrome.storage.session.set({ [RECORD_KEY]: state });
  await recordBackgroundEvent(state, { kind: "new_tab", url: shapeOf(tab.pendingUrl || tab.url || "") });
});
chrome.tabs.onUpdated.addListener(async (tabId, change) => {
  if (!change.url) return;
  const state = await recordingState();
  if (!state || !(state.openedTabs || []).includes(tabId)) return;
  await recordBackgroundEvent(state, { kind: "new_tab_url", url: shapeOf(change.url) });
});

/** Tanı/kayıt raporunu İndirilenler\NHR-Hukuk-UYAP altına JSON dosyası olarak yazar (kişisel veri içermez). */
async function saveReportFile(prefix, report) {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const file = `NHR-Hukuk-UYAP/${prefix}-${stamp}.json`;
  const json = JSON.stringify(report, null, 2);
  await chrome.downloads.download({
    url: `data:application/json;charset=utf-8,${encodeURIComponent(json)}`,
    filename: file,
    saveAs: false,
    conflictAction: "uniquify",
  });
  return file;
}

/* ---------- Dosya penceresindeki evrakları çekme ----------
   İçerik betiği ağaçtaki yaprağa tıklar; UYAP'ın ön izleme isteğinin (view_document_*) adresi burada
   YAKALANIR (webRequest, yalnız gözlem) ve belge bu adresten kullanıcının kendi oturumuyla indirilip
   JurisAI'ya yüklenir. Adres bellekte tutulur; kaydedilmez, günlüğe yazılmaz, içerik betiğine verilmez. */
let pull = null; // { tabId, expectedEvrakId, url }
let pullRun = null; // { hashes: Set } — aynı içerik bir çekmede bir kez gönderilir

const PULL_STATIC_RE = /\.(js|css|png|gif|jpe?g|svg|ico|woff2?|ttf|map)$/i;
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (!pull || details.tabId !== pull.tabId) return;
    try {
      const url = new URL(details.url);
      const name = url.pathname.split("/").pop() || "";
      // Teşhis için: tıklamadan sonra sayfanın yaptığı isteklerin yalnız dosya adı (rakamlar maskeli).
      if (pull.seen.length < 10 && name && !PULL_STATIC_RE.test(name)) pull.seen.push(name.replace(/\d+/g, "#"));
      // Her yaprak öncesinde `pull` sıfırlanır; yaprağın evrak_id'si isteğin evrakId'siyle ESİT olmak zorunda
      // değildir (gerçek portalda eşleşmeme olasılığı var), bu yüzden kimlik karşılaştırılmaz.
      if (/view_document/i.test(url.pathname)) pull.url = details.url;
      else if (/viewer\.jsp$/i.test(url.pathname) && !pull.viewerUrl) pull.viewerUrl = details.url;
    } catch (_) {
      /* çözümlenemeyen adres yoksayılır */
    }
  },
  { urls: ["*://*.uyap.gov.tr/*"] },
);

/** Gerçek belge isteği (view_document_*) yakalanamadıysa, ön izleme sayfasının (viewer.jsp) aynı sorgusundan türetilir. */
function pullTargetUrl() {
  if (pull?.url) return pull.url;
  if (!pull?.viewerUrl) return "";
  const derived = new URL(pull.viewerUrl);
  derived.pathname = derived.pathname.replace(/viewer\.jsp$/i, "view_document_brd.uyap");
  return derived.href;
}

async function handlePullFetch(meta) {
  try {
    const settings = await getSettings();
    const target = pullTargetUrl();
    if (!target) throw new Error("UYAP evrak adresi yakalanamadı");
    const { blob, type } = await fetchDocument(target, Number(settings.timeoutMs) || DEFAULTS.timeoutMs);
    const digest = await sha256Hex(blob);
    if (pullRun?.hashes.has(digest)) return { ok: true, sameContent: true };
    const out = await uploadDocument(settings, { ...meta, url: "" }, blob, type);
    pullRun?.hashes.add(digest);
    return { ok: true, duplicate: !!out.duplicate };
  } catch (error) {
    return { ok: false, error: error.message || "bilinmeyen hata" };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message?.type) {
    case "JURISAI_PULL_BEGIN":
      getSettings().then((settings) => {
        if (!settings.apiUrl) return sendResponse({ ok: false, error: "API adresi ayarlanmadı" });
        if ((settings.apiKey || "").trim().length < 20)
          return sendResponse({ ok: false, error: "Bağlantı anahtarı ayarlanmadı (eklenti penceresine yapıştır)" });
        pullRun = { hashes: new Set() };
        sendResponse({ ok: true, gapMs: Math.max(1500, Number(settings.throttleMs) || DEFAULTS.throttleMs) });
      });
      return true;
    case "JURISAI_PULL_ARM":
      pull = { tabId: sender.tab?.id ?? null, url: "", viewerUrl: "", seen: [] };
      sendResponse({ ok: true });
      return false;
    case "JURISAI_PULL_STATUS":
      sendResponse({ captured: !!(pull?.url || pull?.viewerUrl), exact: !!pull?.url, seen: pull?.seen || [] });
      return false;
    case "JURISAI_PULL_FETCH":
      handlePullFetch(message.meta || {}).then(sendResponse);
      return true;
    case "JURISAI_PULL_END":
      pull = null;
      pullRun = null;
      sendResponse({ ok: true });
      return false;
    default:
      return false;
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "JURISAI_RECORD_STARTED") {
    chrome.storage.session
      .set({ [RECORD_KEY]: { tabId: sender.tab?.id ?? null, startedAt: Date.now(), events: [], openedTabs: [] } })
      .then(() => {
        recordingTabs = new Set(sender.tab?.id != null ? [sender.tab.id] : []);
        sendResponse({ ok: true });
      });
    return true;
  }
  if (message?.type === "JURISAI_RECORD_FINISHED") {
    (async () => {
      try {
        await recordQueue; // bekleyen ağ olayları yazılsın
        const state = await recordingState();
        recordingTabs = new Set();
        await chrome.storage.session.remove(RECORD_KEY);
        const report = { ...message.report, backgroundEvents: state?.events || [] };
        sendResponse({ ok: true, file: await saveReportFile("tani-kayit", report) });
      } catch (error) {
        sendResponse({ ok: false, error: error.message || "bilinmeyen hata" });
      }
    })();
    return true;
  }
  if (message?.type === "JURISAI_SAVE_DIAGNOSIS") {
    saveReportFile("tani", message.report || {})
      .then((file) => sendResponse({ ok: true, file }))
      .catch((error) => sendResponse({ ok: false, error: error.message || "bilinmeyen hata" }));
    return true;
  }
  if (message?.type === "AUTO_INGEST_CASE") {
    handleAutoIngest(message.payload || {}).then(sendResponse);
    return true;
  }

  if (message?.type === "JURISAI_UPLOAD") {
    handleUpload(message.payload).then(sendResponse);
    return true;
  }
  if (message?.type === "JURISAI_TEST") {
    getSettings()
      .then(async (settings) => {
        try {
          if ((settings.apiKey || "").trim().length < 20) {
            sendResponse({ ok: false, error: "Bağlantı anahtarı eksik" });
            return;
          }
          const res = await fetch(settings.apiUrl, {
            method: "POST",
            headers: { Authorization: `Bearer ${settings.apiKey}` },
            body: new FormData(),
          });
          const out = await res.json().catch(() => ({}));
          // Canlı yükleme servisi, dosyasız bağlantı kontrolünde 400 döndürür.
          sendResponse({
            ok: res.status === 400 && /dosya/i.test(out.error || ""),
            status: res.status,
            error: res.status === 401 ? out.error : undefined,
          });
        } catch (error) {
          sendResponse({ ok: false, error: error.message });
        }
      })
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  return false;
});

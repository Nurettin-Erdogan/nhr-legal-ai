/* JurisAI - service worker (Manifest V3)
   Content script'ten gelen aktarım isteğini alır, belgeyi UYAP oturum çerezleriyle
   indirir ve multipart/form-data olarak JurisAI API'sine POST eder.

   Gizlilik varsayılanları: otomatik aktarım ve bilgisayara yerel kopya KAPALIDIR.
   Biri yalnızca kullanıcı ayar penceresinde açıkça açarsa çalışır. */

/* BUILD-CONFIG-BEGIN: mağaza paketi (scripts/build_store_extension.py) bu bloğu üretim değerleriyle değiştirir */
const BUILD = {
  store: false, // true: Chrome Web Mağazası paketi (kendi kendine güncelleme ve alarm yok, mağaza günceller)
  apiUrl: "http://localhost:8766/api/public/v1/documents/upload",
  webOrigins: ["http://localhost:3000"],
  updateManifestUrl: "http://localhost:3000/jurisai-avukat/manifest.json",
};
/* BUILD-CONFIG-END */

const DEFAULTS = {
  apiUrl: BUILD.apiUrl,
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
  const local = await chrome.storage.local.get("apiKey");
  if (stored.apiKey) {
    if (!local.apiKey) await chrome.storage.local.set({ apiKey: stored.apiKey });
    await chrome.storage.sync.remove("apiKey");
  }
  const settings = { ...DEFAULTS, ...stored, apiKey: local.apiKey || stored.apiKey || "" };
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
  const mime = (contentType || "").split(";")[0].trim().toLowerCase();
  // Kesin XML yanıtı eski/yanlış PDF adını geçersiz kılar. Bilinmeyen tür PDF değildir.
  if (mime === "application/xml" || mime === "text/xml") {
    const stem = (meta.evrakAdi || "uyap-evrak").replace(/[\\/:*?"<>|\x00-\x1f]+/g, " ").trim().replace(/\.[a-z0-9]{2,5}$/i, "") || "uyap-evrak";
    return `${stem.slice(0, 140)}.xml`;
  }
  if (/^[a-z0-9]{2,5}$/i.test(meta.fileExt || "") && !/\.(pdf|udf|odt|docx?|tiff?|jpe?g|png|eyp|txt|html|xml|zip)$/i.test(meta.evrakAdi || "")) {
    const clean = (meta.evrakAdi || "uyap-evrak").replace(/[\\/:*?"<>|]+/g, " ").trim() || "uyap-evrak";
    return `${clean.slice(0, 140)}.${meta.fileExt.toLowerCase()}`;
  }
  let base = (meta.evrakAdi || "uyap-evrak").replace(/[\\/:*?"<>|]+/g, " ").trim() || "uyap-evrak";
  if (/\.(pdf|udf|odt|docx?|tiff?|jpe?g|png|eyp|txt|html|xml|zip)$/i.test(base)) {
    const suffix = base.match(/\.[^.]+$/)[0];
    return `${base.slice(0, -suffix.length).slice(0, 140)}${suffix}`;
  }
  const map = {
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "application/vnd.oasis.opendocument.text": ".odt",
    "text/plain": ".txt",
    "text/html": ".html",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/tiff": ".tif",
  };
  const fromUrl = /\.(pdf|udf|odt|docx?|tiff?|jpe?g|png|eyp|xml|zip|txt)(\?|#|$)/i.exec(meta.url || "");
  const ext = fromUrl
    ? `.${fromUrl[1].toLowerCase()}`
    : map[mime] || ".bin";
  return `${base.slice(0, 140)}${ext}`;
}

/** Belgeyi kullanıcının UYAP oturumuyla indirir. */
/* Savunma katmanı (içerik betiği zaten süzer): yalnız UYAP'ın kendi alan adından belge indirilir. */
const SITE_HOST_RE = /(^|\.)(uyap|adalet)\.gov\.tr$/i;
/* Belge boyutu sınırı yoktur: indirilen parçalar bellekte biriktirilmez, tarayıcının Blob deposuna katılır (büyük ekler
   diske taşar) ve JurisAI'a aynı Blob'dan akıtılarak yüklenir. */
const BLOB_FOLD_BYTES = 8 * 1024 * 1024;
/** Bir indirmenin toplam üst süresi (yalnız bir güvenlik ağı): asıl zaman aşımı "veri gelmeden geçen süre"dir ve akan indirmeyi
    kesmez (UYAP büyük ekleri ~1 MB/sn verir; 2 saat ≈ 7 GB). */
const MAX_DOWNLOAD_MS = 2 * 60 * 60 * 1000;
function assertUyapUrl(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch (_) {
    /* aşağıda reddedilir */
  }
  if (parsed?.protocol !== "https:" || !SITE_HOST_RE.test(parsed.hostname))
    throw new Error("Yalnız güvenli UYAP adresinden belge indirilir");
}

/* OTOMATİK aktarımda aynı içerik (SHA-256) bu oturumda bir kez gönderilir: sayfadaki sabit bir dosya
   farklı adlarla defalarca gönderilmesin. Servis çalışanı yeniden başlarsa kayıt sıfırlanır. */
const sentHashes = new Set();
async function sha256Hex(blob) {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Geçici olabilecek hata: çağıran bir kez bekleyip aynı adresi yeniden dener. `notDocument`: UYAP belge yerine metin/sayfa döndürdü. */
function retryable(message) {
  return Object.assign(new Error(message), { retryable: true, notDocument: true });
}

/** UYAP'ın "Kaydet" (indirme) adresi, ön izleme adresinden türetilir.
    Gerçek Vatandaş Portalı'nda ölçüldü (2026-10-05): ağaçtaki "Kaydet" menüsü sayfanın `downloadDoc()` işlevini çağırır; o da
    `Application.getDownloadURL(yargiTuru)` ile ön izlemenin eşi olan adresi (view_document*_brd.uyap → download_document*_brd.uyap,
    kvkEvrakViewDocument → kvkEvrakDownloadDocument) aynı evrakId/dosyaId/yargiTuru ile ister. Ön izlemenin "boyutu çok büyük"
    dediği evrak (ör. taranmış JPEG vekâletname) bu adresten gerçek dosyasıyla gelir. Sorgu, kodlaması bozulmasın diye yeniden
    yazılmaz; yalnız `mimeType` çıkarılır. Tanınmayan adres için boş döner (tahminle istek yapılmaz). */
function downloadUrlFor(viewUrl) {
  try {
    const url = new URL(viewUrl);
    const cut = url.pathname.lastIndexOf("/") + 1;
    const name = url.pathname.slice(cut);
    let next = "";
    if (/^view_document(_[a-z]+)?_brd\.uyap$/i.test(name)) next = name.replace(/^view_document/i, "download_document");
    else if (/^kvkEvrakViewDocument_brd\.uyap$/i.test(name)) next = "kvkEvrakDownloadDocument_brd.uyap";
    if (!next) return "";
    const query = url.search.replace(/^\?/, "").split("&").filter((pair) => pair && !/^mimeType=/i.test(pair)).join("&");
    return `${url.origin}${url.pathname.slice(0, cut)}${next}${query ? `?${query}` : ""}`;
  } catch (_) {
    return "";
  }
}

/** UYAP'ın belge yerine döndürdüğü kısa metni ya da sayfanın başlık/metnini kullanıcıya göstermek için özetler.
    Rakamlar maskelenir (dosya/evrak numarası hata metnine sızmaz) ve uzunluk sınırlanır. */
async function uyapReplyText(blob, type) {
  try {
    let text = await blob.slice(0, 8192).text();
    if (/html/i.test(type)) {
      const title = (/<title[^>]*>([\s\S]*?)<\/title>/i.exec(text) || [])[1] || "";
      const body = text
        .replace(/<(script|style|head)[\s\S]*?<\/\1>/gi, " ")
        .replace(/<[^>]*>/g, " ");
      text = [title, body].map((part) => part.replace(/\s+/g, " ").trim()).filter(Boolean).join(" — ");
    }
    return text
      .replace(/&nbsp;/gi, " ")
      .replace(/&amp;/gi, "&")
      .replace(/\s+/g, " ")
      .replace(/\d+/g, "#")
      .trim()
      .slice(0, 120);
  } catch (_) {
    return "";
  }
}

// Yalnız düz metin karşılaştırması içindir; çözülen metin HTML olarak çalıştırılmaz.
function htmlDocumentText(html) {
  return html.replace(/<(script|style|head)[\s\S]*?<\/\1>/gi, " ")
    .replace(/<[^>]*>/g, " ")
    .replace(/&(?:nbsp|#160|#x0*a0);/gi, " ")
    .replace(/&#(x[\da-f]+|\d+);/gi, (_, code) => {
      const n = code[0].toLowerCase() === "x" ? parseInt(code.slice(1), 16) : Number(code);
      return n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : " ";
    })
    .normalize("NFKC").replace(/[İı]/g, "i").toLowerCase().replace(/\s+/g, " ");
}

// UYAP'ın Hata.html şablonu bir belge değildir. Ret, oturumun kesin olarak
// kapandığını kanıtlamaz; aynı imzalı/şifreli adresi bekleyip yinelemek yerine
// içerik betiği evrağa yeniden tıklayarak taze isteği yakalamalıdır.
function isUyapValidationPage(html) {
  const text = htmlDocumentText(html);
  return /hata\s+olu[şs]tu/.test(text) && /hata\s+mesaji\s*:/.test(text)
    && /do[ğg]rulama\s+hatasi/.test(text);
}

function isPassiveDocumentHtml(html) {
  // Makbuz/KEP şablonları yalnız metin, tablo ve biçimlendirme içerir. Giriş/hata sayfaları
  // veya etkin içerik bu istisnadan yararlanamaz. Bu kontrol MIME türünden bağımsızdır.
  const unsafeMeta = [...html.matchAll(/<meta\b[^>]*>/gi)].some(([tag]) =>
    /http-equiv\s*=/i.test(tag) && !/http-equiv\s*=\s*["']?content-type(?:["'\s/>])/i.test(tag));
  return !unsafeMeta && !isUyapValidationPage(html) && !/<\s*(?:script|form|input|iframe|object|embed|base|link|svg|math|video|audio)\b|\bon\w+\s*=|(?:javascript|vbscript)\s*:/i.test(html)
    && !/oturumunuz\s+(?:sona\s+erdi|kapan)|oturum\s+aç|giriş\s+yap|yetkiniz\s+(?:yok|bulunm)|sistem\s+.{0,20}yoğun/i.test(htmlDocumentText(html));
}

async function decodeDocumentHtml(blob) {
  const raw = await blob.arrayBuffer();
  // Geçerli UTF-8 ikinci kez Windows-1254 diye yorumlanmaz: aksi halde "ERDİ"
  // gibi bir oturum uyarısı bozulur ve ikinci eşleşme denemesinde gözden kaçabilir.
  try { return new TextDecoder("utf-8", { fatal: true }).decode(raw); }
  catch (_) { return new TextDecoder("windows-1254").decode(raw); }
}

async function isUyapReceipt(blob, meta) {
  const type = String(meta?.evrakTuru || "").normalize("NFKC").trim();
  const name = String(meta?.evrakAdi || "").normalize("NFKC").trim();
  // Gerçek Vatandaş Portalı makbuz eklerini yalnız "Ek 75" vb. adla gösterir.
  // Başka bir evrak türünü HTML diye kabul etme: ekte tür VE dar ad biçimi eşleşir;
  // aşağıdaki makbuz başlığı/kurum/alan ve pasif içerik denetimleri aynen gereklidir.
  const receiptAttachment = /^ek$/i.test(type) && /^ek(?:\s+\d+)?$/i.test(name);
  if ((!/makbuz/i.test(`${type} ${name}`) && !receiptAttachment) || blob.size > 1024 * 1024) return false;
  const matches = (html) => {
    const body = htmlDocumentText(html);
    return /vekalet\s+pulu\s+makbuzu/i.test(body)
      && /adalet\s+bakanl[ıi][ğg][ıi]/i.test(body)
      && /makbuz\s*no/i.test(body)
      && isPassiveDocumentHtml(html);
  };
  return matches(await decodeDocumentHtml(blob));
}

/** Gerçek UYAP KEP cevaplarının üç pasif HTML şablonu. Her HTML evrak değildir:
    ağaçtaki evrak türü + KEP şablonu + adres/alanlar birlikte eşleşmelidir. */
async function isUyapKepDocument(blob, meta) {
  const title = `${meta?.evrakTuru || ""} ${meta?.evrakAdi || ""}`.normalize("NFKC").replace(/[İı]/g, "i").toLowerCase();
  // KEP iletisi de ağaçta yalnız "Ek 1" olabilir. Dar ek türü/adı yalnız metadata
  // kapısını açar; aşağıdaki KEP alanları, pasif içerik ve giriş/hata reddi zorunludur.
  const kepAttachment = /^ek$/i.test(String(meta?.evrakTuru || "").normalize("NFKC").trim())
    && /^ek(?:\s+\d+)?$/i.test(String(meta?.evrakAdi || "").normalize("NFKC").trim());
  if ((!/\bkep\b|haciz.{0,20}ihbar.{0,20}cevab/.test(title) && !kepAttachment) || blob.size > 1024 * 1024) return false;
  const matches = (html) => {
    if (!isPassiveDocumentHtml(html)) return false;
    const text = htmlDocumentText(html);
    // Bu UYAP şablonunun TAM metni yalnız bu tek satırdır; adres/konu alanı içermez.
    const notificationText = "ptt kephs'den bir elektronik postaniz var";
    if (text.trim() === notificationText) return true;
    const hasAddress = /[\w.+-]+@[\w.-]+\.(?:kep\.tr|tr)\b/.test(text);
    if (!hasAddress) return false;
    const envelope = /\bkep\s+(?:paketi|iletisi)\s*:/.test(text)
      && /\bkonu(?:su|lu)?\b/.test(text) && /\btarih(?:i(?:nde)?)?\b/.test(text);
    const notification = /ptt\s+kephs'den\s+bir\s+elektronik\s+postaniz\s+var/.test(text)
      && /\bptt(?:hs\d+)?\.kep\.tr\b/.test(text);
    return envelope || notification;
  };
  return matches(await decodeDocumentHtml(blob));
}

function responseByteLength(response) {
  // fetch sıkıştırılmış gövdeyi çözer; Content-Length ise sıkıştırılmış boydur.
  if (!/^(?:identity)?$/i.test(response.headers.get("content-encoding") || "")) return null;
  const raw = response.headers.get("content-length");
  const length = /^\d+$/.test(raw || "") ? Number(raw) : NaN;
  return Number.isSafeInteger(length) && length >= 0 ? length : null;
}

function strongDocumentEtag(response) {
  const tag = response.headers.get("etag") || "";
  return /^"[^"\r\n]{0,512}"$/.test(tag) ? tag : ""; // W/ etiketiyle bayt birleştirilmez.
}

function resumedDocumentLength(response, start, original, expectedTotal, etag) {
  const range = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(response.headers.get("content-range") || "");
  const numbers = range?.slice(1).map(Number);
  const mime = (r) => (r.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
  const invalid = response.status !== 206 || !numbers?.every(Number.isSafeInteger) ||
    numbers[0] !== start || numbers[1] !== numbers[2] - 1 || numbers[2] <= start ||
    (expectedTotal !== null && numbers[2] !== expectedTotal) ||
    strongDocumentEtag(response) !== etag || mime(response) !== mime(original) ||
    !/^(?:identity)?$/i.test(response.headers.get("content-encoding") || "") ||
    (response.url && original.url && response.url !== original.url) ||
    (responseByteLength(response) !== null && responseByteLength(response) !== numbers?.[2] - start);
  if (invalid) throw Object.assign(new Error("UYAP kaldığı yerden indirmeyi doğrulamadı; parçalar birleştirilmedi."), { retryable: true });
  return numbers[2];
}

function throwIfPullCancelled(signal) {
  if (signal?.aborted) throw Object.assign(new Error("Aktarım kullanıcı tarafından durduruldu."), { code: "UYAP_CANCELLED" });
}

async function pullWait(ms, signal) {
  if (!signal) return sleep(ms);
  throwIfPullCancelled(signal);
  await new Promise((resolve) => {
    const finish = () => { clearTimeout(timer); signal.removeEventListener("abort", finish); resolve(); };
    const timer = setTimeout(finish, ms);
    signal.addEventListener("abort", finish, { once: true });
  });
  throwIfPullCancelled(signal);
}

/** Güçlü ETag + doğrulanmış Content-Range varsa kesilen akışı en fazla iki kez sürdürür.
    Sunucu Range'i yok sayarsa, belge değişirse veya toplam boy uyuşmazsa parçalar ASLA birleştirilmez.
    Çerez/URL/evrak kimliği disk veya ayar deposuna yazılmaz; arabellek yalnız bu iş boyunca yaşar. */
async function readUyapDocument(url, timeoutMs, onProgress = null, signal = null) {
  throwIfPullCancelled(signal);
  assertUyapUrl(url);
  let controller;
  const cancel = () => controller?.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  let expired = false;
  let bytes = 0;
  let lastDataAt = null;
  const progress = (expectedBytes, resumes) => onProgress?.({
    receivedBytes: bytes, expectedBytes, lastDataAt, resumes,
  });
  // Yalnız etkin indirme boyunca: Chrome boşta kalan MV3 çalışanını 30 sn'de kapatabilir.
  // İçerik/kimlik göndermez, izin eklemez; iş bitince interval mutlaka temizlenir.
  const keepAlive = typeof chrome !== "undefined" && chrome.runtime?.getPlatformInfo
    ? setInterval(() => { chrome.runtime.getPlatformInfo().catch(() => {}); }, 20000) : null;
  // Büyük eklerde UYAP bazen uzun ara verir. İlk yanıt ve küçük evrak aynı sınırda;
  // 8 MB geldikten sonra normal 45 sn ayarında yalnız hareketsizlik payı 120 sn olur.
  // Özel kısa test/kullanıcı ayarı büyütülmez; toplam iki saatlik güvenlik ağı değişmez.
  const idleLimit = () => bytes >= BLOB_FOLD_BYTES && timeoutMs >= DEFAULTS.timeoutMs ? Math.max(timeoutMs, 120000) : timeoutMs;
  // Zaman aşımı veri geldikçe yeniden kurulur; yalnız "timeoutMs boyunca hiç veri gelmedi" ya da toplam üst süre kesintisidir.
  let timer;
  const arm = () => {
    clearTimeout(timer);
    timer = setTimeout(() => controller.abort(), idleLimit());
  };
  const hardStop = setTimeout(() => { expired = true; controller?.abort(); }, MAX_DOWNLOAD_MS);
  const stalled = (bytes) =>
    Object.assign(
      new Error(`UYAP ${Math.round(idleLimit() / 1000)} sn boyunca veri göndermedi; indirme durdu (${(bytes / 1048576).toFixed(1)} MB geldi).`),
      { retryable: true },
    );
  try {
    const request = async (headers = {}) => {
      throwIfPullCancelled(signal);
      controller = new AbortController();
      arm();
      let response;
      try {
        response = await fetch(url, {
          credentials: "include", cache: "no-store", signal: controller.signal,
          headers: { Accept: "application/pdf,application/octet-stream,*/*", ...headers },
        });
      } catch (error) {
        throwIfPullCancelled(signal);
        if (error?.name === "AbortError") throw stalled(bytes);
        throw error;
      }
      throwIfPullCancelled(signal);
      if (response.url) assertUyapUrl(response.url);
      if (!response.ok) throw new Error(`UYAP yanıtı HTTP ${response.status}`);
      return response;
    };
    // Parçalar önce küçük bir listede toplanır, `BLOB_FOLD_BYTES`'ı geçince Blob'a katılır: JS belleğinde en çok birkaç MB durur.
    let folded = new Blob([]);
    let pending = [];
    let pendingBytes = 0;
    const original = await request();
    if (original.status !== 200 || original.headers.has("content-range"))
      throw new Error("UYAP beklenmeyen kısmi belge döndürdü; kaydedilmedi.");
    let response = original;
    let expectedTotal = responseByteLength(original);
    progress(expectedTotal, 0);
    const etag = /^(?:identity)?$/i.test(original.headers.get("content-encoding") || "") ? strongDocumentEtag(original) : "";
    for (let resumes = 0; ; resumes += 1) {
      if (!response.body) throw new Error("UYAP belgesi okunamadı");
      const reader = response.body.getReader();
      let interrupted = null;
      try {
        while (true) {
          throwIfPullCancelled(signal);
          arm();
          let step;
          try { step = await reader.read(); }
          catch (error) {
            throwIfPullCancelled(signal);
            if (error?.name === "AbortError") throw stalled(bytes);
            throw Object.assign(new Error(`UYAP indirmeyi yarıda kesti (${(bytes / 1048576).toFixed(1)} MB geldi).`), { retryable: true });
          }
          throwIfPullCancelled(signal);
          if (step.done) break;
          bytes += step.value.byteLength;
          lastDataAt = Date.now();
          progress(expectedTotal, resumes);
          if (expectedTotal !== null && bytes > expectedTotal)
            throw new Error("UYAP belge boyutu doğrulanamadı; kaydedilmedi.");
          pending.push(step.value);
          pendingBytes += step.value.byteLength;
          if (pendingBytes >= BLOB_FOLD_BYTES) {
            folded = new Blob([folded, ...pending]);
            pending = [];
            pendingBytes = 0;
          }
        }
        if (expectedTotal !== null && bytes !== expectedTotal)
          throw Object.assign(new Error("UYAP indirmeyi yarıda kesti; belge boyutu eksik."), { retryable: true });
      } catch (error) { interrupted = error; }
      finally {
        clearTimeout(timer);
        if (interrupted) { controller.abort(); await reader.cancel().catch(() => {}); }
        reader.releaseLock();
      }
      if (!interrupted) break;
      throwIfPullCancelled(signal);
      if (!interrupted.retryable || !etag || !bytes || expired || resumes >= 2 ||
          (expectedTotal !== null && bytes >= expectedTotal)) throw interrupted;
      await pullWait(1000, signal); // sınırlı, sıralı devam isteği; portal paralelliği yok
      throwIfPullCancelled(signal);
      if (expired) throw interrupted;
      response = await request({ Range: `bytes=${bytes}-`, "If-Range": etag });
      try { expectedTotal = resumedDocumentLength(response, bytes, original, expectedTotal, etag); }
      catch (error) { controller.abort(); await response.body?.cancel().catch(() => {}); throw error; }
      progress(expectedTotal, resumes + 1);
    }
    return { original, blob: new Blob([folded, ...pending], { type: original.headers.get("content-type") || "" }) };
  } finally {
    signal?.removeEventListener("abort", cancel);
    clearTimeout(timer);
    clearTimeout(hardStop);
    if (keepAlive !== null) clearInterval(keepAlive);
    controller?.abort();
  }
}

async function fetchDocument(url, timeoutMs, meta = null, onProgress = null, signal = null) {
    const { original: res, blob } = await readUyapDocument(url, timeoutMs, onProgress, signal);
    throwIfPullCancelled(signal);
    let type = res.headers.get("content-type") || "";
    if (!blob.size) throw new Error("boş belge");
    // UYAP application/download altında XML, bazen giriş HTML'i döndürüyor.
    // Küçük başlığı oku; büyük belgenin tamamını JS belleğine kopyalama.
    const head = (await blob.slice(0, 4096).text()).replace(/^\uFEFF/, "").trimStart();
    if (/^%PDF-/.test(head)) type = "application/pdf";
    else if (/^<\?xml(?:\s|\?>)|^<dava(?:\s|>)/i.test(head)) type = "application/xml";
    else if (/^<!doctype\s+html|^<html(?:\s|>)/i.test(head)) type = "text/html";
    if (/text\/html/i.test(type)) {
      if (isUyapValidationPage(await decodeDocumentHtml(blob.slice(0, 8192)))) {
        throw Object.assign(new Error("UYAP indirme isteğini doğrulamadı (Doğrulama hatası). Dosyayı UYAP'ta yeniden açıp evrakı tekrar seçin; aynı adresle yeniden denenmedi. Bu mesaj tek başına oturumun kapandığını göstermez."),
          { code: "UYAP_VALIDATION_FAILED", notDocument: true, freshRequestRequired: true });
      }
      // UYAP bazı makbuzları PDF yerine gerçek HTML belge olarak sunar. Yalnızca
      // başlığı ve resmî makbuz alanları eşleşirse kabul et; giriş/hata sayfasını asla yükleme.
      if (await isUyapReceipt(blob, meta) || await isUyapKepDocument(blob, meta)) return { blob, type: "text/html", filename: "" };
      // Gerçek sebep (yetki yok, önizlenemiyor, oturum) UYAP'ın sayfa başlığında/metninde yazar; yalnız oturum
      // belirtisi varsa "oturum kapanmış olabilir" denir (aynı çekimde diğer evraklar geliyorsa yanıltıcıdır).
      const said = await uyapReplyText(blob, type);
      const sessionHint = !said || /giriş|oturum|login/i.test(said);
      throw retryable(`UYAP belge yerine sayfa döndürdü${said ? `: "${said}"` : ""}${sessionHint ? " (oturum kapanmış olabilir)" : ""}`);
    }
    // Önizlenemeyen evrakta UYAP belge yerine kısa bir düz metin (mesaj) döndürür: belge olarak kaydedilmez.
    if (/^text\//i.test(type) && blob.size < 1024) {
      const said = await uyapReplyText(blob, type);
      if (/boyutu\s+.{0,20}\s*büyük|evrakı\s+sisteminize\s+kaydederek/i.test(said)) {
        // Yeniden denemek işe yaramaz (kalıcı): çağıran belgeyi UYAP'ın "Kaydet" adresinden ister (handlePullFetch).
        throw Object.assign(
          new Error("UYAP bu evrakı önizlemede vermiyor: evrakı UYAP'taki Kaydet seçeneğiyle indirip JurisAI Dosyalar sayfasından yükleyin."),
          { previewRefused: true, notDocument: true },
        );
      }
      throw retryable(`UYAP belge yerine şu mesajı döndürdü: "${said}"`);
    }
    const disposition = res.headers.get("content-disposition") || "";
    const filename = (/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition) || [])[1] || "";
    return { blob, type, filename };
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

/** Bu kullanıcının JurisAI hesabında zaten bulunan evrak kimlikleri (yalnız ek bir hızlandırma: hata olursa hepsi çekilir). */
async function knownEvraks(ids, esas, birim, signal = null) {
  try {
    const settings = await getSettings();
    const url = String(settings.apiUrl || "").replace(/\/upload\/?$/, "/known");
    if (!/\/known$/.test(url) || (settings.apiKey || "").trim().length < 20) return { ok: false, known: [] };
    const controller = new AbortController();
    const cancel = () => controller.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      throwIfPullCancelled(signal);
      const res = await fetch(url, {
        method: "POST",
        headers: { Authorization: `Bearer ${settings.apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ evrakIds: ids.slice(0, 5000), dosyaEsasNo: esas || null, birim: birim || null }),
        signal: controller.signal,
      });
      const out = await res.json().catch(() => ({}));
      return res.ok && Array.isArray(out.known) ? { ok: true, known: out.known } : { ok: false, known: [] };
    } finally {
      signal?.removeEventListener("abort", cancel);
      clearTimeout(timer);
    }
  } catch (_) {
    return { ok: false, known: [] };
  }
}

/** Belgeyi Juris AI API'sine multipart/form-data ile yükler. */
async function uploadDocument(settings, meta, blob, contentType, signal = null) {
  throwIfPullCancelled(signal);
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

  let res;
  try {
    res = await fetch(settings.apiUrl, {
      method: "POST",
      headers: { Authorization: `Bearer ${settings.apiKey}` },
      body: form,
      signal,
    });
  } catch (_) {
    throwIfPullCancelled(signal);
    // Ağ/CORS/adres hatasında tarayıcı yalnız "Failed to fetch" der: kullanıcıya neyin denendiği söylenir.
    let host = "";
    try {
      host = new URL(settings.apiUrl).origin;
    } catch (_) {
      /* adres bozuksa boş kalır */
    }
    throw new Error(`JurisAI sunucusuna ulaşılamadı${host ? ` (${host})` : ""}: sunucunun çalıştığını ve eklenti ayarındaki adresi kontrol edin.`);
  }
  const out = await res.json().catch(() => ({}));
  throwIfPullCancelled(signal);
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

/* ---------- Kendi kendine güncelleme (geliştirme kurulumu) ----------
   Eklenti repodaki klasörden ("Paketlenmemiş öğe yükle") yüklüyse, dosyalar değiştiğinde (sürüm yükseldiğinde) kendini
   yeniden yükler ve açık UYAP sekmelerine yeni içerik betiğini yerleştirir: elle ↻ ya da F5 gerekmez.
   Sürümü geliştirme sunucusunun yayınladığı manifest'ten okur. Çekme/kayıt sürerken beklenir. Eklenti repodan değil eski bir
   klasörden yüklenmişse yeniden yükleme sürümü değiştirmez: bu durum açılır pencerede "eski klasörden çalışıyor" diye gösterilir. */
const UPDATE_MANIFEST_URL = BUILD.updateManifestUrl;
const UPDATE_ALARM = "jurisai-update-check";

function compareVersions(a, b) {
  const left = String(a).split(".").map((part) => parseInt(part, 10) || 0);
  const right = String(b).split(".").map((part) => parseInt(part, 10) || 0);
  for (let i = 0; i < Math.max(left.length, right.length); i += 1) {
    const diff = (left[i] || 0) - (right[i] || 0);
    if (diff) return diff > 0 ? 1 : -1;
  }
  return 0;
}
/** Karar saf bir işlevdir (test edilebilir): 'none' | 'wait' | 'reload' | 'stale'. */
function decideUpdate({ remote, current, tried, busy }) {
  if (!remote || compareVersions(remote, current) <= 0) return "none";
  if (busy) return "wait"; // çekme ya da kayıt sürüyor: yeniden yükleme bekler
  if (tried === remote) return "stale"; // bu sürüm için zaten yeniden yüklendi ama sürüm değişmedi
  return "reload";
}
async function checkForUpdate() {
  if (BUILD.store) return; // mağaza kurulumunu Chrome kendisi günceller
  try {
    const { autoUpdate } = await chrome.storage.local.get("autoUpdate");
    if (autoUpdate === false) return;
    const response = await fetch(UPDATE_MANIFEST_URL, { cache: "no-store" });
    if (!response.ok) return;
    const remote = (await response.json()).version;
    const current = chrome.runtime.getManifest().version;
    const { updateTried } = await chrome.storage.local.get("updateTried");
    const busy = !!pullRun || !!pull || !!(await recordingState());
    const decision = decideUpdate({ remote, current, tried: updateTried, busy });
    await chrome.storage.local.set({
      updateState: { stale: decision === "stale", remote: decision === "none" ? "" : remote, current },
    });
    if (decision === "reload") {
      await chrome.storage.local.set({ updateTried: remote });
      chrome.runtime.reload();
    }
  } catch (_) {
    /* geliştirme sunucusu kapalıysa sessizce geç */
  }
}
/** Yeniden yüklemeden sonra açık UYAP sekmelerine yeni içerik betiği yerleştirilir (F5 gerekmesin). */
/* ---------- JurisAI web uygulaması köprüsü ----------
   Komutlar yalnız JurisAI sayfasındaki köprü betiğinden (bridge.js) gelir; gönderenin kaynağı burada ayrıca denetlenir.
   JurisAI yayına alınınca gerçek alan adı hem burada hem manifest'teki bridge.js eşleşmesinde eklenmelidir. */
const WEB_ORIGINS = BUILD.webOrigins;
const UYAP_URLS = ["*://*.uyap.gov.tr/*", "*://*.adalet.gov.tr/*"];

function fromJurisaiWeb(sender) {
  try {
    return WEB_ORIGINS.includes(new URL(sender?.url || sender?.tab?.url || "").origin);
  } catch (_) {
    return false;
  }
}

const pendingPairings = new Map();

async function confirmPairing() {
  if (!chrome.windows?.create) return false;
  const requestId = crypto.randomUUID();
  const url = chrome.runtime.getURL(`approve.html?requestId=${encodeURIComponent(requestId)}`);
  return new Promise((resolve) => {
    let approvalWindowId = null;
    const finish = (approved) => {
      clearTimeout(timer);
      pendingPairings.delete(requestId);
      if (approvalWindowId) chrome.windows.remove(approvalWindowId).catch(() => {});
      resolve(approved);
    };
    const timer = setTimeout(() => finish(false), 90000);
    pendingPairings.set(requestId, finish);
    chrome.windows.create({ url, type: "popup", width: 460, height: 340 })
      .then((approvalWindow) => { approvalWindowId = approvalWindow?.id || null; })
      .catch(() => finish(false));
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "JURISAI_PAIRING_DECISION") return false;
  const expected = chrome.runtime.getURL("approve.html");
  if (sender.id !== chrome.runtime.id || !sender.url?.startsWith(`${expected}?`)) {
    sendResponse({ ok: false });
    return false;
  }
  const finish = pendingPairings.get(message.requestId);
  if (!finish) {
    sendResponse({ ok: false });
    return false;
  }
  finish(message.approved === true);
  sendResponse({ ok: true });
  return false;
});

const UYAP_HOST = /^https:\/\/([a-z0-9-]+\.)*(uyap|adalet)\.gov\.tr\//i;
const textArg = (value, max) => (typeof value === "string" && value.length <= max ? value : "");

/** Daha önce yanıt veren belirli bir UYAP sekmesine komut gönderir (iş durumu o sekmede tutulur). Yalnız UYAP sekmeleri kabul edilir. */
async function askTab(tabId, message) {
  if (!Number.isInteger(tabId)) return { ok: false, code: "bad_tab", error: "Geçersiz sekme" };
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  if (!tab || !UYAP_HOST.test(tab.url || "")) return { ok: false, code: "no_uyap_tab", error: "UYAP sekmesi kapanmış: UYAP'ı aç ve dosyaları yeniden listele." };
  const out = await chrome.tabs.sendMessage(tabId, message, { frameId: 0 }).catch(() => null);
  return out ? { ...out, tabId } : { ok: false, code: "no_content", error: "UYAP sekmesine ulaşılamadı: UYAP sayfasını yenile (F5)." };
}

/** UYAP sekmelerinden (en son kullanılan önce) ilkinin içerik betiğine komut gönderir; ilk başarılı yanıtı döndürür. */
async function askUyapTab(message, { focus = false } = {}) {
  const tabs = (await chrome.tabs.query({ url: UYAP_URLS })).sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0));
  if (!tabs.length) return { ok: false, code: "no_uyap_tab", error: "Açık bir UYAP sekmesi yok: UYAP'ı aç ve giriş yap." };
  let last = null;
  for (const tab of tabs) {
    const out = await chrome.tabs.sendMessage(tab.id, message, { frameId: 0 }).catch(() => null);
    if (out?.ok) {
      out.tabId = tab.id; // iş komutlarında (ağaç, aktarım) sonraki sorgular aynı sekmeye gider
      if (focus) {
        await chrome.tabs.update(tab.id, { active: true }).catch(() => {});
        await chrome.windows.update(tab.windowId, { focused: true }).catch(() => {});
      }
      return out;
    }
    last = out || last;
  }
  return last || { ok: false, code: "no_content", error: "UYAP sekmesine ulaşılamadı: UYAP sayfasını yenile (F5)." };
}

// Recovery never accepts a URL or switches accounts/tabs. Only the tab holding the
// exact, recently failed read-only job may approve a reload. No running pull is interrupted.
const recoveringTabs = new Set();
async function recoverReadTab(tabId, jobId) {
  if (!Number.isInteger(tabId) || !jobId) return { ok: false, code: "bad_tab", error: "Geçersiz toparlanma isteği." };
  if (recoveringTabs.has(tabId)) return { ok: false, code: "busy", error: "UYAP sayfası zaten toparlanıyor." };
  recoveringTabs.add(tabId);
  try {
    const before = await chrome.tabs.get(tabId).catch(() => null);
    if (!before || !UYAP_HOST.test(before.url || "")) return { ok: false, code: "no_uyap_tab", error: "UYAP sekmesi kapanmış." };
    const stampKey = `jurisai.readRecovery.${tabId}`;
    const stamps = await chrome.storage.session.get(stampKey);
    if (Date.now() - (Number(stamps[stampKey]) || 0) < 60000)
      return { ok: false, code: "recovery_limited", error: "UYAP sık yenilenmedi; sayfayı kontrol edip yeniden dene." };
    const ready = await askTab(tabId, { type: "JURISAI_PREPARE_RECOVERY", jobId });
    if (!ready.ok) return ready;
    const current = await chrome.tabs.get(tabId).catch(() => null);
    if (current?.url !== before.url) return { ok: false, code: "stale", error: "UYAP sayfası değişti; otomatik yenilenmedi." };
    await chrome.storage.session.set({ [stampKey]: Date.now() });
    await chrome.tabs.reload(tabId);
    const deadline = Date.now() + 40000;
    while (Date.now() < deadline) {
      await sleep(1000);
      const reply = await askTab(tabId, { type: "JURISAI_RECOVERY_READY" });
      if (reply.ok || !["no_content", "navigating"].includes(reply.code)) return reply;
    }
    return { ok: false, code: "recovery_failed", error: "UYAP yenilendi ama dosya listesi hazır olmadı; sayfayı kontrol et." };
  } finally {
    recoveringTabs.delete(tabId);
  }
}

async function handleBridge(type, payload) {
  switch (type) {
    case "BRIDGE_PING": {
      const settings = await getSettings();
      return { ok: true, version: chrome.runtime.getManifest().version, connected: (settings.apiKey || "").trim().length >= 20 };
    }
    case "BRIDGE_SET_KEY": {
      const key = String(payload?.key || "").trim();
      if (!/^jsai_[A-Za-z0-9]{20,200}$/.test(key)) return { ok: false, error: "Anahtar biçimi geçersiz" };
      // Sayfanın postMessage köprüsüne aynı origin'deki başka JS de ulaşabilir. Eklenti
      // penceresinde açık onay olmadan anahtar değişmez; anahtar senkronize depoya yazılmaz.
      if (!(await confirmPairing())) return { ok: false, code: "pairing_rejected", error: "Eklenti bağlantısı onaylanmadı" };
      await chrome.storage.local.set({ apiKey: key });
      await chrome.storage.sync.remove("apiKey");
      return { ok: true };
    }
    case "BRIDGE_TREE":
    case "BRIDGE_DETAIL": {
      const message = { type: type === "BRIDGE_TREE" ? "JURISAI_TREE" : "JURISAI_DETAIL", key: textArg(payload?.key, 600), yargiTuru: textArg(payload?.yargiTuru, 80) };
      return payload?.tabId === undefined ? askUyapTab(message) : askTab(payload.tabId, message);
    }
    case "BRIDGE_RECOVER_READ":
      return recoverReadTab(payload?.tabId, textArg(payload?.jobId, 64));
    case "BRIDGE_JOB_STATUS": {
      const out = await askTab(payload?.tabId, {
        type: "JURISAI_JOB_STATUS",
        jobId: textArg(payload?.jobId, 64),
        withTree: payload?.withTree === true,
        withDetail: payload?.withDetail === true,
      });
      // Yalnız aynı sekmedeki aynı canlı iş. URL, ETag, kimlik, başlık veya
      // belge içeriği web köprüsüne eklenmez; sayısal ilerleme bellekte kalır.
      if (out.ok && out.run && out.job?.state === "running" && out.job.kind === "pull" &&
          pullRun?.tabId === payload?.tabId && pullRun?.jobId === payload?.jobId && pullRun?.transfer) {
        out.run.phase = transferPhase(pullRun.transfer);
      }
      return out;
    }
    case "BRIDGE_PULL_IDS": {
      if (Array.isArray(payload?.ids) && payload.ids.length > 5000)
        return { ok: false, code: "too_many", error: "Bir aktarımda en fazla 5.000 evrak seç; kalanları sonraki aktarımda seç." };
      const ids = Array.isArray(payload?.ids) ? payload.ids.map((id) => textArg(id, 600)).filter(Boolean).slice(0, 5000) : [];
      if (!ids.length) return { ok: false, code: "empty", error: "Seçili evrak yok." };
      return askTab(payload?.tabId, { type: "JURISAI_PULL_IDS", ids, mode: payload?.mode === "disk" ? "disk" : "upload" });
    }
    case "BRIDGE_CURRENT_JOB":
      return askUyapTab({ type: "JURISAI_CURRENT_JOB" });
    case "BRIDGE_STOP_JOB":
    {
      const jobId = textArg(payload?.jobId, 64);
      const out = await askTab(payload?.tabId, { type: "JURISAI_BRIDGE_STOP", jobId });
      if (out.ok) abortPullRun(payload?.tabId, jobId);
      return out;
    }
    case "BRIDGE_LIST_DOSYALAR":
      return askUyapTab({ type: "JURISAI_LIST_DOSYALAR" });
    case "BRIDGE_OPEN_DOSYA":
      return askUyapTab({ type: "JURISAI_OPEN_DOSYA", key: textArg(payload?.key, 600), yargiTuru: textArg(payload?.yargiTuru, 80) }, { focus: true });
    default:
      return { ok: false, error: "Bilinmeyen komut" };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!/^BRIDGE_/.test(message?.type || "")) return false;
  if (!fromJurisaiWeb(sender)) {
    sendResponse({ ok: false, error: "Bu kaynaktan komut kabul edilmez" });
    return false;
  }
  handleBridge(message.type, message.payload || {})
    .then(sendResponse)
    .catch((error) => sendResponse({ ok: false, error: error?.message || "bilinmeyen hata" }));
  return true;
});

async function reinjectIntoOpenTabs() {
  try {
    // JurisAI sekmeleri: eklenti güncellenince eski köprü yetim kalır, yenisi yerleştirilir.
    for (const tab of await chrome.tabs.query({ url: WEB_ORIGINS.map((origin) => `${origin}/*`) })) {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["bridge.js"] }).catch(() => {});
    }
  } catch (_) {
    /* yoksay */
  }
  try {
    const tabs = await chrome.tabs.query({ url: ["*://*.uyap.gov.tr/*", "*://*.adalet.gov.tr/*"] });
    for (const tab of tabs) {
      try {
        await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, files: ["content.js"] });
        await chrome.scripting.insertCSS({ target: { tabId: tab.id, allFrames: true }, files: ["content.css"] });
      } catch (_) {
        /* bu sekmeye yerleştirilemedi (ör. yüklenmemiş): F5 ile gelir */
      }
    }
  } catch (_) {
    /* yoksay */
  }
}
chrome.runtime.onInstalled.addListener(() => {
  if (!BUILD.store) chrome.alarms.create(UPDATE_ALARM, { periodInMinutes: 0.5 });
  reinjectIntoOpenTabs();
  checkForUpdate();
});
chrome.runtime.onStartup.addListener(() => {
  if (!BUILD.store) chrome.alarms.create(UPDATE_ALARM, { periodInMinutes: 0.5 });
  checkForUpdate();
});
// Mağaza paketinde "alarms" izni yoktur: dinleyici yalnız geliştirme kurulumunda eklenir.
if (!BUILD.store) {
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === UPDATE_ALARM) checkForUpdate();
  });
}

/* ---------- Tıklama kaydı (tanı) ----------
   İçerik betiği kaydı başlatınca indirme ve yeni sekme olayları da toplanır (oturum belleğinde, servis
   çalışanı kapansa da kaybolmaz). Yalnız YOL BİÇİMLERİ ve uzantı/MIME türü saklanır; ad ve içerik yok. */
const RECORD_KEY = "jurisaiRecording";
const safeDecode = (value) => {
  try {
    return decodeURIComponent(String(value));
  } catch (_) {
    return String(value);
  }
};
const pathShape = (value) => String(value || "").split("/").map((part) => part ? ":segment" : "").join("/").slice(0, 80);
function shapeOf(raw) {
  if (!raw) return "";
  if (/^blob:/i.test(raw)) return "blob:";
  if (/^data:/i.test(raw)) return `data:${(raw.slice(5).split(/[;,]/)[0] || "").slice(0, 40)}`;
  try {
    const url = new URL(raw);
    return `${SITE_HOST_RE.test(url.hostname) ? "(UYAP)" : "(dış kaynak)"}${pathShape(url.pathname)}${url.search ? "?param" : ""}`;
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
      bodyFieldCount: body?.formData ? Object.keys(body.formData).length : 0,
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

/* ---------- Klasör yapısıyla bilgisayara indirme ----------
   İndirilenler\JurisAI-UYAP\<esas no + mahkeme>\<UYAP klasörleri>\<evrak>. JurisAI'ya hiçbir şey göndermez. */
const FS_BAD_CHARS = /[<>:"/\\|?*\u0000-\u001f]/g;
function fsSegment(text, fallback = "Evrak") {
  const cleaned = String(text || "")
    .replace(FS_BAD_CHARS, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[. ]+$/g, "")
    .slice(0, 80);
  return cleaned || fallback;
}
function folderDownloadPath(meta, contentType) {
  const dosya = fsSegment([meta.dosyaEsasNo, meta.birim].filter(Boolean).join(" "), "UYAP dosyasi");
  const folders = String(meta.klasorYolu || "")
    .split(" / ")
    .filter(Boolean)
    .map((part) => fsSegment(part, "Klasor"));
  const name = fsSegment(fileNameFor({ ...meta, url: "" }, contentType), "evrak");
  return ["JurisAI-UYAP", dosya, ...folders, name].join("/");
}
async function saveToFolder(blob, contentType, meta, signal = null) {
  throwIfPullCancelled(signal);
  const buffer = new Uint8Array(await blob.arrayBuffer());
  throwIfPullCancelled(signal);
  let binary = "";
  for (let i = 0; i < buffer.length; i += 0x8000) binary += String.fromCharCode(...buffer.subarray(i, i + 0x8000));
  const mime = (contentType || "application/octet-stream").split(";")[0];
  const filename = folderDownloadPath(meta, contentType);
  await chrome.downloads.download({
    url: `data:${mime};base64,${btoa(binary)}`,
    filename,
    saveAs: false,
    conflictAction: "uniquify", // aynı adlı iki evrak "(1)" soneki alır
  });
  return filename;
}

/* ---------- Dosya penceresindeki evrakları çekme ----------
   İçerik betiği ağaçtaki yaprağa tıklar; UYAP'ın ön izleme isteğinin (view_document_*) adresi burada
   YAKALANIR (webRequest, yalnız gözlem) ve belge bu adresten kullanıcının kendi oturumuyla indirilip
   JurisAI'ya yüklenir. Adres bellekte tutulur; kaydedilmez, günlüğe yazılmaz, içerik betiğine verilmez. */
let pull = null; // { tabId, expectedEvrakId, url }
let pullRun = null; // Etkin kullanıcı çekimi; evrak kimliği sunucuda tekilleştirilir.

// Başka sekme/iş eski bir END veya STOP ile etkin aktarımı iptal edemez.
function ownsPullRun(sender, jobId = pullRun?.jobId) {
  return !!pullRun && pullRun.tabId === sender.tab?.id && pullRun.frameId === (sender.frameId || 0)
    && pullRun.jobId === jobId;
}
function abortPullRun(tabId, jobId) {
  if (!pullRun || pullRun.tabId !== tabId || pullRun.jobId !== jobId) return false;
  pullRun.controller.abort();
  return true;
}

chrome.tabs.onRemoved.addListener((tabId) => {
  if (pullRun?.tabId === tabId) { pullRun.controller.abort(); pullRun = null; }
  if (pull?.tabId === tabId) pull = null;
});
chrome.tabs.onUpdated.addListener((tabId, change) => {
  // Yenileme/gezinme içerik betiğini yok eder: sahipsiz indirme devam etmez.
  if (change.status === "loading" && pullRun?.tabId === tabId) {
    pullRun.controller.abort(); pullRun = null;
    if (pull?.tabId === tabId) pull = null;
  }
});

/* Ön izleme önizleyemediği evrak için (ör. TIFF) belge yerine kısa bir metin döndürür ve gerçek dosyayı AYRI bir
   istekle (Content-Disposition: attachment) indirtir. O isteğin adresi de yakalanır; belge istendiğinde metin
   gelirse bu adres denenir. */
chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (!pull || details.tabId !== pull.tabId) return;
    try {
      const path = new URL(details.url).pathname;
      if (/view_document|viewer\.jsp/i.test(path)) return;
      const header = (name) =>
        (details.responseHeaders || []).find((item) => item.name.toLowerCase() === name)?.value || "";
      const type = header("content-type").toLowerCase();
      if (/attachment/i.test(header("content-disposition")) || /^(image\/tiff|application\/octet-stream)/.test(type)) {
        pull.altUrl = details.url;
      }
    } catch (_) {
      /* yoksay */
    }
  },
  { urls: ["*://*.uyap.gov.tr/*"] },
  ["responseHeaders"],
);

const PULL_STATIC_RE = /\.(js|css|png|gif|jpe?g|svg|ico|woff2?|ttf|map)$/i;
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (!pull || details.tabId !== pull.tabId) return;
    try {
      const url = new URL(details.url);
      const name = url.pathname.split("/").pop() || "";
      // Yalnız sabit kategorileri göster: sorgu, dosya/kişi numarası ve yol sızmasın.
      if (pull.seen.length < 10 && name && !PULL_STATIC_RE.test(name)) {
        const category = /view_document/i.test(name) ? "belge önizleme"
          : /viewer\.jsp/i.test(name) ? "görüntüleyici"
            : /indir|download/i.test(name) ? "indirme" : "diğer UYAP isteği";
        if (!pull.seen.includes(category)) pull.seen.push(category);
      }
      // Yaprağın `evrak_id` özniteliği isteğin `evrakId`siyle aynı olmak zorunda değildir (gerçek portalda şifreli ve
      // farklı); bu yüzden eşleştirme ön izleme sayfasının (viewer.jsp) kendi `evrakId`siyle yapılır: bu yaprak için
      // açılan ilk viewer.jsp'nin kimliği belirlenir, yalnız o kimlikle gelen belge istekleri bu yaprağa aittir. Önceki
      // yaprağın GECİKMİŞ (ya da ikinci aşama) isteği başka bir kimlik taşıdığından yok sayılır.
      if (/viewer\.jsp$/i.test(url.pathname)) {
        if (!pull.viewerUrl) {
          pull.viewerUrl = details.url;
          pull.viewerEvrakId = url.searchParams.get("evrakId") || "";
        }
      } else if (/view_document/i.test(url.pathname)) {
        const id = url.searchParams.get("evrakId") || "";
        if (pull.viewerEvrakId && id && id !== pull.viewerEvrakId) return;
        if (pull.viewerEvrakId) pull.url = details.url;
        else pull.loose = details.url; // viewer.jsp henüz görülmedi: yalnız son çare (aşağıya bak)
      }
    } catch (_) {
      /* çözümlenemeyen adres yoksayılır */
    }
  },
  { urls: ["*://*.uyap.gov.tr/*"] },
);

/** Gerçek belge isteği (view_document_*) yakalanamadıysa, ön izleme sayfasının (viewer.jsp) aynı sorgusundan türetilir. */
function pullTargetUrl() {
  if (pull?.url) return pull.url;
  if (!pull?.viewerUrl) return pull?.loose || "";
  const derived = new URL(pull.viewerUrl);
  derived.pathname = derived.pathname.replace(/viewer\.jsp$/i, "view_document_brd.uyap");
  return derived.href;
}

/** İçerik betiğinin kurduğu adres yalnız bilinen ön izleme adresi biçimindeyse kabul edilir (UYAP alan adı ayrıca denetlenir). */
function acceptedDirectUrl(url) {
  try {
    return /\/view_document(_[a-z]+)?_brd\.uyap$/i.test(new URL(url).pathname) ? url : "";
  } catch (_) {
    return "";
  }
}

function isTransientPullError(error) {
  return !!error?.retryable || error?.name === "AbortError" ||
    /HTTP (429|5\d\d)|zaman aşımı|abort/i.test(error?.message || "");
}

function transferPhase(transfer) {
  if (transfer.stage === "upload") return "Belge indirildi; JurisAI'ya kaydediliyor";
  if (transfer.stage === "waiting") return "UYAP yanıt başlıkları bekleniyor";
  const mb = (n) => (Math.max(0, Number(n) || 0) / 1048576).toFixed(1);
  const total = Number.isSafeInteger(transfer.expectedBytes) && transfer.expectedBytes > 0
    ? ` / ${mb(transfer.expectedBytes)} MB` : " MB (toplam boyut bildirilmedi)";
  const idle = transfer.lastDataAt ? Math.max(0, Math.floor((Date.now() - transfer.lastDataAt) / 1000)) : null;
  return `İndiriliyor: ${mb(transfer.receivedBytes)}${total}` +
    (idle !== null && idle >= 5 ? ` · ${idle} sn yeni veri yok` : "") +
    (transfer.resumes > 0 ? ` · sürdürme ${transfer.resumes}/2` : "");
}

async function handlePullFetch(meta, mode = "upload", direct = "") {
  const run = pullRun;
  const signal = run?.controller?.signal;
  try {
    const settings = await getSettings();
    throwIfPullCancelled(signal);
    const captured = pullTargetUrl();
    const viaDirect = !captured && !!acceptedDirectUrl(direct); // tıklamasız yol: başarısızsa beklemeden döner, çağıran tıklama yolunu dener
    const target = captured || acceptedDirectUrl(direct);
    if (!target) throw new Error("UYAP evrak adresi yakalanamadı");
    const timeout = Number(settings.timeoutMs) || DEFAULTS.timeoutMs;
    const startedAt = Date.now();
    let retried = false;
    let viaSave = false;
    let fetched;
    const fetchCurrent = (url, timeout, meta) => {
      throwIfPullCancelled(signal);
      if (run) run.transfer = { stage: "waiting" };
      return fetchDocument(url, timeout, meta, (value) => {
        if (run && pullRun === run) run.transfer = { stage: "download", ...value };
      }, signal);
    };
    try {
      fetched = await fetchCurrent(target, timeout, meta);
    } catch (error) {
      // Doğrulama reddinde türetilmiş Kaydet URL'si de aynı eski parametreleri
      // taşır. Doğrudan yolun çağıranı bir kez normal tıklama/yakalama yapar;
      // yakalanmış taze istek de reddedilirse ret açıkça kullanıcıya döner.
      if (error.freshRequestRequired || error.code === "UYAP_CANCELLED") throw error;
      const transient = isTransientPullError(error);
      // Ön izleme belge yerine metin/sayfa döndürdüyse gerçek dosya başka adrestedir: (1) UYAP'ın kendi başlattığı ayrı indirme
      // (ör. "Tiff görüntülenemediğinden indiriliyor"), (2) UYAP'ın "Kaydet" adresi (ör. "boyutu çok büyük").
      const saveUrl = error.notDocument ? downloadUrlFor(target) : "";
      if (pull?.altUrl) {
        fetched = await fetchCurrent(pull.altUrl, timeout, meta);
      } else if (saveUrl) {
        try {
          fetched = await fetchCurrent(saveUrl, timeout, meta);
          viaSave = true;
        } catch (saveError) {
          if (saveError.freshRequestRequired || saveError.code === "UYAP_CANCELLED") throw saveError;
          if (isTransientPullError(saveError) && !viaDirect) {
            // UYAP "Kaydet" akışını yarıda kesti: bir kez bekleyip aynı adresi yeniden dene.
            retried = true;
            await pullWait(8000, signal);
            fetched = await fetchCurrent(saveUrl, timeout, meta);
            viaSave = true;
          } else if (!transient || viaDirect) {
            // Kaydet'in asıl hata türünü koru: geçici indirme kesintisi,
            // mesajdaki "önizlemede vermiyor" yüzünden kalıcı ret sayılmamalı.
            // Doğrudan yolun çağıranı bu durumda normal tıklamayla taze istek yakalar.
            throw error.previewRefused
              ? Object.assign(new Error(`UYAP bu evrakı önizlemede vermiyor ve "Kaydet" adresinden de alınamadı: ${saveError.message}`),
                { previewRefused: true, retryable: isTransientPullError(saveError), ...(saveError.code ? { code: saveError.code } : {}) })
              : isTransientPullError(saveError) ? saveError : error;
          } else {
            retried = true;
            await pullWait(8000, signal);
            fetched = await fetchCurrent(target, timeout, meta);
          }
        }
      } else if (transient && !viaDirect) {
        // Geçici olabilir (yoğunluk, hazırlanıyor): bir kez bekleyip aynı adresi yeniden dene.
        retried = true;
        await pullWait(8000, signal);
        fetched = await fetchCurrent(target, timeout, meta);
      } else {
        throw error;
      }
    }
    const timing ={ download: Date.now() - startedAt, upload: 0, retried, viaSave };
    throwIfPullCancelled(signal);
    const { blob, type, filename } = fetched;
    if (filename) meta = { ...meta, fileExt: (/\.([A-Za-z0-9]{2,5})$/.exec(filename) || [])[1] || "" };
    // Farklı UYAP evrakları birebir aynı baytlara sahip olabilir (özellikle ekler).
    // İçerik hash'iyle atlamak bunları sessizce kaybettirir; sunucu evrak kimliğiyle tekilleştirir.
    const savingFrom = Date.now();
    if (run && pullRun === run) run.transfer = { stage: "upload" };
    if (mode === "disk") {
      await saveToFolder(blob, type, meta, signal);
      timing.upload = Date.now() - savingFrom;
      return { ok: true, saved: true, ms: timing };
    }
    const out = await uploadDocument(settings, { ...meta, url: "" }, blob, type, signal);
    timing.upload = Date.now() - savingFrom;
    return { ok: true, duplicate: !!out.duplicate, ms: timing };
  } catch (error) {
    return { ok: false, error: error.message || "bilinmeyen hata", ...(error.code ? { code: error.code } : {}),
      ...(error.code === "UYAP_CANCELLED" ? { stopped: true } : {}),
      ...(isTransientPullError(error) ? { retryable: true } : {}) };
  }
}

/* ---------- Doğrudan indirme denemesi ----------
   Soru: yaprağa tıklamadan, belge adresini kendimiz kurup indirebilir miyiz? Bu deneme yalnız ölçer: ilk iki evrağı
   normal yoldan (tıklayıp adresi yakalayarak) alır, ikincinin adresini birincinin şablonundan evrak_id değiştirerek kurar ve
   ikisinin SHA-256'sını karşılaştırır. Hiçbir belge saklanmaz/yüklenmez; rapora yalnız mantıksal sonuçlar, uzunluklar, durum
   kodları ve mimeType değerleri yazılır (kimlik/ad/içerik değeri yazılmaz). */
let probe = null; // { urls: [], attrIds: [] }

async function runDirectProbe(attrIds) {
  const [urlA, urlB] = probe?.urls || [];
  if (!urlA || !urlB) throw new Error("iki evrağın adresi yakalanamadı");
  const a = new URL(urlA);
  const b = new URL(urlB);
  const sha = async (blob) => (blob ? await sha256Hex(blob) : "");
  const get = async (url) => {
    const res = await fetch(url, { credentials: "include" });
    const blob = await res.blob();
    return { status: res.status, type: (res.headers.get("content-type") || "").split(";")[0], size: blob.size, hash: await sha(blob) };
  };
  const params = [];
  for (const [name, value] of a.searchParams) {
    const other = b.searchParams.get(name);
    params.push({
      sameInBothEvraks: other === value,
      length: value.length,
      equalsAttributeOfEvrakA: value === attrIds[0],
      equalsDecodedAttributeOfEvrakA: safeDecode(value) === safeDecode(attrIds[0]),
    });
  }
  const realB = await get(urlB);
  // Doğrudan kurulan adres: B'nin kimliğini A'nın şablonuna koy (evrakId'nin yaprak özniteliğine eşit olduğu varsayımı).
  const built = new URL(urlA);
  built.searchParams.set("evrakId", attrIds[1]);
  const mimeA = a.searchParams.get("mimeType");
  const mimeB = b.searchParams.get("mimeType");
  const direct = await get(built.href).catch(() => ({ error: "request_failed" }));
  // Evrak türü sorgusu (sayfanın kendi isteği): tek alan evrakId.
  let typeQuery = {};
  try {
    const ajx = `${a.origin}/main/jsp/vatandas/dosya_evrak_turu_brd.ajx`;
    const res = await fetch(ajx, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8" },
      body: `evrakId=${encodeURIComponent(attrIds[0])}`,
    });
    const text = await res.text();
    typeQuery = { status: res.status, contentType: (res.headers.get("content-type") || "").split(";")[0], responseLength: text.length };
  } catch (_) {
    typeQuery = { error: "request_failed" };
  }
  return {
    kind: "doğrudan indirme denemesi",
    pathShape: shapeOf(urlA),
    paramCount: a.searchParams.size,
    params,
    mimeTypeDiffersBetweenEvraks: mimeA !== mimeB,
    realB: { status: realB.status, type: realB.type, size: realB.size },
    direct: direct.error
      ? { error: direct.error }
      : {
          status: direct.status,
          type: direct.type,
          size: direct.size,
          sameBytesAsRealB: !!direct.hash && direct.hash === realB.hash,
        },
    typeQuery,
  };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (/^JURISAI_PULL_(?:BEGIN|ARM|STATUS|FETCH|CANCEL|WAIT|END)$/.test(message?.type || "") &&
      (!Number.isInteger(sender.tab?.id) || !UYAP_HOST.test(sender.url || sender.tab?.url || ""))) {
    sendResponse({ ok: false, code: "wrong_source", error: "Bu kaynaktan çekim komutu kabul edilmez." });
    return false;
  }
  switch (message?.type) {
    case "JURISAI_PROBE_BEGIN":
      probe = { urls: [] };
      sendResponse({ ok: true });
      return false;
    case "JURISAI_PROBE_KEEP":
      // Yakalanan gerçek adresi (yalnız bellekte) deneme için sakla; içerik betiğine geri verilmez.
      if (pull && probe) probe.urls.push(pullTargetUrl());
      sendResponse({ ok: !!(pull && probe && probe.urls[probe.urls.length - 1]) });
      return false;
    case "JURISAI_PROBE_RUN":
      runDirectProbe(message.attrIds || [])
        .then(async (report) => {
          probe = null;
          sendResponse({ ok: true, file: await saveReportFile("dogrudan-deneme", report), report });
        })
        .catch((error) => {
          probe = null;
          sendResponse({ ok: false, error: error.message || "bilinmeyen hata" });
        });
      return true;
    case "JURISAI_PULL_BEGIN":
      getSettings().then((settings) => {
        // Bilgisayara indirme JurisAI'ya bağlanmaz: anahtar/adres gerekmez.
        if (message.mode !== "disk") {
          if (!settings.apiUrl) return sendResponse({ ok: false, error: "API adresi ayarlanmadı" });
          if ((settings.apiKey || "").trim().length < 20)
            return sendResponse({ ok: false, error: "Bağlantı anahtarı ayarlanmadı (eklenti penceresine yapıştır)" });
        }
        if (pullRun) return sendResponse({ ok: false, code: "busy", error: "Başka bir evrak aktarımı sürüyor; önce durdurun." });
        pullRun = { tabId: sender.tab.id, frameId: sender.frameId || 0,
          jobId: textArg(message.jobId, 64), controller: new AbortController() };
        sendResponse({ ok: true, gapMs: Math.max(1500, Number(settings.throttleMs) || DEFAULTS.throttleMs) });
      });
      return true;
    case "JURISAI_PULL_ARM":
      if (pullRun && !ownsPullRun(sender)) { sendResponse({ ok: false, code: "wrong_job" }); return false; }
      pull = { tabId: sender.tab?.id ?? null, url: "", viewerUrl: "", viewerEvrakId: "", loose: "", altUrl: "", seen: [], armedAt: Date.now() };
      sendResponse({ ok: true });
      return false;
    case "JURISAI_PULL_STATUS":
      sendResponse({
        // viewer.jsp hiç gelmezse (başka evrak biçimi) gevşek adres yalnız 3 sn sonra kabul edilir: eski bir önizlemenin
        // gecikmiş isteği hemen "yakalandı" sayılmasın.
        captured: !!(pull?.url || pull?.viewerUrl || (pull?.loose && Date.now() - pull.armedAt > 3000)),
        exact: !!pull?.url,
        seen: pull?.seen || [],
      });
      return false;
    case "JURISAI_PULL_FETCH":
      if (!ownsPullRun(sender)) { sendResponse({ ok: false, code: "wrong_job" }); return false; }
      handlePullFetch(message.meta || {}, message.mode, message.direct || "").then(sendResponse);
      return true;
    case "JURISAI_MENU": {
      // UYAP yan menüsü `menuButtonClick("<sayı>")` işlevini çağırır; işlev sayfanın kendi dünyasındadır, içerik betiği (yalıtılmış dünya)
      // çağıramaz. Yalnız UYAP sekmesinden gelen, yalnız sayısal kimlik kabul edilir.
      const tabId = sender.tab?.id;
      if (tabId == null || !UYAP_HOST.test(sender.tab?.url || "") || !/^\d{1,8}$/.test(String(message.id))) {
        sendResponse({ ok: false });
        return false;
      }
      chrome.scripting
        .executeScript({
          target: { tabId, frameIds: [sender.frameId || 0] },
          world: "MAIN",
          func: (id) => (typeof window.menuButtonClick === "function" ? (window.menuButtonClick(id), true) : false),
          args: [String(message.id)],
        })
        .then((results) => sendResponse({ ok: !!results?.[0]?.result }))
        .catch(() => sendResponse({ ok: false }));
      return true;
    }
    case "JURISAI_SLEEP":
      // Gizli sekmedeki içerik betiği zamanlayıcıları kısılabilir: bekleme burada (servis çalışanında) yapılır.
      setTimeout(() => sendResponse({ ok: true }), Math.max(0, Math.min(60000, Number(message.ms) || 0)));
      return true;
    case "JURISAI_PULL_KNOWN":
      knownEvraks(message.ids || [], message.esas || "", message.birim || "",
        ownsPullRun(sender) ? pullRun.controller.signal : null).then(sendResponse);
      return true;
    case "JURISAI_PULL_WAIT":
      if (!ownsPullRun(sender, textArg(message.jobId, 64))) { sendResponse({ ok: false, code: "wrong_job" }); return false; }
      pullWait(Math.max(0, Math.min(20000, Number(message.ms) || 0)), pullRun.controller.signal)
        .then(() => sendResponse({ ok: true }))
        .catch(error => sendResponse({ ok: false, code: error.code }));
      return true;
    case "JURISAI_PULL_CANCEL":
      if (!ownsPullRun(sender, textArg(message.jobId, 64))) { sendResponse({ ok: false, code: "wrong_job" }); return false; }
      abortPullRun(sender.tab.id, pullRun.jobId);
      sendResponse({ ok: true });
      return false;
    case "JURISAI_PULL_END":
      if (ownsPullRun(sender, textArg(message.jobId, 64))) {
        pullRun.controller.abort();
        pullRun = null;
      }
      if (pull?.tabId === sender.tab.id && !pullRun) pull = null;
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

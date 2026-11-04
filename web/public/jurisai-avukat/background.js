/* JurisAI - service worker (Manifest V3)
   Content script'ten gelen aktarım isteğini alır, belgeyi UYAP oturum çerezleriyle
   indirir ve multipart/form-data olarak JurisAI API'sine POST eder.

   Gizlilik varsayılanları: otomatik aktarım ve bilgisayara yerel kopya KAPALIDIR.
   Biri yalnızca kullanıcı ayar penceresinde açıkça açarsa çalışır. */

/* BUILD-CONFIG-BEGIN: mağaza paketi (scripts/build_store_extension.py) bu bloğu üretim değerleriyle değiştirir */
const BUILD = {
  store: false, // true: Chrome Web Mağazası paketi (kendi kendine güncelleme ve alarm yok, mağaza günceller)
  apiUrl: "http://localhost:8766/api/public/v1/documents/upload",
  webOrigins: ["http://localhost:3000", "https://desktop-reflects-nyc-supervisor.trycloudflare.com"],
  updateManifestUrl: "http://localhost:3000/jurisai-avukat/manifest.json",
};
/* BUILD-CONFIG-END */

const DEFAULTS = {
  apiUrl: BUILD.apiUrl,
  apiKey: "",
  throttleMs: 1500,
  timeoutMs: 45000,
  // Takılan evrak aynı koşuda yeniden denenmeden önceki bekleme (2. denemede 2 katı, 3. denemede 4 katı).
  retryWaitMs: 15000,
  // Tıklamasız yolda aynı anda kaç evrak indirilir (1-3). Tıklama yolu her zaman tektir. Canlı ölçüm (2026-10-16, 191 evrak,
  // hatasız): 1 → 125 sn, 2 → 58 sn, 3 → 47 sn. Hata görülünce içerik betiği kendiliğinden teke iner (bkz. content.js).
  pullParallel: 3,
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
    const stem =
      (meta.evrakAdi || "uyap-evrak")
        .replace(/[\\/:*?"<>|\x00-\x1f]+/g, " ")
        .trim()
        .replace(/\.[a-z0-9]{2,5}$/i, "") || "uyap-evrak";
    return `${stem.slice(0, 140)}.xml`;
  }
  if (
    /^(pdf|udf|odt|docx?|tiff?|jpe?g|png|eyp|txt|html|xml|zip|rar|7z|xlsx?|pptx?|ods|odp|rtf|csv|eml|msg|p7[sm]|mp[34]|wav|m4a|wma|ogg|avi|wmv|mov|mpg|mpeg|3gp|mkv|bmp|gif|webp)$/i.test(
      meta.fileExt || "",
    )
  ) {
    const clean =
      (meta.evrakAdi || "uyap-evrak").replace(/[\\/:*?"<>|]+/g, " ").trim() || "uyap-evrak";
    return `${clean.replace(/\.[a-z0-9]{2,5}$/i, "").slice(0, 140)}.${meta.fileExt.toLowerCase()}`;
  }
  let base = (meta.evrakAdi || "uyap-evrak").replace(/[\\/:*?"<>|]+/g, " ").trim() || "uyap-evrak";
  if (
    /\.(pdf|udf|odt|docx?|tiff?|jpe?g|png|eyp|txt|html|xml|zip|rar|7z|xlsx?|pptx?|ods|odp|rtf|csv|eml|msg|p7[sm]|mp[34]|wav|m4a|wma|ogg|avi|wmv|mov|mpg|mpeg|3gp|mkv|bmp|gif|webp)$/i.test(
      base,
    )
  ) {
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
    "application/x-rar-compressed": ".rar",
    "application/vnd.rar": ".rar",
    "application/x-7z-compressed": ".7z",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.presentation": ".odp",
    "application/rtf": ".rtf",
    "text/rtf": ".rtf",
    "text/csv": ".csv",
    "image/bmp": ".bmp",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
    "audio/x-ms-wma": ".wma",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
    "video/x-ms-wmv": ".wmv",
    "video/mpeg": ".mpeg",
    "video/3gpp": ".3gp",
    "video/x-matroska": ".mkv",
    "message/rfc822": ".eml",
    "application/pkcs7-signature": ".p7s",
    "application/pkcs7-mime": ".p7m",
  };
  const fromUrl = /\.(pdf|udf|odt|docx?|tiff?|jpe?g|png|eyp|xml|zip|txt)(\?|#|$)/i.exec(
    meta.url || "",
  );
  const ext = fromUrl ? `.${fromUrl[1].toLowerCase()}` : map[mime] || ".bin";
  // Unknown formats still have an archive path. Retain a safe original suffix
  // inside the name, but the final .bin cannot be executed/previewed as that type.
  const originalExt = String(meta.fileExt || "").toLowerCase();
  if (
    ext === ".bin" &&
    /^[a-z0-9]{1,16}$/.test(originalExt) &&
    !base.toLowerCase().endsWith(`.${originalExt}`)
  )
    base += `.${originalExt}`;
  if (ext === ".bin" && /\.bin$/i.test(base)) return `${base.slice(0, -4).slice(0, 140)}.bin`;
  return `${base.slice(0, 140)}${ext}`;
}

/** Belgeyi kullanıcının UYAP oturumuyla indirir. */
/* Savunma katmanı (içerik betiği zaten süzer): yalnız UYAP'ın kendi alan adından belge indirilir. */
const SITE_HOST_RE = /(^|\.)(uyap|adalet)\.gov\.tr$/i;

function dispositionFileName(value) {
  const extended = /(?:^|;)\s*filename\*\s*=\s*(?:"([^"]*)"|([^;]*))/i.exec(value || "");
  const encoded = (extended?.[1] ?? extended?.[2] ?? "").trim();
  const utf8 = /^UTF-8'[^']*'(.*)$/i.exec(encoded);
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1]).replace(/[\x00-\x1f\x7f]/g, "");
    } catch (_) {
      /* ordinary filename fallback */
    }
  }
  const ordinary = /(?:^|;)\s*filename\s*=\s*(?:"((?:\\.|[^"\\])*)"|([^;]*))/i.exec(value || "");
  return (ordinary?.[1] ?? ordinary?.[2] ?? "")
    .replace(/\\(["\\])/g, "$1")
    .replace(/[\x00-\x1f\x7f]/g, "")
    .trim();
}

// Only unambiguous signatures; never guess that arbitrary binary bytes are PDF.
// Unknown bytes use the separate opaque .bin archive path, never a parser.
function binaryDocumentType(bytes) {
  const starts = (...prefix) => prefix.every((byte, index) => bytes[index] === byte);
  if (
    starts(0x50, 0x4b, 0x03, 0x04) ||
    starts(0x50, 0x4b, 0x05, 0x06) ||
    starts(0x50, 0x4b, 0x07, 0x08)
  )
    return "application/zip";
  if (starts(0x49, 0x49, 0x2a, 0) || starts(0x4d, 0x4d, 0, 0x2a)) return "image/tiff";
  if (starts(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)) return "image/png";
  if (starts(0xff, 0xd8, 0xff)) return "image/jpeg";
  if (starts(0x47, 0x49, 0x46, 0x38, 0x37, 0x61) || starts(0x47, 0x49, 0x46, 0x38, 0x39, 0x61))
    return "image/gif";
  if (starts(0x52, 0x61, 0x72, 0x21, 0x1a, 0x07)) return "application/vnd.rar";
  if (starts(0x37, 0x7a, 0xbc, 0xaf, 0x27, 0x1c)) return "application/x-7z-compressed";
  if (starts(0x52, 0x49, 0x46, 0x46) && bytes.length >= 12) {
    const kind = String.fromCharCode(...bytes.slice(8, 12));
    if (kind === "WEBP") return "image/webp";
    if (kind === "WAVE") return "audio/wav";
    if (kind === "AVI ") return "video/x-msvideo";
  }
  return "";
}
/* Belge boyutu sınırı yoktur: indirilen parçalar bellekte biriktirilmez, tarayıcının Blob deposuna katılır (büyük ekler
   diske taşar) ve JurisAI'a aynı Blob'dan akıtılarak yüklenir. */
const BLOB_FOLD_BYTES = 8 * 1024 * 1024;
const LARGE_IDLE_BYTES = 1024 * 1024;
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
    if (/^view_document(_[a-z]+)?_brd\.uyap$/i.test(name))
      next = name.replace(/^view_document/i, "download_document");
    else if (/^kvkEvrakViewDocument_brd\.uyap$/i.test(name))
      next = "kvkEvrakDownloadDocument_brd.uyap";
    if (!next) return "";
    const query = url.search
      .replace(/^\?/, "")
      .split("&")
      .filter((pair) => pair && !/^mimeType=/i.test(pair))
      .join("&");
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
      text = [title, body]
        .map((part) => part.replace(/\s+/g, " ").trim())
        .filter(Boolean)
        .join(" — ");
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
  return html
    .replace(/<(script|style|head)[\s\S]*?<\/\1>/gi, " ")
    .replace(/<[^>]*>/g, " ")
    .replace(/&(?:nbsp|#160|#x0*a0);/gi, " ")
    .replace(/&#(x[\da-f]+|\d+);/gi, (_, code) => {
      const n = code[0].toLowerCase() === "x" ? parseInt(code.slice(1), 16) : Number(code);
      return n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : " ";
    })
    .normalize("NFKC")
    .replace(/[İı]/g, "i")
    .toLowerCase()
    .replace(/\s+/g, " ");
}

// UYAP'ın Hata.html şablonu bir belge değildir. Ret, oturumun kesin olarak
// kapandığını kanıtlamaz; aynı imzalı/şifreli adresi bekleyip yinelemek yerine
// içerik betiği evrağa yeniden tıklayarak taze isteği yakalamalıdır.
function isUyapValidationPage(html) {
  const text = htmlDocumentText(html);
  return (
    /hata\s+olu[şs]tu/.test(text) &&
    /hata\s+mesaji\s*:/.test(text) &&
    /do[ğg]rulama\s+hatasi/.test(text)
  );
}

// Genel "Hata Oluştu", "Güvenli Çıkış" bağlantısı veya iç servis adresi,
// oturum kaybının kanıtı değildir. Yalnız açık kimlik doğrulama belirtisi kabul edilir.
function uyapHtmlFailureCode(html) {
  const text = htmlDocumentText(html);
  const title = htmlDocumentText((/<title[^>]*>([\s\S]*?)<\/title>/i.exec(html) || [])[1] || "");
  if (
    /oturum(?:unuz|un)?\s+(?:süresi\s+(?:dol|bit)|sona\s+er|kapan|zaman\s+aş)|geçerli\s+(?:bir\s+)?oturum\s+bulunama/.test(
      text,
    ) ||
    /(?:giriş|login|kimlik doğrulama)\s*(?:ekrani|sayfasi)$/.test(title.trim()) ||
    /<input\b[^>]*\btype\s*=\s*["']?password\b/i.test(html)
  )
    return "UYAP_SESSION_EXPIRED";
  if (/yetkiniz\s+(?:yok|bulunm)|erişim\s+(?:izniniz\s+yok|reddedildi)/.test(text))
    return "UYAP_ACCESS_DENIED";
  return "UYAP_PORTAL_ERROR";
}

// Art arda genel "Hata Oluştu" sayfası iki şey olabilir: evrağa özgü servis hatası ya da oturumun düşmesi. Gerçek
// aktarımda oturum dolunca UYAP giriş ekranı yerine bu genel sayfayı döndürdü (2026-10-13); öte yandan oturum açıkken de
// tek tek evraklarda görülebilir. Tahmin edilmez, ölçülür: UYAP sekmesinin kendi adresi salt okunur bir kez istenir.
// Açık oturumda bu adres normal portal sayfasıdır; hata ya da giriş ekranı dönerse oturum kapanmıştır.
async function probeUyapSession(url) {
  try {
    assertUyapUrl(url);
    const response = await fetch(url, {
      credentials: "include",
      cache: "no-store",
      redirect: "follow",
    });
    if (response.url && !SITE_HOST_RE.test(new URL(response.url).hostname)) return "expired"; // e-Devlet girişine yönlendi
    if (response.status === 401) return "expired";
    if (!response.ok) return "unknown";
    const html = (await response.text()).slice(0, 200000);
    const text = htmlDocumentText(html);
    if (uyapHtmlFailureCode(html) === "UYAP_SESSION_EXPIRED" || /hata\s+olu[şs]tu/.test(text))
      return "expired";
    if (
      /e-?devlet\s+ile\s+giriş|giriş\s+seçenekleri|e-?imza\s+ile\s+giriş/.test(text) &&
      !/kill_session|logout/i.test(html)
    )
      return "expired";
    return "alive";
  } catch (_) {
    return "unknown"; // ağ hatası oturum hakkında bir şey kanıtlamaz
  }
}

function isPassiveDocumentHtml(html) {
  // Makbuz/KEP şablonları yalnız metin, tablo ve biçimlendirme içerir. Giriş/hata sayfaları
  // veya etkin içerik bu istisnadan yararlanamaz. Bu kontrol MIME türünden bağımsızdır.
  const unsafeMeta = [...html.matchAll(/<meta\b[^>]*>/gi)].some(
    ([tag]) =>
      /http-equiv\s*=/i.test(tag) && !/http-equiv\s*=\s*["']?content-type(?:["'\s/>])/i.test(tag),
  );
  return (
    !unsafeMeta &&
    !isUyapValidationPage(html) &&
    !/<\s*(?:script|form|input|iframe|object|embed|base|link|svg|math|video|audio)\b|\bon\w+\s*=|(?:javascript|vbscript)\s*:/i.test(
      html,
    ) &&
    !/oturumunuz\s+(?:sona\s+erdi|kapan)|oturum\s+aç|giriş\s+yap|yetkiniz\s+(?:yok|bulunm)|sistem\s+.{0,20}yoğun/i.test(
      htmlDocumentText(html),
    )
  );
}

async function decodeDocumentHtml(blob) {
  const raw = await blob.arrayBuffer();
  const bytes = new Uint8Array(raw);
  if (bytes[0] === 0xff && bytes[1] === 0xfe) return new TextDecoder("utf-16le").decode(raw);
  if (bytes[0] === 0xfe && bytes[1] === 0xff) return new TextDecoder("utf-16be").decode(raw);
  // Geçerli UTF-8 ikinci kez Windows-1254 diye yorumlanmaz: aksi halde "ERDİ"
  // gibi bir oturum uyarısı bozulur ve ikinci eşleşme denemesinde gözden kaçabilir.
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(raw);
  } catch (_) {
    return new TextDecoder("windows-1254").decode(raw);
  }
}

async function isUyapReceipt(blob, meta) {
  // A tree label is neither a format nor an authenticity signal. Recognize the
  // actual complete passive document independently of account/court/title.
  if (blob.size > 1024 * 1024) return false;
  const matches = (html) => {
    const body = htmlDocumentText(html);
    return (
      /vekalet\s+pulu\s+makbuzu/i.test(body) &&
      /adalet\s+bakanl[ıi][ğg][ıi]/i.test(body) &&
      /makbuz\s*no/i.test(body) &&
      isPassiveDocumentHtml(html)
    );
  };
  return matches(await decodeDocumentHtml(blob));
}

/** Recognize passive KEP content, not a growing list of tree labels. Generic
    pages, incomplete envelopes, login/error pages and active HTML still fail. */
async function isUyapKepDocument(blob, meta) {
  if (blob.size > 1024 * 1024) return false;
  const matches = (html) => {
    if (!isPassiveDocumentHtml(html)) return false;
    const text = htmlDocumentText(html);
    // Bu UYAP şablonunun TAM metni yalnız bu tek satırdır; adres/konu alanı içermez.
    const notificationText = "ptt kephs'den bir elektronik postaniz var";
    if (text.trim() === notificationText) return true;
    const hasAddress = /[\w.+-]+@[\w.-]+\.(?:kep\.tr|tr)\b/.test(text);
    if (!hasAddress) return false;
    const envelope =
      /\bkep\s+(?:paketi|iletisi)\s*:/.test(text) &&
      /\bkonu(?:su|lu)?\b/.test(text) &&
      /\btarih(?:i(?:nde)?)?\b/.test(text);
    const notification =
      /ptt\s+kephs'den\s+bir\s+elektronik\s+postaniz\s+var/.test(text) &&
      /\bptt(?:hs\d+)?\.kep\.tr\b/.test(text);
    return envelope || notification;
  };
  return matches(await decodeDocumentHtml(blob));
}

async function isUyapHtmlAttachment(blob, filename, disposition) {
  // Generic HTML documents need actual download-disposition evidence, not
  // "html" in their label. A generic portal page is never enough.
  if (
    blob.size > 1024 * 1024 ||
    !/^\s*attachment\b/i.test(disposition) ||
    !/\.html?$/i.test(filename) ||
    /^(?:hata|error|login|giri[şs])(?:\W|_)/i.test(filename)
  )
    return false;
  const html = await decodeDocumentHtml(blob);
  if (!isPassiveDocumentHtml(html) || uyapHtmlFailureCode(html) !== "UYAP_PORTAL_ERROR")
    return false;
  const text = htmlDocumentText(html).trim();
  const title = htmlDocumentText(
    (/<title[^>]*>([\s\S]*?)<\/title>/i.exec(html) || [])[1] || "",
  ).trim();
  return (
    text.length >= 10 &&
    !/^(?:hata(?:\s+(?:oluştu|mesaji))?|error|doğrulama\s+hatasi)\b/.test(text) &&
    !/^(?:hata|error|giriş|login)(?:\b|\s)/.test(title)
  );
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
  const invalid =
    response.status !== 206 ||
    !numbers?.every(Number.isSafeInteger) ||
    numbers[0] !== start ||
    numbers[1] !== numbers[2] - 1 ||
    numbers[2] <= start ||
    (expectedTotal !== null && numbers[2] !== expectedTotal) ||
    strongDocumentEtag(response) !== etag ||
    mime(response) !== mime(original) ||
    !/^(?:identity)?$/i.test(response.headers.get("content-encoding") || "") ||
    (response.url && original.url && response.url !== original.url) ||
    (responseByteLength(response) !== null &&
      responseByteLength(response) !== numbers?.[2] - start);
  if (invalid)
    throw Object.assign(
      new Error("UYAP kaldığı yerden indirmeyi doğrulamadı; parçalar birleştirilmedi."),
      { retryable: true },
    );
  return numbers[2];
}

function throwIfPullCancelled(signal) {
  if (signal?.aborted)
    throw Object.assign(new Error("Aktarım kullanıcı tarafından durduruldu."), {
      code: "UYAP_CANCELLED",
    });
}

/** Tıklamasız yolda aynı anda en çok kaç evrak indirilir (ayar 1-3 arasında sınırlanır). */
const PULL_MAX_PARALLEL = 3;

/** İçerik betiğinin okuduğu UYAP kişisi: yalnız beklenen biçimdeki parmak izi + ad soyad geçer (rakam yok: kimlik numarası değil). */
function cleanIdentity(value) {
  if (!value || typeof value !== "object") return null;
  const fingerprint = String(value.fingerprint || "");
  const display = String(value.display || "");
  if (!/^[0-9a-f]{64}$/.test(fingerprint) || !["tc", "name"].includes(value.kind)) return null;
  if (
    !/^[A-Za-zÇĞİÖŞÜÂÎÛçğıöşüâîû][A-Za-zÇĞİÖŞÜÂÎÛçğıöşüâîû .'*\-]{0,118}[A-Za-zÇĞİÖŞÜÂÎÛçğıöşüâîû.*]$/.test(
      display,
    )
  )
    return null;
  return {
    fingerprint,
    kind: value.kind,
    portal: ["vatandas", "avukat"].includes(value.portal) ? value.portal : "diger",
    display,
  };
}

/** Sunucu, kimliği bilinmeyen ya da hesaba bağlı olmayan UYAP kişisinin aktarımını reddeder (bkz. api/uyap_account.py). */
function identityHeaders(identity) {
  const clean = cleanIdentity(identity);
  return clean
    ? {
        "X-UYAP-Identity": clean.fingerprint,
        "X-UYAP-Identity-Kind": clean.kind,
        "X-UYAP-Portal": clean.portal,
        "X-UYAP-Display": encodeURIComponent(clean.display),
      }
    : {};
}
const ACCOUNT_CODES = new Set([
  "uyap_account_mismatch",
  "uyap_account_taken",
  "uyap_identity_required",
]);
/** Kayıt kontrolünde istek başına evrak kimliği (sunucu sınırı `MAX_KNOWN_IDS`). */
const KNOWN_BATCH = 5000;

async function pullWait(ms, signal) {
  if (!signal) return sleep(ms);
  throwIfPullCancelled(signal);
  await new Promise((resolve) => {
    const finish = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    };
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
  const progress = (expectedBytes, resumes) =>
    onProgress?.({
      receivedBytes: bytes,
      expectedBytes,
      lastDataAt,
      resumes,
    });
  // Yalnız etkin indirme boyunca: Chrome boşta kalan MV3 çalışanını 30 sn'de kapatabilir.
  // İçerik/kimlik göndermez, izin eklemez; iş bitince interval mutlaka temizlenir.
  const keepAlive =
    typeof chrome !== "undefined" && chrome.runtime?.getPlatformInfo
      ? setInterval(() => {
          chrome.runtime.getPlatformInfo().catch(() => {});
        }, 20000)
      : null;
  // Büyük eklerde UYAP bazen uzun ara verir. İlk yanıt ve küçük evrak aynı sınırda;
  // 1 MB geldikten sonra normal 45 sn ayarında yalnız hareketsizlik payı 120 sn olur.
  // Özel kısa test/kullanıcı ayarı büyütülmez; toplam iki saatlik güvenlik ağı değişmez.
  // Eşik 1 MB: gerçek aktarımda büyük ekler 3-7 MB geldikten sonra 45 sn'lik sınıra takılıp baştan başlıyordu (2026-10-11).
  const idleLimit = () =>
    bytes >= LARGE_IDLE_BYTES && timeoutMs >= DEFAULTS.timeoutMs
      ? Math.max(timeoutMs, 120000)
      : timeoutMs;
  // Zaman aşımı veri geldikçe yeniden kurulur; yalnız "timeoutMs boyunca hiç veri gelmedi" ya da toplam üst süre kesintisidir.
  let timer;
  const arm = () => {
    clearTimeout(timer);
    timer = setTimeout(() => controller.abort(), idleLimit());
  };
  const hardStop = setTimeout(() => {
    expired = true;
    controller?.abort();
  }, MAX_DOWNLOAD_MS);
  const stalled = (bytes) =>
    Object.assign(
      new Error(
        `UYAP ${Math.round(idleLimit() / 1000)} sn boyunca veri göndermedi; indirme durdu (${(bytes / 1048576).toFixed(1)} MB geldi).`,
      ),
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
          credentials: "include",
          cache: "no-store",
          signal: controller.signal,
          headers: { Accept: "application/pdf,application/octet-stream,*/*", ...headers },
        });
      } catch (error) {
        throwIfPullCancelled(signal);
        if (error?.name === "AbortError") throw stalled(bytes);
        throw error;
      }
      throwIfPullCancelled(signal);
      if (response.url) assertUyapUrl(response.url);
      if (!response.ok) {
        const error = new Error(`UYAP yanıtı HTTP ${response.status}`);
        if (response.status === 401) error.code = "UYAP_SESSION_EXPIRED";
        else if (response.status === 403) error.code = "UYAP_ACCESS_DENIED";
        throw error;
      }
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
    const etag = /^(?:identity)?$/i.test(original.headers.get("content-encoding") || "")
      ? strongDocumentEtag(original)
      : "";
    for (let resumes = 0; ; resumes += 1) {
      if (!response.body) throw new Error("UYAP belgesi okunamadı");
      const reader = response.body.getReader();
      let interrupted = null;
      try {
        while (true) {
          throwIfPullCancelled(signal);
          arm();
          let step;
          try {
            step = await reader.read();
          } catch (error) {
            throwIfPullCancelled(signal);
            if (error?.name === "AbortError") throw stalled(bytes);
            throw Object.assign(
              new Error(`UYAP indirmeyi yarıda kesti (${(bytes / 1048576).toFixed(1)} MB geldi).`),
              { retryable: true },
            );
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
          throw Object.assign(new Error("UYAP indirmeyi yarıda kesti; belge boyutu eksik."), {
            retryable: true,
          });
      } catch (error) {
        interrupted = error;
      } finally {
        clearTimeout(timer);
        if (interrupted) {
          controller.abort();
          await reader.cancel().catch(() => {});
        }
        reader.releaseLock();
      }
      if (!interrupted) break;
      throwIfPullCancelled(signal);
      if (
        !interrupted.retryable ||
        !etag ||
        !bytes ||
        expired ||
        resumes >= 2 ||
        (expectedTotal !== null && bytes >= expectedTotal)
      )
        throw interrupted;
      await pullWait(1000, signal); // sınırlı, sıralı devam isteği; portal paralelliği yok
      throwIfPullCancelled(signal);
      if (expired) throw interrupted;
      response = await request({ Range: `bytes=${bytes}-`, "If-Range": etag });
      try {
        expectedTotal = resumedDocumentLength(response, bytes, original, expectedTotal, etag);
      } catch (error) {
        controller.abort();
        await response.body?.cancel().catch(() => {});
        throw error;
      }
      progress(expectedTotal, resumes + 1);
    }
    return {
      original,
      blob: new Blob([folded, ...pending], { type: original.headers.get("content-type") || "" }),
    };
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
  const disposition = res.headers.get("content-disposition") || "";
  const filename = dispositionFileName(disposition);
  // UYAP application/download altında XML, bazen giriş HTML'i döndürüyor.
  // Küçük başlığı oku; büyük belgenin tamamını JS belleğine kopyalama.
  const header = await blob.slice(0, 4096).arrayBuffer();
  const headerBytes = new Uint8Array(header);
  const encoding =
    headerBytes[0] === 0xff && headerBytes[1] === 0xfe
      ? "utf-16le"
      : headerBytes[0] === 0xfe && headerBytes[1] === 0xff
        ? "utf-16be"
        : "utf-8";
  const head = new TextDecoder(encoding)
    .decode(header)
    .replace(/^\uFEFF/, "")
    .replace(/^(?:\s|<!--[\s\S]*?-->)+/, "")
    .trimStart();
  const binaryType = binaryDocumentType(headerBytes);
  if (/^%PDF-/.test(head)) type = "application/pdf";
  else if (/^<\?xml(?:\s|\?>)|^<dava(?:\s|>)/i.test(head)) type = "application/xml";
  else if (
    /^<!doctype\s+html|^<(?:html|head|body|form|input|script|div|table|p|meta)(?:\s|>)/i.test(head)
  )
    type = "text/html";
  else if (
    binaryType &&
    /^(?:application\/(?:download|octet-stream)|binary\/octet-stream)?(?:;|$)/i.test(type)
  )
    type = binaryType;
  else if (
    /^(?:application\/(?:download|octet-stream)|binary\/octet-stream)?(?:;|$)/i.test(type) &&
    /^(?:oturum(?:unuz)?\s+(?:sona|kapan|süresi)|giriş\s+yap|yetkiniz\s+(?:yok|bulunm)|doğrulama\s+hatası)/i.test(
      head,
    )
  )
    type = "text/plain";
  if (
    blob.size <= 8192 &&
    (/application\/json/i.test(type) || /^\{/.test(head)) &&
    !(
      /^\s*attachment\b/i.test(disposition) &&
      filename &&
      !/^(?:hata|error|login)(?:\W|_)/i.test(filename)
    )
  ) {
    let envelope;
    try {
      envelope = JSON.parse(await decodeDocumentHtml(blob));
    } catch (_) {
      /* not a JSON error envelope */
    }
    if (
      envelope &&
      (envelope.ok === false ||
        envelope.success === false ||
        envelope.status === "error" ||
        envelope.error ||
        envelope.errors)
    )
      throw Object.assign(retryable("UYAP belge yerine JSON hata yanıtı döndürdü; arşivlenmedi."), {
        code: "UYAP_PORTAL_ERROR",
        notDocument: true,
      });
  }
  if (/text\/html/i.test(type)) {
    if (isUyapValidationPage(await decodeDocumentHtml(blob.slice(0, 8192)))) {
      throw Object.assign(
        new Error(
          "UYAP indirme isteğini doğrulamadı (Doğrulama hatası). Dosyayı UYAP'ta yeniden açıp evrakı tekrar seçin; aynı adresle yeniden denenmedi. Bu mesaj tek başına oturumun kapandığını göstermez.",
        ),
        { code: "UYAP_VALIDATION_FAILED", notDocument: true, freshRequestRequired: true },
      );
    }
    // UYAP bazı makbuzları PDF yerine gerçek HTML belge olarak sunar. Yalnızca
    // başlığı ve resmî makbuz alanları eşleşirse kabul et; giriş/hata sayfasını asla yükleme.
    if ((await isUyapReceipt(blob, meta)) || (await isUyapKepDocument(blob, meta)))
      return { blob, type: "text/html", filename: "" };
    if (await isUyapHtmlAttachment(blob, filename, disposition))
      return { blob, type: "text/html", filename };
    // Kısaltılmış kullanıcı mesajından teşhis koyma: hata türü özgün yanıtın
    // başlık/metnindeki açık belirtilerden, mesaj ise maskelenmiş özetten gelir.
    const said = await uyapReplyText(blob, type);
    // UYAP "Evrak UYAP sistemine yüklenmemiş" diyorsa evrağın içeriği UYAP'ın kendisinde yok: kalıcıdır, yeniden denenmez,
    // eksik sayılmaz; raporda ayrıca yazılır (canlıda görüldü, 2026-10-17: her dosyada ~5,5 dk boşa yeniden deneme).
    if (/sistemine\s+yüklenmemiş|evrak\s+yüklenmemiş/i.test(said))
      throw Object.assign(new Error(`UYAP bu evrakın içeriğini vermiyor: "${said}"`), {
        code: "UYAP_DOCUMENT_ABSENT",
        notDocument: true,
      });
    const head = await decodeDocumentHtml(blob.slice(0, 8192));
    const code = uyapHtmlFailureCode(head);
    const message = `UYAP belge yerine sayfa döndürdü${said ? `: "${said}"` : ""}`;
    // errorPage: UYAP'ın kendi "Hata Oluştu" şablonu (ör. "AVUKATWeb bağlantı hatası"). Önizleme sayfası ya da ayrı indirme
    // yönlendirmesi gibi meşru belge-dışı yanıtlar bu değildir; onlar için Kaydet/alternatif adres yolu sürer.
    throw Object.assign(code === "UYAP_PORTAL_ERROR" ? retryable(message) : new Error(message), {
      code,
      notDocument: true,
      errorPage: code === "UYAP_PORTAL_ERROR" && /hata\s+olu[şs]tu/.test(htmlDocumentText(head)),
    });
  }
  // Short text is not inherently an error. A complete content-validated KEP
  // envelope or a named text attachment can be a perfectly real small file.
  if (/^text\//i.test(type) && blob.size < 1024) {
    if ((await isUyapReceipt(blob, meta)) || (await isUyapKepDocument(blob, meta)))
      return { blob, type: "text/html", filename: "" };
    const said = await uyapReplyText(blob, type);
    // UYAP "Evrak UYAP sistemine yüklenmemiş" diyorsa evrağın içeriği UYAP'ın kendisinde yok: kalıcıdır, yeniden denenmez,
    // eksik sayılmaz; raporda ayrıca yazılır (canlıda görüldü, 2026-10-17: her dosyada ~5,5 dk boşa yeniden deneme).
    if (/sistemine\s+yüklenmemiş|evrak\s+yüklenmemiş/i.test(said))
      throw Object.assign(new Error(`UYAP bu evrakın içeriğini vermiyor: "${said}"`), {
        code: "UYAP_DOCUMENT_ABSENT",
        notDocument: true,
      });
    if (/boyutu\s+.{0,20}\s*büyük|evrakı\s+sisteminize\s+kaydederek/i.test(said)) {
      // Yeniden denemek işe yaramaz (kalıcı): çağıran belgeyi UYAP'ın "Kaydet" adresinden ister (handlePullFetch).
      throw Object.assign(
        new Error(
          "UYAP bu evrakı önizlemede vermiyor: evrakı UYAP'taki Kaydet seçeneğiyle indirip JurisAI Dosyalar sayfasından yükleyin.",
        ),
        { previewRefused: true, notDocument: true },
      );
    }
    const code = uyapHtmlFailureCode(await decodeDocumentHtml(blob));
    const textAttachment =
      /^\s*attachment\b/i.test(disposition) &&
      /\.(?:txt|csv|eml|rtf)$/i.test(filename) &&
      code === "UYAP_PORTAL_ERROR" &&
      !/^(?:hata|error|login|giri[şs])(?:\W|_)/i.test(filename) &&
      !/^\s*(?:hata(?:\s+(?:oluştu|mesaji))?|error|doğrulama\s+hatasi|sistem\s+.{0,20}yoğun)\b/i.test(
        htmlDocumentText(await decodeDocumentHtml(blob)),
      );
    if (textAttachment) return { blob, type, filename };
    const message = `UYAP belge yerine şu mesajı döndürdü: "${said}"`;
    throw Object.assign(code === "UYAP_PORTAL_ERROR" ? retryable(message) : new Error(message), {
      code,
      notDocument: true,
    });
  }
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
async function knownEvraks(ids, esas, birim, signal = null, identity = null) {
  // Sunucu istek başına en çok 5 000 kimlik alır; büyük dosyada (canlıda 20 000+ evraklı dosyalar, 2026-10-17) hepsi sorulur.
  if (ids.length > KNOWN_BATCH) {
    const known = [];
    for (let start = 0; start < ids.length; start += KNOWN_BATCH) {
      const part = await knownEvraks(
        ids.slice(start, start + KNOWN_BATCH),
        esas,
        birim,
        signal,
        identity,
      );
      if (!part.ok) return part;
      known.push(...part.known);
    }
    return { ok: true, known };
  }
  try {
    const settings = await getSettings();
    const url = String(settings.apiUrl || "").replace(/\/upload\/?$/, "/known");
    if (!/\/known$/.test(url) || (settings.apiKey || "").trim().length < 20)
      return { ok: false, known: [] };
    const controller = new AbortController();
    const cancel = () => controller.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      throwIfPullCancelled(signal);
      const res = await fetch(url, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${settings.apiKey}`,
          "Content-Type": "application/json",
          ...identityHeaders(identity),
        },
        body: JSON.stringify({
          evrakIds: ids.slice(0, 5000),
          dosyaEsasNo: esas || null,
          birim: birim || null,
        }),
        signal: controller.signal,
      });
      const out = await res.json().catch(() => ({}));
      if (ACCOUNT_CODES.has(out.code))
        return { ok: false, known: [], code: "uyap_account_mismatch", error: out.error || "" };
      return res.ok && Array.isArray(out.known)
        ? { ok: true, known: out.known }
        : { ok: false, known: [] };
    } finally {
      signal?.removeEventListener("abort", cancel);
      clearTimeout(timer);
    }
  } catch (_) {
    return { ok: false, known: [] };
  }
}

/** Belgeyi Juris AI API'sine multipart/form-data ile yükler. */
function uploadFailure(message, status = 0, retryable = false, retryAfterMs = 0) {
  const code =
    status === 401 || status === 403
      ? "pairing_rejected"
      : [400, 409, 413, 415, 422].includes(status)
        ? "JURISAI_DOCUMENT_REJECTED"
        : "destination_unavailable";
  return Object.assign(new Error(message), {
    code,
    uploadFailed: true,
    status,
    retryable,
    retryAfterMs,
  });
}

function uploadTimeoutMs(bytes) {
  return Math.min(
    30 * 60 * 1000,
    90000 + Math.ceil(Math.max(0, Number(bytes) || 0) / (256 * 1024)) * 1000,
  );
}

function uploadRetryAfterMs(value) {
  if (!value) return 0;
  const seconds = Number(value);
  const ms =
    Number.isFinite(seconds) && seconds >= 0 ? seconds * 1000 : Date.parse(value) - Date.now();
  return Number.isFinite(ms) ? Math.max(0, ms) : 0;
}

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

  // Retry only the upload, from this same Blob. Never fetch the document again
  // because the destination failed. A stable ID makes an ambiguous POST retry
  // safe: the API verifies identity AND checksum before returning duplicate.
  const attempts = meta.evrakId ? 3 : 1;
  for (let attempt = 0; attempt < attempts; attempt++) {
    throwIfPullCancelled(signal);
    const controller = new AbortController();
    const cancel = () => controller.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    let expired = false;
    const timeout = uploadTimeoutMs(blob.size);
    const timer = setTimeout(() => {
      expired = true;
      controller.abort();
    }, timeout);
    let failure;
    try {
      const res = await fetch(settings.apiUrl, {
        method: "POST",
        headers: { Authorization: `Bearer ${settings.apiKey}`, ...identityHeaders(meta.identity) },
        body: form,
        signal: controller.signal,
      });
      throwIfPullCancelled(signal);
      if (res.status === 401 || res.status === 403) {
        await res.body?.cancel().catch(() => {});
        throw uploadFailure(
          "JurisAI bağlantı anahtarı geçersiz veya yükleme izni yok; UYAP oturumunu yenilemek bu hatayı çözmez.",
          res.status,
        );
      }
      const out = await res.json().catch((error) => {
        if (controller.signal.aborted) throw error;
        return {};
      });
      throwIfPullCancelled(signal);
      if (ACCOUNT_CODES.has(out.code))
        // Başka bir UYAP kişisinin evrakı bu hesaba yazılmaz: tekrar denenmez, aktarım durur.
        throw Object.assign(
          uploadFailure(out.error || "UYAP hesabı bu JurisAI hesabına bağlı değil.", res.status),
          { code: "uyap_account_mismatch" },
        );
      if (expired) throw new Error("upload deadline elapsed");
      if (!res.ok)
        throw uploadFailure(
          out.error || `JurisAI kayıt hatası (HTTP ${res.status})`,
          res.status,
          out.retryable !== false &&
            (res.status === 408 || res.status === 429 || (res.status >= 500 && res.status !== 507)),
          uploadRetryAfterMs(res.headers?.get("Retry-After")),
        );
      if (out.ok !== true || typeof out.id !== "string" || !out.id.trim())
        throw uploadFailure("JurisAI sunucusu belge kaydını doğrulamadı; başarı sayılmadı.");
      return out;
    } catch (error) {
      throwIfPullCancelled(signal);
      failure = error.uploadFailed
        ? error
        : uploadFailure(
            expired
              ? `JurisAI yükleme zaman aşımı (${Math.ceil(timeout / 1000)} sn); UYAP'tan inen belge yeniden indirilmedi.`
              : "JurisAI sunucusuna ulaşılamadı; sunucunun çalıştığını kontrol edin.",
            0,
            true,
          );
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", cancel);
    }
    if (!failure.retryable || attempt + 1 >= attempts || failure.retryAfterMs > 120000)
      throw failure;
    await pullWait(Math.max(1000 * 2 ** attempt, failure.retryAfterMs), signal);
  }
}

async function handleUpload(meta, identity = null) {
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
    const saved = await saveLocally(
      blob,
      fileNameFor(meta, type),
      type,
      settings.saveLocal === true,
    );
    const out = await uploadDocument(settings, { ...meta, identity }, blob, type);
    return { ok: true, duplicate: !!out.duplicate, id: out.id || null, saved };
  } catch (error) {
    return { ok: false, error: error.message || "bilinmeyen hata" };
  }
}

/** Dosya detayındaki meta veriyi + evrakları tek seferde Juris AI'ya aktarır. */
async function handleAutoIngest(payload, identity = null) {
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
      identity,
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
        await saveLocally(
          blob,
          fileNameFor({ ...meta, url }, type),
          type,
          settings.saveLocal === true,
        );
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
  const left = String(a)
    .split(".")
    .map((part) => parseInt(part, 10) || 0);
  const right = String(b)
    .split(".")
    .map((part) => parseInt(part, 10) || 0);
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
    // "Tüm dosyaları aktar" dosyalar arasında kısa süre boşta görünür (`pullRun` dosya başınadır). O aralıkta kendini
    // yeniden yükleyen eklenti süren toplu aktarımı keserdi; son UYAP komutundan sonra 10 dakika güncelleme beklenir.
    const busy =
      !!pullRun ||
      !!pull ||
      Date.now() - lastUyapWorkAt < UPDATE_QUIET_MS ||
      !!(await recordingState());
    const decision = decideUpdate({ remote, current, tried: updateTried, busy });
    await chrome.storage.local.set({
      updateState: {
        stale: decision === "stale",
        remote: decision === "none" ? "" : remote,
        current,
      },
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
    chrome.windows
      .create({ url, type: "popup", width: 460, height: 340 })
      .then((approvalWindow) => {
        approvalWindowId = approvalWindow?.id || null;
      })
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
  if (!tab || !UYAP_HOST.test(tab.url || ""))
    return {
      ok: false,
      code: "no_uyap_tab",
      error: "UYAP sekmesi kapanmış: UYAP'ı aç ve dosyaları yeniden listele.",
    };
  const out = await chrome.tabs.sendMessage(tabId, message, { frameId: 0 }).catch(() => null);
  return out
    ? { ...out, tabId }
    : {
        ok: false,
        code: "no_content",
        error: "UYAP sekmesine ulaşılamadı: UYAP sayfasını yenile (F5).",
      };
}

/** UYAP sekmelerinden (en son kullanılan önce) ilkinin içerik betiğine komut gönderir; ilk başarılı yanıtı döndürür. */
async function askUyapTab(message, { focus = false } = {}) {
  const tabs = (await chrome.tabs.query({ url: UYAP_URLS })).sort(
    (a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0),
  );
  if (!tabs.length)
    return {
      ok: false,
      code: "no_uyap_tab",
      error: "Açık bir UYAP sekmesi yok: UYAP'ı aç ve giriş yap.",
    };
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
  return (
    last || {
      ok: false,
      code: "no_content",
      error: "UYAP sekmesine ulaşılamadı: UYAP sayfasını yenile (F5).",
    }
  );
}

// Recovery never accepts a URL or switches accounts/tabs. Only the tab holding the
// exact, recently failed read-only job may approve a reload. No running pull is interrupted.
const recoveringTabs = new Set();
async function recoverReadTab(tabId, jobId) {
  if (!Number.isInteger(tabId) || !jobId)
    return { ok: false, code: "bad_tab", error: "Geçersiz toparlanma isteği." };
  if (recoveringTabs.has(tabId))
    return { ok: false, code: "busy", error: "UYAP sayfası zaten toparlanıyor." };
  recoveringTabs.add(tabId);
  try {
    const before = await chrome.tabs.get(tabId).catch(() => null);
    if (!before || !UYAP_HOST.test(before.url || ""))
      return { ok: false, code: "no_uyap_tab", error: "UYAP sekmesi kapanmış." };
    const stampKey = `jurisai.readRecovery.${tabId}`;
    const stamps = await chrome.storage.session.get(stampKey);
    if (Date.now() - (Number(stamps[stampKey]) || 0) < 60000)
      return {
        ok: false,
        code: "recovery_limited",
        error: "UYAP sık yenilenmedi; sayfayı kontrol edip yeniden dene.",
      };
    const ready = await askTab(tabId, { type: "JURISAI_PREPARE_RECOVERY", jobId });
    if (!ready.ok) return ready;
    const current = await chrome.tabs.get(tabId).catch(() => null);
    if (current?.url !== before.url)
      return { ok: false, code: "stale", error: "UYAP sayfası değişti; otomatik yenilenmedi." };
    await chrome.storage.session.set({ [stampKey]: Date.now() });
    await chrome.tabs.reload(tabId);
    const deadline = Date.now() + 40000;
    while (Date.now() < deadline) {
      await sleep(1000);
      const reply = await askTab(tabId, { type: "JURISAI_RECOVERY_READY" });
      if (reply.ok || !["no_content", "navigating"].includes(reply.code)) return reply;
    }
    return {
      ok: false,
      code: "recovery_failed",
      error: "UYAP yenilendi ama dosya listesi hazır olmadı; sayfayı kontrol et.",
    };
  } finally {
    recoveringTabs.delete(tabId);
  }
}

async function handleBridge(type, payload) {
  if (type !== "BRIDGE_PING") lastUyapWorkAt = Date.now();
  switch (type) {
    // Sayfa tanınmadığında (liste/ağaç okunamadı) UYAP sekmesinin YAPI özeti: içerik, ad, numara taşımaz (content.js
    // `diagnose`). JurisAI sayfası bunu sahibin hesabına kaydeder; canlıda görülmemiş portallar ilk kullanımda düzeltilir.
    case "BRIDGE_DIAGNOSE": {
      const tabs = (await chrome.tabs.query({ url: UYAP_URLS })).sort(
        (a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0),
      );
      if (!tabs.length)
        return { ok: false, code: "no_uyap_tab", error: "Açık bir UYAP sekmesi yok." };
      const frames = await chrome.scripting
        .executeScript({
          target: { tabId: tabs[0].id, allFrames: true },
          func: () =>
            typeof window.__jurisaiDiagnose === "function" ? window.__jurisaiDiagnose() : null,
        })
        .catch(() => []);
      return {
        ok: true,
        reports: frames
          .map((frame) => frame.result)
          .filter(Boolean)
          .slice(0, 8),
      };
    }
    case "BRIDGE_PING": {
      const settings = await getSettings();
      return {
        ok: true,
        version: chrome.runtime.getManifest().version,
        connected: (settings.apiKey || "").trim().length >= 20,
      };
    }
    case "BRIDGE_SET_KEY": {
      const key = String(payload?.key || "").trim();
      if (!/^jsai_[A-Za-z0-9]{20,200}$/.test(key))
        return { ok: false, error: "Anahtar biçimi geçersiz" };
      // Sayfanın postMessage köprüsüne aynı origin'deki başka JS de ulaşabilir. Eklenti
      // penceresinde açık onay olmadan anahtar değişmez; anahtar senkronize depoya yazılmaz.
      if (!(await confirmPairing()))
        return { ok: false, code: "pairing_rejected", error: "Eklenti bağlantısı onaylanmadı" };
      await chrome.storage.local.set({ apiKey: key });
      await chrome.storage.sync.remove("apiKey");
      return { ok: true };
    }
    case "BRIDGE_TREE":
    case "BRIDGE_DETAIL": {
      const message = {
        type: type === "BRIDGE_TREE" ? "JURISAI_TREE" : "JURISAI_DETAIL",
        key: textArg(payload?.key, 600),
        yargiTuru: textArg(payload?.yargiTuru, 80),
      };
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
      if (
        out.ok &&
        out.run &&
        out.job?.state === "running" &&
        out.job.kind === "pull" &&
        pullRun?.tabId === payload?.tabId &&
        pullRun?.jobId === payload?.jobId &&
        pullRun?.transfer
      ) {
        out.run.phase = transferPhase(pullRun.transfer);
      }
      return out;
    }
    case "BRIDGE_PULL_IDS": {
      if (Array.isArray(payload?.ids) && payload.ids.length > 5000)
        return {
          ok: false,
          code: "too_many",
          error: "Bir aktarımda en fazla 5.000 evrak seç; kalanları sonraki aktarımda seç.",
        };
      const ids = Array.isArray(payload?.ids)
        ? payload.ids
            .map((id) => textArg(id, 600))
            .filter(Boolean)
            .slice(0, 5000)
        : [];
      if (!ids.length) return { ok: false, code: "empty", error: "Seçili evrak yok." };
      return askTab(payload?.tabId, {
        type: "JURISAI_PULL_IDS",
        ids,
        mode: payload?.mode === "disk" ? "disk" : "upload",
      });
    }
    case "BRIDGE_CURRENT_JOB":
      return askUyapTab({ type: "JURISAI_CURRENT_JOB" });
    case "BRIDGE_STOP_JOB": {
      const jobId = textArg(payload?.jobId, 64);
      const out = await askTab(payload?.tabId, { type: "JURISAI_BRIDGE_STOP", jobId });
      if (out.ok) abortPullRun(payload?.tabId, jobId);
      return out;
    }
    case "BRIDGE_LIST_DOSYALAR":
      return askUyapTab({ type: "JURISAI_LIST_DOSYALAR" });
    case "BRIDGE_OPEN_DOSYA":
      return askUyapTab(
        {
          type: "JURISAI_OPEN_DOSYA",
          key: textArg(payload?.key, 600),
          yargiTuru: textArg(payload?.yargiTuru, 80),
        },
        { focus: true },
      );
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
    for (const tab of await chrome.tabs.query({
      url: WEB_ORIGINS.map((origin) => `${origin}/*`),
    })) {
      await chrome.scripting
        .executeScript({ target: { tabId: tab.id }, files: ["bridge.js"] })
        .catch(() => {});
    }
  } catch (_) {
    /* yoksay */
  }
  try {
    const tabs = await chrome.tabs.query({ url: ["*://*.uyap.gov.tr/*", "*://*.adalet.gov.tr/*"] });
    for (const tab of tabs) {
      try {
        await chrome.scripting.executeScript({
          target: { tabId: tab.id, allFrames: true },
          files: ["content.js"],
        });
        await chrome.scripting.insertCSS({
          target: { tabId: tab.id, allFrames: true },
          files: ["content.css"],
        });
      } catch (_) {
        /* bu sekmeye yerleştirilemedi (ör. yüklenmemiş): F5 ile gelir */
      }
    }
  } catch (_) {
    /* yoksay */
  }
}
/* Kullanıcıya özel indirilen pakette jurisai-config.json bulunur (api/uyap_extension_package.py): bağlantı anahtarı bir kez
   saklanır, kullanıcı anahtarla uğraşmaz. Aynı anahtar yeniden uygulanmaz; sayfadan sonradan yazılan yeni anahtar ezilmez. */
async function applyBundledKey() {
  try {
    const response = await fetch(chrome.runtime.getURL("jurisai-config.json"));
    if (!response.ok) return;
    const apiKey = String((await response.json())?.apiKey || "");
    if (!/^jsai_[A-Za-z0-9]{20,200}$/.test(apiKey)) return;
    const { bundledKeyApplied } = await chrome.storage.local.get("bundledKeyApplied");
    if (bundledKeyApplied === apiKey) return;
    await chrome.storage.local.set({ apiKey, bundledKeyApplied: apiKey });
    await chrome.storage.sync.remove("apiKey");
  } catch (_) {
    /* genel pakette dosya yoktur */
  }
}
applyBundledKey();
chrome.runtime.onInstalled.addListener(() => {
  applyBundledKey();
  if (!BUILD.store) chrome.alarms.create(UPDATE_ALARM, { periodInMinutes: 0.5 });
  reinjectIntoOpenTabs();
  checkForUpdate();
});
chrome.runtime.onStartup.addListener(() => {
  applyBundledKey();
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
const pathShape = (value) =>
  String(value || "")
    .split("/")
    .map((part) => (part ? ":segment" : ""))
    .join("/")
    .slice(0, 80);
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
      if (state.events.length < 500)
        state.events.push({ t: Date.now() - state.startedAt, ...event });
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
const NET_FILTER = {
  urls: ["*://*.uyap.gov.tr/*", "*://*.adalet.gov.tr/*", "*://*.e-devlet.gov.tr/*"],
};
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
      bodyRawBytes: body?.raw
        ? body.raw.reduce((sum, part) => sum + (part.bytes?.byteLength || 0), 0)
        : 0,
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
  await recordBackgroundEvent(state, {
    kind: "new_tab",
    url: shapeOf(tab.pendingUrl || tab.url || ""),
  });
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
  for (let i = 0; i < buffer.length; i += 0x8000)
    binary += String.fromCharCode(...buffer.subarray(i, i + 0x8000));
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
let lastUyapWorkAt = 0; // son köprü/çekim komutunun zamanı (yalnız bellekte)
const UPDATE_QUIET_MS = 10 * 60 * 1000;

// Başka sekme/iş eski bir END veya STOP ile etkin aktarımı iptal edemez.
function ownsPullRun(sender, jobId = pullRun?.jobId) {
  return (
    !!pullRun &&
    pullRun.tabId === sender.tab?.id &&
    pullRun.frameId === (sender.frameId || 0) &&
    pullRun.jobId === jobId
  );
}
function abortPullRun(tabId, jobId) {
  if (!pullRun || pullRun.tabId !== tabId || pullRun.jobId !== jobId) return false;
  pullRun.controller.abort();
  return true;
}

chrome.tabs.onRemoved.addListener((tabId) => {
  if (pullRun?.tabId === tabId) {
    pullRun.controller.abort();
    pullRun = null;
  }
  if (pull?.tabId === tabId) pull = null;
});
chrome.tabs.onUpdated.addListener((tabId, change) => {
  // Yenileme/gezinme içerik betiğini yok eder: sahipsiz indirme devam etmez.
  if (change.status === "loading" && pullRun?.tabId === tabId) {
    pullRun.controller.abort();
    pullRun = null;
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
        (details.responseHeaders || []).find((item) => item.name.toLowerCase() === name)?.value ||
        "";
      const type = header("content-type").toLowerCase();
      if (
        /attachment/i.test(header("content-disposition")) ||
        /^(image\/tiff|application\/octet-stream)/.test(type)
      ) {
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
        const category = /view_document/i.test(name)
          ? "belge önizleme"
          : /viewer\.jsp/i.test(name)
            ? "görüntüleyici"
            : /indir|download/i.test(name)
              ? "indirme"
              : "diğer UYAP isteği";
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
  return (
    !!error?.retryable ||
    error?.name === "AbortError" ||
    /HTTP (429|5\d\d)|zaman aşımı|abort/i.test(error?.message || "")
  );
}

function transferPhase(transfer) {
  if (transfer.stage === "upload") return "Belge indirildi; JurisAI'ya kaydediliyor";
  if (transfer.stage === "waiting") return "UYAP yanıt başlıkları bekleniyor";
  const mb = (n) => (Math.max(0, Number(n) || 0) / 1048576).toFixed(1);
  const total =
    Number.isSafeInteger(transfer.expectedBytes) && transfer.expectedBytes > 0
      ? ` / ${mb(transfer.expectedBytes)} MB`
      : " MB (toplam boyut bildirilmedi)";
  const idle = transfer.lastDataAt
    ? Math.max(0, Math.floor((Date.now() - transfer.lastDataAt) / 1000))
    : null;
  return (
    `İndiriliyor: ${mb(transfer.receivedBytes)}${total}` +
    (idle !== null && idle >= 5 ? ` · ${idle} sn yeni veri yok` : "") +
    (transfer.resumes > 0 ? ` · sürdürme ${transfer.resumes}/2` : "")
  );
}

/** `quick`: ilk geçiş. Takılan evrak içeride beklenip yeniden denenmez, hareketsizlik sınırı kısadır (30 sn); evrak hemen
    "geçici hata" ile döner ve çağıran onu dosyanın sonundaki yeniden deneme turuna bırakır. Böylece birkaç büyük ek, arkasındaki
    yüzlerce küçük evrakı dakikalarca bekletmez (gerçek aktarımda iki büyük ek 10 dakika boyunca sırayı tuttu; 2026-10-12). */
async function handlePullFetch(
  meta,
  mode = "upload",
  direct = "",
  quick = false,
  directOnly = false,
) {
  const run = pullRun;
  const signal = run?.controller?.signal;
  try {
    const settings = await getSettings();
    throwIfPullCancelled(signal);
    // Eşzamanlı (directOnly) işler tıklamayla yakalanan adresi kullanmaz: o adres o an tıklanan BAŞKA evrağa aittir.
    const captured = directOnly ? "" : pullTargetUrl();
    const viaDirect = !captured && !!acceptedDirectUrl(direct); // tıklamasız yol: başarısızsa beklemeden döner, çağıran tıklama yolunu dener
    const target = captured || acceptedDirectUrl(direct);
    if (!target) throw new Error("UYAP evrak adresi yakalanamadı");
    const timeout = quick
      ? Math.min(30000, Number(settings.timeoutMs) || DEFAULTS.timeoutMs)
      : Number(settings.timeoutMs) || DEFAULTS.timeoutMs;
    const startedAt = Date.now();
    let retried = false;
    let viaSave = false;
    let fetched;
    const fetchCurrent = (url, timeout, meta) => {
      throwIfPullCancelled(signal);
      if (run) run.transfer = { stage: "waiting" };
      return fetchDocument(
        url,
        timeout,
        meta,
        (value) => {
          if (run && pullRun === run) run.transfer = { stage: "download", ...value };
        },
        signal,
      );
    };
    try {
      fetched = await fetchCurrent(target, timeout, meta);
    } catch (error) {
      // Doğrulama reddinde türetilmiş Kaydet URL'si de aynı eski parametreleri
      // taşır. Doğrudan yolun çağıranı bir kez normal tıklama/yakalama yapar;
      // yakalanmış taze istek de reddedilirse ret açıkça kullanıcıya döner.
      if (
        error.freshRequestRequired ||
        [
          "UYAP_CANCELLED",
          "UYAP_SESSION_EXPIRED",
          "UYAP_ACCESS_DENIED",
          "UYAP_DOCUMENT_ABSENT",
        ].includes(error.code)
      )
        throw error;
      // UYAP'ın genel iç hata sayfası ("Hata Oluştu … AVUKATWeb bağlantı hatası") ön izleme reddi değildir: Kaydet adresi de aynı
      // hatayı verir ve 8 sn'lik yerinde yeniden deneme yalnız süre yer (canlıda böyle evraklar bir dosyayı ~13 dk oyaladı,
      // 2026-10-17). Evrak dosyanın sonundaki turda zaten yeniden denenir; oturum kaybı ayrıca yoklanır (içerik betiği).
      if (error.errorPage) throw error;
      const transient = isTransientPullError(error);
      // Ön izleme belge yerine metin/sayfa döndürdüyse gerçek dosya başka adrestedir: (1) UYAP'ın kendi başlattığı ayrı indirme
      // (ör. "Tiff görüntülenemediğinden indiriliyor"), (2) UYAP'ın "Kaydet" adresi (ör. "boyutu çok büyük").
      const saveUrl = error.notDocument ? downloadUrlFor(target) : "";
      if (!directOnly && pull?.altUrl) {
        fetched = await fetchCurrent(pull.altUrl, timeout, meta);
      } else if (saveUrl) {
        try {
          fetched = await fetchCurrent(saveUrl, timeout, meta);
          viaSave = true;
        } catch (saveError) {
          if (
            saveError.freshRequestRequired ||
            ["UYAP_CANCELLED", "UYAP_SESSION_EXPIRED", "UYAP_ACCESS_DENIED"].includes(
              saveError.code,
            )
          )
            throw saveError;
          if (isTransientPullError(saveError) && !viaDirect && !quick) {
            // UYAP "Kaydet" akışını yarıda kesti: bir kez bekleyip aynı adresi yeniden dene.
            retried = true;
            await pullWait(8000, signal);
            fetched = await fetchCurrent(saveUrl, timeout, meta);
            viaSave = true;
          } else if (!transient || viaDirect || quick) {
            // Kaydet'in asıl hata türünü koru: geçici indirme kesintisi,
            // mesajdaki "önizlemede vermiyor" yüzünden kalıcı ret sayılmamalı.
            // Doğrudan yolun çağıranı bu durumda normal tıklamayla taze istek yakalar.
            throw error.previewRefused
              ? Object.assign(
                  new Error(
                    `UYAP bu evrakı önizlemede vermiyor ve "Kaydet" adresinden de alınamadı: ${saveError.message}`,
                  ),
                  {
                    previewRefused: true,
                    retryable: isTransientPullError(saveError),
                    ...(saveError.code ? { code: saveError.code } : {}),
                  },
                )
              : isTransientPullError(saveError)
                ? saveError
                : error;
          } else {
            retried = true;
            await pullWait(8000, signal);
            fetched = await fetchCurrent(target, timeout, meta);
          }
        }
      } else if (transient && !viaDirect && !quick) {
        // Geçici olabilir (yoğunluk, hazırlanıyor): bir kez bekleyip aynı adresi yeniden dene.
        retried = true;
        await pullWait(8000, signal);
        fetched = await fetchCurrent(target, timeout, meta);
      } else {
        throw error;
      }
    }
    const timing = { download: Date.now() - startedAt, upload: 0, retried, viaSave };
    throwIfPullCancelled(signal);
    const { blob, type, filename } = fetched;
    if (filename)
      meta = { ...meta, fileExt: (/\.([A-Za-z0-9]{1,16})$/.exec(filename) || [])[1] || "" };
    // Farklı UYAP evrakları birebir aynı baytlara sahip olabilir (özellikle ekler).
    // İçerik hash'iyle atlamak bunları sessizce kaybettirir; sunucu evrak kimliğiyle tekilleştirir.
    const savingFrom = Date.now();
    if (run && pullRun === run) run.transfer = { stage: "upload" };
    if (mode === "disk") {
      await saveToFolder(blob, type, meta, signal);
      timing.upload = Date.now() - savingFrom;
      return { ok: true, saved: true, ms: timing };
    }
    const out = await uploadDocument(
      settings,
      { ...meta, url: "", identity: run?.identity },
      blob,
      type,
      signal,
    );
    timing.upload = Date.now() - savingFrom;
    return { ok: true, duplicate: !!out.duplicate, ms: timing };
  } catch (error) {
    return {
      ok: false,
      error: error.message || "bilinmeyen hata",
      ...(error.code ? { code: error.code } : {}),
      ...(error.errorPage ? { errorPage: true } : {}),
      ...(error.uploadFailed ? { uploadFailed: true } : {}),
      ...(error.code === "UYAP_CANCELLED" ? { stopped: true } : {}),
      ...(isTransientPullError(error) ? { retryable: true } : {}),
    };
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
    return {
      status: res.status,
      type: (res.headers.get("content-type") || "").split(";")[0],
      size: blob.size,
      hash: await sha(blob),
    };
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
    typeQuery = {
      status: res.status,
      contentType: (res.headers.get("content-type") || "").split(";")[0],
      responseLength: text.length,
    };
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
  if (
    /^JURISAI_PULL_(?:BEGIN|ARM|STATUS|FETCH|FETCH_START|FETCH_POLL|CANCEL|WAIT|END)$/.test(
      message?.type || "",
    ) &&
    (!Number.isInteger(sender.tab?.id) || !UYAP_HOST.test(sender.url || sender.tab?.url || ""))
  ) {
    sendResponse({
      ok: false,
      code: "wrong_source",
      error: "Bu kaynaktan çekim komutu kabul edilmez.",
    });
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
            return sendResponse({
              ok: false,
              error: "Bağlantı anahtarı ayarlanmadı (eklenti penceresine yapıştır)",
            });
        }
        if (pullRun)
          return sendResponse({
            ok: false,
            code: "busy",
            error: "Başka bir evrak aktarımı sürüyor; önce durdurun.",
          });
        pullRun = {
          tabId: sender.tab.id,
          frameId: sender.frameId || 0,
          jobId: textArg(message.jobId, 64),
          controller: new AbortController(),
          identity: cleanIdentity(message.identity),
        };
        sendResponse({
          ok: true,
          gapMs: Math.max(1500, Number(settings.throttleMs) || DEFAULTS.throttleMs),
          retryWaitMs: Math.max(0, Math.min(120000, Number(settings.retryWaitMs ?? 15000) || 0)),
          parallel: Math.max(
            1,
            Math.min(PULL_MAX_PARALLEL, Math.round(Number(settings.pullParallel) || 1)),
          ),
        });
      });
      return true;
    case "JURISAI_PULL_ARM":
      if (pullRun && !ownsPullRun(sender)) {
        sendResponse({ ok: false, code: "wrong_job" });
        return false;
      }
      pull = {
        tabId: sender.tab?.id ?? null,
        url: "",
        viewerUrl: "",
        viewerEvrakId: "",
        loose: "",
        altUrl: "",
        seen: [],
        armedAt: Date.now(),
      };
      sendResponse({ ok: true });
      return false;
    case "JURISAI_PULL_STATUS":
      sendResponse({
        // viewer.jsp hiç gelmezse (başka evrak biçimi) gevşek adres yalnız 3 sn sonra kabul edilir: eski bir önizlemenin
        // gecikmiş isteği hemen "yakalandı" sayılmasın.
        captured: !!(
          pull?.url ||
          pull?.viewerUrl ||
          (pull?.loose && Date.now() - pull.armedAt > 3000)
        ),
        exact: !!pull?.url,
        seen: pull?.seen || [],
      });
      return false;
    case "JURISAI_PULL_FETCH":
      if (!ownsPullRun(sender)) {
        sendResponse({ ok: false, code: "wrong_job" });
        return false;
      }
      handlePullFetch(message.meta || {}, message.mode, message.direct || "").then(sendResponse);
      return true;
    // Uzun indirme tek bir mesajın cevabı olarak BEKLETİLMEZ. Chrome, cevabı 5 dakikayı aşan olayın servis çalışanını
    // kapatır; çalışan yeniden başlayınca `pullRun` (yalnız bellekte) kaybolur ve sıradaki her evrak "wrong_job" alır.
    // Gerçek aktarımda (2026-10-11) takılan tek bir büyük ekten sonra art arda dört evrak böyle düştü ve dosyanın kalan
    // 232 evrakı hiç denenmedi. İş burada başlatılır, sonuç kısa yoklamalarla (FETCH_POLL) alınır; her olay kısadır.
    case "JURISAI_PULL_FETCH_START": {
      if (!ownsPullRun(sender)) {
        sendResponse({ ok: false, code: "wrong_job" });
        return false;
      }
      const run = pullRun;
      // `fetchId` taşıyan tıklamasız iş kendi yuvasında koşar (en çok PULL_MAX_PARALLEL); tıklama yolu tek yuvayı kullanır.
      const fetchId = message.fetchId && message.direct ? textArg(message.fetchId, 96) : "";
      if (fetchId) {
        run.fetches ||= new Map();
        if (run.fetches.has(fetchId) || run.fetches.size >= PULL_MAX_PARALLEL) {
          sendResponse({
            ok: false,
            code: "busy",
            error: "Eşzamanlı indirme sınırı dolu.",
            retryable: true,
          });
          return false;
        }
      } else if (run.fetch && !run.fetch.done) {
        sendResponse({ ok: false, code: "busy", error: "Önceki evrak hâlâ indiriliyor." });
        return false;
      }
      const job = { done: false, result: null, listeners: new Set() };
      if (fetchId) run.fetches.set(fetchId, job);
      else run.fetch = job;
      handlePullFetch(
        message.meta || {},
        message.mode,
        message.direct || "",
        message.quick === true,
        !!fetchId,
      )
        .then(
          (result) => {
            job.result = result;
          },
          (error) => {
            job.result = {
              ok: false,
              error: error?.message || "Evrak aktarılamadı",
              retryable: true,
            };
          },
        )
        .finally(() => {
          job.done = true;
          for (const notify of [...job.listeners]) notify();
        });
      sendResponse({ ok: true, started: true });
      return false;
    }
    case "JURISAI_PULL_FETCH_POLL": {
      if (!ownsPullRun(sender)) {
        sendResponse({ ok: false, code: "wrong_job" });
        return false;
      }
      const run = pullRun;
      const fetchId = message.fetchId ? textArg(message.fetchId, 96) : "";
      const current = () => (fetchId ? run.fetches?.get(fetchId) : run.fetch);
      const clear = () => {
        if (fetchId) run.fetches?.delete(fetchId);
        else run.fetch = null;
      };
      const job = current();
      if (!job) {
        sendResponse({
          ok: false,
          code: "no_fetch",
          error: "Bekleyen evrak indirmesi yok.",
          retryable: true,
        });
        return false;
      }
      // En fazla bir saniyelik olay: küçük belge biter bitmez yanıt verilir;
      // içerik betiğinde her evrak için sabit 700 ms zamanlayıcı beklenmez.
      const waitMs = Math.max(0, Math.min(1000, Number(message.waitMs) || 0));
      if (!job.done && waitMs > 0) {
        let settled = false;
        const finish = () => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          job.listeners.delete(finish);
          run.controller.signal.removeEventListener("abort", finish);
          if (pullRun !== run || !ownsPullRun(sender))
            return sendResponse({ ok: false, code: "wrong_job" });
          if (run.controller.signal.aborted)
            return sendResponse({ ok: false, code: "UYAP_CANCELLED", stopped: true });
          if (current() !== job)
            return sendResponse({ ok: false, code: "no_fetch", retryable: true });
          if (!job.done) return sendResponse({ ok: true, pending: true });
          clear();
          sendResponse(job.result);
        };
        const timer = setTimeout(finish, waitMs);
        job.listeners.add(finish);
        run.controller.signal.addEventListener("abort", finish, { once: true });
        if (run.controller.signal.aborted) finish();
        return true;
      }
      if (!job.done) {
        sendResponse({ ok: true, pending: true });
        return false;
      }
      clear();
      sendResponse(job.result);
      return false;
    }
    case "JURISAI_MENU": {
      // UYAP yan menüsü `menuButtonClick("<sayı>")` işlevini çağırır; işlev sayfanın kendi dünyasındadır, içerik betiği (yalıtılmış dünya)
      // çağıramaz. Yalnız UYAP sekmesinden gelen, yalnız sayısal kimlik kabul edilir.
      const tabId = sender.tab?.id;
      if (
        tabId == null ||
        !UYAP_HOST.test(sender.tab?.url || "") ||
        !/^\d{1,8}$/.test(String(message.id))
      ) {
        sendResponse({ ok: false });
        return false;
      }
      chrome.scripting
        .executeScript({
          target: { tabId, frameIds: [sender.frameId || 0] },
          world: "MAIN",
          func: (id) =>
            typeof window.menuButtonClick === "function"
              ? (window.menuButtonClick(id), true)
              : false,
          args: [String(message.id)],
        })
        .then((results) => sendResponse({ ok: !!results?.[0]?.result }))
        .catch(() => sendResponse({ ok: false }));
      return true;
    }
    case "JURISAI_SLEEP":
      // Gizli sekmedeki içerik betiği zamanlayıcıları kısılabilir: bekleme burada (servis çalışanında) yapılır.
      setTimeout(
        () => sendResponse({ ok: true }),
        Math.max(0, Math.min(60000, Number(message.ms) || 0)),
      );
      return true;
    case "JURISAI_PULL_KNOWN":
      knownEvraks(
        message.ids || [],
        message.esas || "",
        message.birim || "",
        ownsPullRun(sender) ? pullRun.controller.signal : null,
        message.identity,
      ).then(sendResponse);
      return true;
    case "JURISAI_PULL_WAIT":
      if (!ownsPullRun(sender, textArg(message.jobId, 64))) {
        sendResponse({ ok: false, code: "wrong_job" });
        return false;
      }
      pullWait(Math.max(0, Math.min(20000, Number(message.ms) || 0)), pullRun.controller.signal)
        .then(() => sendResponse({ ok: true }))
        .catch((error) => sendResponse({ ok: false, code: error.code }));
      return true;
    case "JURISAI_PULL_SESSION_PROBE":
      if (!ownsPullRun(sender, textArg(message.jobId, 64))) {
        sendResponse({ ok: false, code: "wrong_job" });
        return false;
      }
      probeUyapSession(String(sender.tab?.url || "")).then((state) =>
        sendResponse({ ok: true, state }),
      );
      return true;
    case "JURISAI_PULL_CANCEL":
      if (!ownsPullRun(sender, textArg(message.jobId, 64))) {
        sendResponse({ ok: false, code: "wrong_job" });
        return false;
      }
      abortPullRun(sender.tab.id, pullRun.jobId);
      sendResponse({ ok: true });
      return false;
    case "JURISAI_PULL_END":
      lastUyapWorkAt = Date.now();
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
      .set({
        [RECORD_KEY]: {
          tabId: sender.tab?.id ?? null,
          startedAt: Date.now(),
          events: [],
          openedTabs: [],
        },
      })
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
    handleAutoIngest(message.payload || {}, message.identity).then(sendResponse);
    return true;
  }

  if (message?.type === "JURISAI_UPLOAD") {
    handleUpload(message.payload, message.identity).then(sendResponse);
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

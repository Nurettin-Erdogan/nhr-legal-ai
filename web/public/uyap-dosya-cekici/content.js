/* UYAP Dosya Çekici - content script
   Sayfanın (ve iframe'lerinin) DOM'undan indirilebilir belge adreslerini toplar.
   Kullanıcının kendi UYAP oturumu kullanılır; şifre/imza bilgisi hiçbir zaman okunmaz. */

const DOC_EXT_RE = /\.(pdf|docx?|xlsx?|zip|jpe?g|png|txt|udf|tiff?|rtf|eyp)(\?|#|$)/i;
// UYAP'a özgü belge üreten uç noktaların adlarında geçen ipuçları
const HINT_RE =
  /indir|download|evrak|dokuman|doküman|belge|goster|getDosya|dosyaIndir|udfGoster|icerikGetir|dokumanGetir|tumEvrak|ekgoster/i;
const PAGE_NEXT_RE = /sonraki|next|ileri|»|›/i;
const MAX_LINKS = 5000;

/** Sayfanın kendi ağ trafiğinde geçen belge adresleri (script enjeksiyonu ile). */
const sniffed = new Set();
window.addEventListener("message", (event) => {
  if (event.source !== window) return;
  const data = event.data;
  if (data && data.source === "uyap-dosya-cekici" && typeof data.url === "string") {
    sniffed.add(data.url);
  }
});

/* Sayfanın MAIN dünyasına küçük bir dinleyici enjekte et (fetch / XHR adresleri). */
(function injectSniffer() {
  try {
    const code = `(() => {
      const post = (u) => { try { window.postMessage({ source: "uyap-dosya-cekici", url: new URL(u, location.href).href }, "*"); } catch (e) {} };
      const of = window.fetch;
      window.fetch = function (input, init) { post(typeof input === "string" ? input : input && input.url); return of.apply(this, arguments); };
      const oo = XMLHttpRequest.prototype.open;
      XMLHttpRequest.prototype.open = function (m, u) { post(u); return oo.apply(this, arguments); };
    })();`;
    const el = document.createElement("script");
    el.textContent = code;
    (document.documentElement || document.head).appendChild(el);
    el.remove();
  } catch (_) {
    /* CSP engellerse yalnızca DOM taraması yapılır */
  }
})();

function absolute(raw) {
  if (!raw) return null;
  if (/^(javascript|mailto|tel|data|blob):/i.test(raw)) return null;
  try {
    // HTTPS sayfadan http:// indirme engellenir; adresi yükselt.
    return new URL(raw, location.href).href.replace(/^http:\/\//i, "https://");
  } catch (_) {
    return null;
  }
}

function isDocumentUrl(url) {
  return DOC_EXT_RE.test(url) || HINT_RE.test(url);
}

/** Tüm olası belge adreslerini { url, name } listesi olarak döndürür. */
function collectDocuments() {
  const found = new Map();

  const add = (raw, label) => {
    const url = absolute(raw);
    if (!url || !/^https?:/i.test(url)) return;
    if (!isDocumentUrl(url)) return;
    if (found.size >= MAX_LINKS || found.has(url)) return;
    found.set(url, (label || "").replace(/\s+/g, " ").trim().slice(0, 100));
  };

  // 1) Klasik bağlantılar ve gömülü belgeler
  document
    .querySelectorAll("a[href], iframe[src], embed[src], object[data], area[href]")
    .forEach((el) => {
      add(
        el.getAttribute("href") || el.getAttribute("src") || el.getAttribute("data"),
        el.textContent || el.getAttribute("title") || el.getAttribute("aria-label"),
      );
    });

  // 2) UYAP'ın data-* öznitelikleri
  document
    .querySelectorAll("[data-url],[data-href],[data-link],[data-dosya],[data-evrak],[data-belge]")
    .forEach((el) => {
      add(
        el.dataset.url ||
          el.dataset.href ||
          el.dataset.link ||
          el.dataset.dosya ||
          el.dataset.evrak ||
          el.dataset.belge,
        el.textContent || el.getAttribute("title"),
      );
    });

  // 3) onclick / ng-click içindeki adresler
  document.querySelectorAll("[onclick],[ng-click],button,a[href^='javascript:']").forEach((el) => {
    const src = `${el.getAttribute("onclick") || ""} ${el.getAttribute("ng-click") || ""} ${
      el.getAttribute("href") || ""
    }`;
    const label = el.textContent || "";
    (src.match(/['"]([^'"\s]{6,400})['"]/g) || []).forEach((m) => add(m.slice(1, -1), label));
  });

  // 4) Sayfanın ağ trafiğinden yakalananlar
  sniffed.forEach((url) => add(url, ""));

  return [...found.entries()].map(([url, name]) => ({ url, name }));
}

/** Sayfalama: "Sonraki" düğmesine tıklar, varsa true döner. */
function goToNextPage() {
  const candidates = [...document.querySelectorAll("a,button,li,span,input[type='button']")];
  const next = candidates.find((el) => {
    const text = `${el.textContent || ""} ${el.value || ""} ${el.title || ""} ${
      el.getAttribute("aria-label") || ""
    }`;
    if (!PAGE_NEXT_RE.test(text)) return false;
    if (el.disabled || el.getAttribute("aria-disabled") === "true") return false;
    if ((el.className || "").toString().includes("disabled")) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  });
  if (!next) return false;
  next.click();
  return true;
}

/** Sayfadan oturum sahibinin adını tahmin eder (yalnızca görünen metin). */
function guessUser() {
  const selectors = [
    ".user-name",
    ".kullanici-adi",
    "#kullaniciAdi",
    "[class*='userName']",
    "[class*='kullanici']",
    "header .name",
    ".navbar-text",
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    const text = (el?.textContent || "").replace(/\s+/g, " ").trim();
    if (text && text.length < 60) return text;
  }
  const match = document.body.innerText.match(/\b([A-ZÇĞİÖŞÜ]{2,}\s+[A-ZÇĞİÖŞÜ]{2,})\b/);
  return match ? match[1] : "";
}

/** Oturum durumu: giriş formu yoksa ve portal içeriği görünüyorsa açık kabul edilir. */
function detectSession() {
  const text = document.body?.innerText || "";
  const hasLoginForm =
    !!document.querySelector("input[type='password']") ||
    /e-devlet ile giriş yap|giriş yapınız|kullanıcı adı ve şifre/i.test(text);
  const hasPortal =
    /güvenli çıkış|çıkış yap|portal|uyap işlemlerim|dosya sorgula|menü ara|duyurular/i.test(text) ||
    document.querySelectorAll("a,button,table").length > 10;
  return { active: !hasLoginForm && hasPortal, user: guessUser() };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  try {
    if (message?.type === "UYAP_SESSION") {
      const info = detectSession();
      sendResponse({ ok: true, active: info.active, user: info.user, url: location.href });
      return true;
    }

    if (message?.type === "UYAP_COLLECT") {
      sendResponse({ ok: true, documents: collectDocuments(), url: location.href });
      return true;
    }
    if (message?.type === "UYAP_NEXT_PAGE") {
      sendResponse({ ok: true, moved: goToNextPage() });
      return true;
    }
  } catch (error) {
    sendResponse({ ok: false, error: String(error?.message || error) });
    return true;
  }
  return false;
});

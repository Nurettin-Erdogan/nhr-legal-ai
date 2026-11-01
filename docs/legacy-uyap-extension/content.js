/* JURISAI - UYAP sayfasındaki belgeleri kullanıcının kendi oturumuyla indirip
   JURISAI hesabına aktarır. Giriş bilgileri hiçbir zaman okunmaz veya gönderilmez. */

const DOC_RE = /\.(pdf|udf|docx?|tiff?|jpe?g|png|zip|eyp|xml|txt|rtf|xls[xm]?)(\?|#|$)/i;
const HINT_RE =
  /indir|download|evrak|dokuman|doküman|belge|ekgoster|goster|getDosya|dosyaIndir|udfGoster|tumEvrak|karar|tebligat|dilekce|dilekçe|safahat|ekler|dokumanGetir|icerikGetir/i;
const PAGE_HINT_RE =
  /dosya|evrak|safahat|detay|liste|goster|görüntü|arama|sorgu|karar|tebligat|dava|icra|durusma|duruşma/i;
const MAX_LINKS = 4000;
const MAX_PAGES = 400;
// Base64 dosyaları tek tek gönder; büyük toplu JSON istekleri ağ geçidi sınırına takılabilir.
const BATCH_SIZE = 1;
const MAX_DEPTH = 3;

/** Sayfanın kendi ağ trafiğinden yakalanan adresler (sniffer.js). */
const sniffed = new Set();
const sniffedRequests = new Map();
const capturedFiles = new Map();
window.addEventListener("message", (e) => {
  if (e.source !== window) return;
  const d = e.data;
  if (d?.source === "jurisai-sniffer" && d.url) {
    sniffed.add(d.url);
    return;
  }
  if (d?.source === "jurisai-sniffer-request" && d.url) {
    sniffedRequests.set(d.url, {
      method: d.method || "GET",
      body: d.body || undefined,
      contentType: d.contentType || undefined,
    });
    sniffed.add(d.url);
    return;
  }
  if (d?.source === "jurisai-sniffer-file" && d.contentBase64) {
    const key = `${d.url || "uyap-belge"}:${d.contentBase64.length}`;
    capturedFiles.set(key, d);
    return;
  }
  if (d?.source === "jurisai-sniffer-body" && d.text) {
    // Sunucudan dönen liste/JSON yanıtlarındaki belge adreslerini çıkar.
    const matches =
      d.text.match(/https?:\/\/[^"'\s\\<>]{6,400}|\/[A-Za-z0-9_./?=&%:-]{6,300}/g) || [];
    for (const raw of matches) {
      try {
        const abs = new URL(raw.replace(/\\\//g, "/"), d.base || location.href).href;
        if (/^https?:/i.test(abs) && looksLikeDoc(abs)) sniffed.add(abs);
      } catch (_) {}
      if (sniffed.size > MAX_LINKS * 2) break;
    }
  }
});

function toHttps(u) {
  return String(u || "").replace(/^http:\/\//i, "https://");
}

function looksLikeDoc(abs) {
  return DOC_RE.test(abs) || HINT_RE.test(abs);
}

/** Verilen DOM (veya ayrıştırılmış belge) içinden adresleri toplar. */
function scanDom(root, baseHref, out, pageOut) {
  const add = (raw, label) => {
    if (!raw) return;
    if (/^(javascript|mailto|tel|blob|data):/i.test(raw)) return;
    let abs;
    try {
      abs = new URL(raw, baseHref).href;
    } catch (_) {
      return;
    }
    if (!/^https?:/i.test(abs)) return;
    // HTTPS sayfadan http:// indirme tarayıcı tarafından engellenir; adresi yükselt.
    abs = abs.replace(/^http:\/\//i, "https://");
    const clean = (label || "").trim().slice(0, 120);
    if (looksLikeDoc(abs)) {
      if (out.size < MAX_LINKS && !out.has(abs)) out.set(abs, clean);
    } else if (pageOut && PAGE_HINT_RE.test(abs) && abs.includes("uyap.gov.tr")) {
      pageOut.add(abs.split("#")[0]);
    }
  };

  root
    .querySelectorAll("a[href], iframe[src], embed[src], object[data], area[href]")
    .forEach((el) => {
      add(
        el.getAttribute("href") || el.getAttribute("src") || el.getAttribute("data"),
        el.textContent || el.getAttribute("title") || el.getAttribute("aria-label"),
      );
    });

  root
    .querySelectorAll("[data-url],[data-href],[data-link],[data-dosya],[data-evrak],[data-id]")
    .forEach((el) => {
      const v =
        el.getAttribute("data-url") ||
        el.getAttribute("data-href") ||
        el.getAttribute("data-link") ||
        el.getAttribute("data-dosya") ||
        el.getAttribute("data-evrak");
      add(v, el.textContent || el.getAttribute("title"));
    });

  root.querySelectorAll("[onclick], a[href^='javascript:'], button, [ng-click]").forEach((el) => {
    const src = `${el.getAttribute("onclick") || ""} ${el.getAttribute("href") || ""} ${
      el.getAttribute("ng-click") || ""
    }`;
    const label = (el.textContent || "").trim();
    (src.match(/['"]([^'"\s]{6,400})['"]/g) || []).forEach((m) => {
      const val = m.slice(1, -1);
      if (val.includes("/") || DOC_RE.test(val)) add(val, label);
    });
  });

  // Satır içi script/JSON içeriğindeki adresler
  root.querySelectorAll("script:not([src])").forEach((el) => {
    const text = el.textContent || "";
    if (text.length > 300000) return;
    (text.match(/["'](\/[^"'\s]{6,300})["']/g) || []).forEach((m) => {
      const val = m.slice(1, -1);
      if (looksLikeDoc(val)) add(val, "");
    });
  });
}

/** Bu çerçevedeki tüm olası belge bağlantılarını toplar. */
function collectDocumentLinks() {
  const urls = new Map();
  scanDom(document, location.href, urls, null);
  sniffed.forEach((u) => {
    if (looksLikeDoc(u) && !urls.has(u) && urls.size < MAX_LINKS) urls.set(u, "");
  });
  return [...urls.entries()].slice(0, MAX_LINKS);
}

/** Aynı origin içinde HTML sayfalarını gezerek (derin tarama) belge adresleri bulur. */
async function deepCrawl(seedLinks, onProgress) {
  const docs = new Map(seedLinks);
  const pages = new Set();
  const visited = new Set([location.href.split("#")[0]]);

  scanDom(document, location.href, docs, pages);
  sniffed.forEach((u) => {
    if (looksLikeDoc(u)) docs.set(u, docs.get(u) || "");
    else if (PAGE_HINT_RE.test(u) && u.includes("uyap.gov.tr")) pages.add(u.split("#")[0]);
  });

  let queue = [...pages].map((u) => ({ url: u, depth: 1 }));
  let scanned = 0;

  while (queue.length && scanned < MAX_PAGES && docs.size < MAX_LINKS) {
    const chunk = queue.splice(0, 6);
    await Promise.all(
      chunk.map(async ({ url, depth }) => {
        if (visited.has(url) || scanned >= MAX_PAGES) return;
        visited.add(url);
        scanned++;
        onProgress?.(scanned, docs.size);
        try {
          const res = await fetch(toHttps(url), { credentials: "include" });
          const ct = res.headers.get("content-type") || "";
          if (!res.ok) return;
          if (/json/i.test(ct)) {
            const text = (await res.text()).slice(0, 500000);
            (text.match(/https?:\/\/[^"'\s\\]{6,400}|\/[A-Za-z0-9_./?=&%-]{6,300}/g) || []).forEach(
              (raw) => {
                try {
                  const abs = new URL(raw, url).href;
                  if (looksLikeDoc(abs) && !docs.has(abs) && docs.size < MAX_LINKS)
                    docs.set(abs, "");
                } catch (_) {}
              },
            );
            return;
          }
          if (!/text\/html/i.test(ct)) {
            if (!docs.has(url) && docs.size < MAX_LINKS) docs.set(url, "");
            return;
          }
          const html = await res.text();
          const doc = new DOMParser().parseFromString(html, "text/html");
          const nextPages = new Set();
          scanDom(doc, url, docs, nextPages);
          if (depth < MAX_DEPTH) {
            nextPages.forEach((p) => {
              if (!visited.has(p)) queue.push({ url: p, depth: depth + 1 });
            });
          }
        } catch (_) {
          /* atla */
        }
      }),
    );
  }
  return [...docs.entries()].slice(0, MAX_LINKS);
}

// Her çerçeve, arka plan servisinden gelen toplama isteğine yanıt verir.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "jurisai-collect-frame") {
    sendResponse({
      links: collectDocumentLinks(),
      files: [...capturedFiles.entries()],
      requests: [...sniffedRequests.entries()],
    });
    return true;
  }
  return false;
});

function collectFromAllFrames() {
  return new Promise((resolve) => {
    let done = false;
    const fallback = setTimeout(() => {
      if (!done) {
        done = true;
        resolve({
          links: collectDocumentLinks(),
          files: [...capturedFiles.entries()],
          requests: [...sniffedRequests.entries()],
        });
      }
    }, 8000);
    try {
      chrome.runtime.sendMessage({ type: "jurisai-collect-all" }, (res) => {
        void chrome.runtime.lastError;
        if (done) return;
        done = true;
        clearTimeout(fallback);
        resolve({
          links: res?.links?.length ? res.links : collectDocumentLinks(),
          files: res?.files || [...capturedFiles.entries()],
          requests: res?.requests || [...sniffedRequests.entries()],
        });
      });
    } catch (_) {
      if (!done) {
        done = true;
        clearTimeout(fallback);
        resolve({
          links: collectDocumentLinks(),
          files: [...capturedFiles.entries()],
          requests: [...sniffedRequests.entries()],
        });
      }
    }
  });
}

function shortHash(value) {
  let hash = 2166136261;
  const text = String(value || "uyap");
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36).slice(0, 8);
}

function fileNameFrom(url, label, contentType, disposition, identity = url) {
  const fromHeader = /filename\*?=(?:UTF-8''|")?([^\";]+)/i.exec(disposition || "");
  if (fromHeader?.[1]) {
    const decoded = decodeURIComponent(fromHeader[1].replace(/"$/, ""));
    const dot = decoded.lastIndexOf(".");
    return dot > 0
      ? `${decoded.slice(0, dot)}-${shortHash(identity)}${decoded.slice(dot)}`
      : `${decoded}-${shortHash(identity)}`;
  }
  const path = new URL(url).pathname.split("/").pop() || "";
  if (DOC_RE.test(path)) {
    const decoded = decodeURIComponent(path);
    const dot = decoded.lastIndexOf(".");
    return `${decoded.slice(0, dot)}-${shortHash(identity)}${decoded.slice(dot)}`;
  }
  const ext = /pdf/i.test(contentType || "")
    ? "pdf"
    : /zip/i.test(contentType || "")
      ? "zip"
      : /image/i.test(contentType || "")
        ? "jpg"
        : /msword|officedocument/i.test(contentType || "")
          ? "docx"
          : "pdf";
  const base =
    (label || "uyap-belge").replace(/[^\w\sğüşıöçĞÜŞİÖÇ.-]+/g, " ").trim() || "uyap-belge";
  return `${base}-${shortHash(identity)}.${ext}`;
}

async function toBase64(blob) {
  const buf = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let i = 0; i < buf.length; i += 8192) {
    binary += String.fromCharCode.apply(null, buf.subarray(i, i + 8192));
  }
  return btoa(binary);
}

async function sendBatch(apiUrl, token, files) {
  const res = await fetch(`${apiUrl}/api/public/uyap-ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, files }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.status);
  return { inserted: data.inserted || 0, skipped: data.skipped || 0 };
}

async function run(statusEl, button, deep) {
  const { jurisaiToken, jurisaiApiUrl } = await chrome.storage.sync.get([
    "jurisaiToken",
    "jurisaiApiUrl",
  ]);
  if (!jurisaiToken) {
    statusEl.textContent = "Eklenti simgesine tıklayıp JURISAI bağlantı anahtarını kaydet.";
    return;
  }
  const apiUrl = jurisaiApiUrl || "http://localhost:8766";

  document.querySelectorAll("#jurisai-panel button").forEach((b) => (b.disabled = true));
  statusEl.textContent = "Belgeler taranıyor...";
  const collected = await collectFromAllFrames();
  let links = collected.links;
  (collected.files || []).forEach(([key, file]) => capturedFiles.set(key, file));
  (collected.requests || []).forEach(([url, request]) => sniffedRequests.set(url, request));
  if (deep) {
    const rowButtons = [...document.querySelectorAll("button, a, input[type='button']")].filter(
      (el) => {
        if (el.closest("#jurisai-panel")) return false;
        const text = `${el.textContent || ""} ${el.value || ""} ${el.title || ""}`.trim();
        const rect = el.getBoundingClientRect();
        return (
          rect.width > 0 &&
          rect.height > 0 &&
          /dosya\s*görüntüle|evrak\s*görüntüle|belge\s*görüntüle/i.test(text)
        );
      },
    );
    for (let i = 0; i < rowButtons.length; i++) {
      statusEl.textContent = `Dosyalar açılıyor (${i + 1}/${rowButtons.length})...`;
      try {
        rowButtons[i].click();
        await new Promise((resolve) => setTimeout(resolve, 900));
      } catch (_) {}
    }
    links = await deepCrawl(links, (pageCount, docCount) => {
      statusEl.textContent = `Derin tarama: ${pageCount} sayfa gezildi, ${docCount} belge bulundu...`;
    });
  }
  if (!links.length && !capturedFiles.size) {
    statusEl.textContent =
      'Bu sayfada belge bulunamadı. "Otomatik yakala"yı açıp UYAP\'ta belgeleri görüntüle; açtığın her belge kendiliğinden aktarılır.';
    document.querySelectorAll("#jurisai-panel button").forEach((b) => (b.disabled = false));
    return;
  }

  let inserted = 0;
  let skipped = 0;
  let batch = [];
  const uploadedCaptured = new Set();

  const flush = async () => {
    if (!batch.length) return;
    statusEl.textContent = `JURISAI'ye aktarılıyor (${inserted + skipped + batch.length}/${links.length})...`;
    try {
      const r = await sendBatch(apiUrl, jurisaiToken, batch);
      inserted += r.inserted;
      skipped += r.skipped;
    } catch (e) {
      statusEl.textContent = `Hata: ${e.message || "aktarım başarısız"}`;
      skipped += batch.length;
    }
    batch = [];
  };

  const reasons = { html: 0, http: 0, empty: 0, error: 0, server: 0 };

  for (const [key, file] of capturedFiles) {
    batch.push({
      name: fileNameFrom(
        file.url || "uyap-belge",
        "UYAP belge",
        file.contentType,
        file.disposition,
        key,
      ),
      mimeType: (file.contentType || "").split(";")[0] || undefined,
      contentBase64: file.contentBase64,
    });
    uploadedCaptured.add(key);
    if (batch.length >= BATCH_SIZE) await flush();
  }

  for (let i = 0; i < links.length; i++) {
    const [url, label] = links[i];
    statusEl.textContent = `Belgeler indiriliyor (${i + 1}/${links.length}) - ${inserted} aktarıldı`;
    try {
      const request = sniffedRequests.get(url);
      const headers = {};
      if (request?.contentType) headers["Content-Type"] = request.contentType;
      const res = await fetch(toHttps(url), {
        method: request?.method || "GET",
        body:
          request?.method && request.method !== "GET" && request.method !== "HEAD"
            ? request.body
            : undefined,
        headers,
        credentials: "include",
      });
      if (!res.ok) {
        reasons.http++;
        skipped++;
        continue;
      }
      const contentType = res.headers.get("content-type") || "";
      const disposition = res.headers.get("content-disposition") || "";
      if (/text\/html/i.test(contentType) && !/attachment/i.test(disposition)) {
        reasons.html++;
        skipped++;
        continue;
      }
      const blob = await res.blob();
      if (!blob.size || blob.size > 50 * 1024 * 1024) {
        reasons.empty++;
        skipped++;
        continue;
      }
      batch.push({
        name: fileNameFrom(url, label, contentType, disposition, `${url}:${request?.body || ""}`),
        mimeType: contentType.split(";")[0] || undefined,
        contentBase64: await toBase64(blob),
      });
      if (batch.length >= BATCH_SIZE) await flush();
    } catch (_) {
      reasons.error++;
      skipped++;
    }
  }
  await flush();
  uploadedCaptured.forEach((key) => capturedFiles.delete(key));

  if (inserted) {
    statusEl.textContent = `Tamamlandı: ${inserted} belge aktarıldı, ${skipped} atlandı.`;
  } else {
    const detay = [];
    if (reasons.html) detay.push(`${reasons.html} bağlantı belge değil (sayfa)`);
    if (reasons.http) detay.push(`${reasons.http} bağlantı reddedildi (oturum/yetki)`);
    if (reasons.empty) detay.push(`${reasons.empty} boş/çok büyük dosya`);
    if (reasons.error) detay.push(`${reasons.error} bağlantı hatası`);
    statusEl.textContent = `${links.length} bağlantı denendi, belge indirilemedi. ${
      detay.join(", ") || ""
    }. Bu sayfada dosya yoksa "UYAP İşlemlerim → Dosyalarım" içinden bir dosyanın evrak ekranını açıp tekrar dene.`;
  }
  document.querySelectorAll("#jurisai-panel button").forEach((b) => (b.disabled = false));
}

/* Otomatik yakala: UYAP'ta açtığın her belge (blob/PDF/JSON içi) anında aktarılır. */
let watchTimer = null;
let watchTotal = 0;

async function watchTick(statusEl) {
  if (!capturedFiles.size) return;
  const { jurisaiToken, jurisaiApiUrl } = await chrome.storage.sync.get([
    "jurisaiToken",
    "jurisaiApiUrl",
  ]);
  if (!jurisaiToken) {
    statusEl.textContent = "Eklenti simgesine tıklayıp JURISAI bağlantı anahtarını kaydet.";
    return;
  }
  const apiUrl = jurisaiApiUrl || "http://localhost:8766";
  const entries = [...capturedFiles.entries()].slice(0, BATCH_SIZE);
  const files = entries.map(([key, f]) => ({
    name: fileNameFrom(f.url || "uyap-belge", "UYAP belge", f.contentType, f.disposition, key),
    mimeType: (f.contentType || "").split(";")[0] || undefined,
    contentBase64: f.contentBase64,
  }));
  try {
    const r = await sendBatch(apiUrl, jurisaiToken, files);
    watchTotal += r.inserted;
    entries.forEach(([key]) => capturedFiles.delete(key));
    statusEl.textContent = `Otomatik yakala açık - ${watchTotal} belge aktarıldı.`;
  } catch (e) {
    statusEl.textContent = `Otomatik yakala: aktarım hatası (${e.message || "bilinmiyor"}).`;
  }
}

function toggleWatch(statusEl, button) {
  if (watchTimer) {
    clearInterval(watchTimer);
    watchTimer = null;
    button.textContent = "Otomatik yakalamayı başlat";
    statusEl.textContent = `Otomatik yakala kapatıldı. Toplam ${watchTotal} belge aktarıldı.`;
    return;
  }
  button.textContent = "Otomatik yakalamayı durdur";
  statusEl.textContent = "Otomatik yakala açık - UYAP'ta belgeleri açmaya başla.";
  watchTimer = setInterval(() => watchTick(statusEl), 2500);
}

function mountPanel() {
  if (document.getElementById("jurisai-panel") || window.top !== window) return;
  const panel = document.createElement("div");
  panel.id = "jurisai-panel";
  panel.innerHTML = `
    <button id="jurisai-close" title="Kapat">×</button>
    <h4>JURISAI</h4>
    <div style="font-size:11px;color:#94a3b8">Bu sayfadaki (iframe dahil) belgeleri hesabına aktar.</div>
    <button id="jurisai-run">Bu sayfadaki belgeleri aktar</button>
    <button id="jurisai-run-deep">Tüm dosyaları derin tara ve aktar</button>
    <button id="jurisai-watch">Otomatik yakalamayı başlat</button>
    <div id="jurisai-status"></div>`;
  document.body.appendChild(panel);
  const statusEl = panel.querySelector("#jurisai-status");
  panel
    .querySelector("#jurisai-run")
    .addEventListener("click", (e) => run(statusEl, e.currentTarget, false));
  panel
    .querySelector("#jurisai-run-deep")
    .addEventListener("click", (e) => run(statusEl, e.currentTarget, true));
  panel
    .querySelector("#jurisai-watch")
    .addEventListener("click", (e) => toggleWatch(statusEl, e.currentTarget));
  panel.querySelector("#jurisai-close").addEventListener("click", () => panel.remove());
}

mountPanel();

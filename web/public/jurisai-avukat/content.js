/* NHR Hukuk - UYAP Avukat Portalı içerik betiği
   Evrak tablosunu bulur, her satıra "NHR Hukuk'a Aktar" düğmesi enjekte eder,
   toplu aktarım için listenin üstüne bir araç çubuğu ekler.
   Kullanıcının kendi UYAP oturumu kullanılır; şifre/e-imza asla okunmaz.

   Otomatik aktarım (dosya açılınca evrakları kendiliğinden gönderme) yalnızca kullanıcı ayar
   penceresinde açıkça açtıysa çalışır; varsayılan KAPALIDIR. Kapalıyken yalnızca düğmeye basılan
   evrak gönderilir. */

(() => {
  let autoSync = false;
  try {
    // Ayar asenkron gelir; ilk tarama ondan önce bitmiş olabilir. Açıksa hemen yeniden taranır
    // (aksi halde sayfa değişmedikçe otomatik aktarım hiç başlamazdı).
    chrome.storage.sync.get(["autoSync"]).then((stored) => {
      autoSync = stored.autoSync === true;
      if (autoSync) refresh();
    });
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area === "sync" && changes.autoSync) {
        autoSync = changes.autoSync.newValue === true;
        if (autoSync) refresh();
      }
    });
  } catch (_) {
    /* ayar okunamazsa güvenli taraf: otomatik aktarım kapalı kalır */
  }

  const DOC_RE =
    /\.(pdf|udf|docx?|tiff?|jpe?g|png|eyp)(\?|#|$)|indir|download|evrak|dokuman|doküman|belge|goster|dosyaIndir|udfGoster/i;
  /* Yalnız UYAP'ın kendi alan adındaki ve yardım/kılavuz olmayan bağlantılar evrak sayılır. Sayfalarda
     e-Devlet kullanım kılavuzu gibi dış PDF'ler ve örnek belge bağlantıları durur; bunları evrak sanıp
     dava evrakı diye göndermek gerçek UYAP'ta görülen hataydı (aynı dosya farklı adlarla defalarca gelmişti). */
  const SITE_HOST_RE = /(^|\.)(uyap|adalet)\.gov\.tr$/i;
  const NOT_EVRAK_PATH_RE =
    /kilavuz|kılavuz|rehber|yardim|yardım|help|manual|ornek|örnek|sozlesme|sözleşme|nasil-?kullan|downloads\/portal|\/cdn\//i;
  const CHROME_AREA = "nav, header, footer, aside, [role='navigation'], [role='contentinfo']";
  function isEvrakUrl(url) {
    try {
      const parsed = new URL(url);
      return (
        SITE_HOST_RE.test(parsed.hostname) &&
        !NOT_EVRAK_PATH_RE.test(decodeURIComponent(parsed.pathname)) &&
        DOC_RE.test(url)
      );
    } catch (_) {
      return false;
    }
  }
  const BTN_CLASS = "jurisai-send-btn";
  const MAX_ROW_TEXT = 600; // bundan uzun metinli öğe tek bir evrak satırı değil, kapsayıcıdır
  const throttleGap = 1500; // portalın oturumu kapatmaması için istekler arası bekleme

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  /* ---------- Bildirim (toast) ---------- */
  let toastHost = null;
  function toast(message, kind = "info") {
    try {
      if (!toastHost) {
        toastHost = document.createElement("div");
        toastHost.className = "jurisai-toasts";
        document.body.appendChild(toastHost);
      }
      const el = document.createElement("div");
      el.className = `jurisai-toast jurisai-${kind}`;
      el.textContent = message;
      toastHost.appendChild(el);
      setTimeout(() => el.remove(), 5000);
    } catch (_) {
      /* sayfa kısıtlıysa sessiz geç */
    }
  }

  /* ---------- Metadata çıkarımı ---------- */
  function textOf(el) {
    return (el?.textContent || "").replace(/\s+/g, " ").trim();
  }

  function esasNoFrom(text) {
    const m = text.match(/\b(20\d{2})\s*[/-]\s*(\d{1,7})\b/);
    return m ? `${m[1]}/${m[2]}` : "";
  }

  function evrakTuruFrom(text) {
    const types = [
      "Dilekçe",
      "Tensip",
      "Karar",
      "Gerekçeli Karar",
      "Tebligat",
      "Bilirkişi Raporu",
      "Duruşma Tutanağı",
      "Müzekkere",
      "Haciz",
      "Ödeme Emri",
      "Vekaletname",
      "Cevap Dilekçesi",
      "Temyiz",
      "İstinaf",
      "Rapor",
      "Makbuz",
      "İddianame",
    ];
    const lower = text.toLocaleLowerCase("tr");
    return types.find((t) => lower.includes(t.toLocaleLowerCase("tr"))) || "";
  }

  function absolute(raw) {
    if (!raw) return "";
    if (/^(javascript|mailto|tel|data|blob):/i.test(raw)) return "";
    try {
      return new URL(raw, location.href).href;
    } catch (_) {
      return "";
    }
  }

  /** Bir satır/kart içindeki indirme adresini bulur. */
  function urlFromRow(row) {
    const candidates = [
      ...row.querySelectorAll(
        "a[href], [data-url], [data-href], [data-link], [onclick], [ng-click]",
      ),
    ];
    for (const el of candidates) {
      const raw =
        el.getAttribute("href") || el.dataset?.url || el.dataset?.href || el.dataset?.link || "";
      const url = absolute(raw);
      if (url && isEvrakUrl(url)) return url;
      const script = `${el.getAttribute("onclick") || ""} ${el.getAttribute("ng-click") || ""}`;
      const inline = (script.match(/['"]([^'"\s]{6,400})['"]/g) || [])
        .map((s) => absolute(s.slice(1, -1)))
        .find((u) => u && isEvrakUrl(u));
      if (inline) return inline;
    }
    return "";
  }

  function metaFromRow(row, url) {
    const text = textOf(row).slice(0, 400);
    const pageText = textOf(document.querySelector("h1,h2,.panel-title,.page-title")) || "";
    let evrakAdi = text.split(" ").slice(0, 12).join(" ") || "UYAP Evrakı";
    const nameFromUrl = decodeURIComponent((url.split("?")[0] || "").split("/").pop() || "");
    if (/\.(pdf|udf|docx?|tiff?|jpe?g|png|eyp)$/i.test(nameFromUrl)) evrakAdi = nameFromUrl;
    return {
      evrakId:
        row.getAttribute("data-id") ||
        row.getAttribute("data-evrak-id") ||
        row.id ||
        String(Math.abs(hash(url)).toString(36)),
      evrakAdi: evrakAdi.slice(0, 200),
      evrakTuru: evrakTuruFrom(text),
      dosyaEsasNo:
        esasNoFrom(text) ||
        esasNoFrom(pageText) ||
        esasNoFrom(textOf(document.body).slice(0, 3000)),
      birim: (pageText || "").slice(0, 160),
      url,
    };
  }

  function hash(text) {
    let h = 2166136261;
    for (let i = 0; i < text.length; i++) {
      h ^= text.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }

  /* ---------- Aktarım ---------- */
  async function sendOne(meta, button) {
    if (button) {
      button.disabled = true;
      button.textContent = "Aktarılıyor…";
    }
    try {
      const res = await chrome.runtime.sendMessage({ type: "JURISAI_UPLOAD", payload: meta });
      if (res?.ok) {
        if (button) {
          button.textContent = res.duplicate ? "Zaten var" : "Aktarıldı ✓";
          button.classList.add("jurisai-done");
        }
        toast(`${meta.evrakAdi} aktarıldı.`, "success");
        return true;
      }
      throw new Error(res?.error || "bilinmeyen hata");
    } catch (error) {
      if (button) {
        button.disabled = false;
        button.textContent = "NHR Hukuk'a Aktar";
      }
      toast(`Aktarılamadı: ${error.message}`, "error");
      return false;
    }
  }

  /* ---------- Düğme enjeksiyonu ---------- */
  const ROW_SELECTOR = "table tr, li, .list-group-item, .evrak-satir";

  /** Satırdaki bağlantılardan indirileni seçer ("indir"/dosya uzantısı), yoksa ilkini. */
  function primaryDocUrl(urls) {
    return (
      urls.find((u) => /indir|download|\.(pdf|udf|docx?|tiff?|jpe?g|png|eyp)(\?|#|$)/i.test(u)) ||
      urls[0]
    );
  }

  /** Sayfada bir dava/dosya bağlamı var mı (esas numarası)? Giriş ve ana sayfalarda düğme çıkmaz. */
  function hasCaseContext() {
    return !!esasNoFrom((document.body?.textContent || "").replace(/\s+/g, " ").slice(0, 40000));
  }

  function injectRowButtons() {
    if (!hasCaseContext()) return 0;
    // Genel kapsayıcılar (.card, .row) bilerek yok: tüm bölümü tek "evrak" sanıp yanlış düğme koyuyordu.
    const rows = [...document.querySelectorAll(ROW_SELECTOR)];
    let count = 0;
    for (const row of rows) {
      if (row.querySelector(`.${BTN_CLASS}`)) {
        count++;
        continue;
      }
      if (row.closest("nav, header, footer, [role='navigation']")) continue;
      if (textOf(row).length > MAX_ROW_TEXT) continue;
      const found = collectDocUrls(row);
      if (!found.length) continue;
      // İç içe başka bir evrak satırı barındıran öğe bir kapsayıcıdır; belgelerin kendi
      // satırları ayrıca ele alınır. (Tek satırda hem "Görüntüle" hem "İndir" olabilir.)
      const hasNestedRow = [...row.querySelectorAll(ROW_SELECTOR)].some(
        (inner) => inner !== row && collectDocUrls(inner).length > 0,
      );
      if (hasNestedRow) continue;
      const url = primaryDocUrl(found);
      const button = document.createElement("button");
      button.type = "button";
      button.className = BTN_CLASS;
      button.textContent = "NHR Hukuk'a Aktar";
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        sendOne(metaFromRow(row, url), button);
      });
      const cell = row.lastElementChild && row.tagName === "TR" ? row.lastElementChild : row;
      cell.appendChild(button);
      count++;
    }
    return count;
  }

  function injectToolbar() {
    if (document.querySelector(".jurisai-toolbar")) return;
    const bar = document.createElement("div");
    bar.className = "jurisai-toolbar";

    const label = document.createElement("span");
    label.className = "jurisai-brand";
    label.textContent = "⚖️ NHR Hukuk";

    const allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.className = "jurisai-send-all";
    allBtn.textContent = "Bu sayfadaki tüm evrakları aktar";
    allBtn.addEventListener("click", async () => {
      const buttons = [...document.querySelectorAll(`.${BTN_CLASS}:not(.jurisai-done)`)];
      if (!buttons.length) return toast("Aktarılacak evrak bulunamadı.", "info");
      // Toplu aktarım açık onaysız başlamaz: müvekkil belgeleri kullanıcının hesabına gider.
      if (
        !window.confirm(
          `Bu sayfadaki ${buttons.length} evrak NHR Hukuk hesabınıza aktarılacak. Devam edilsin mi?`,
        )
      ) {
        return;
      }
      allBtn.disabled = true;
      let ok = 0;
      for (let i = 0; i < buttons.length; i++) {
        allBtn.textContent = `Aktarılıyor ${i + 1}/${buttons.length}`;
        buttons[i].click();
        await sleep(throttleGap); // rate limiting
        if (buttons[i].classList.contains("jurisai-done")) ok++;
      }
      allBtn.disabled = false;
      allBtn.textContent = "Bu sayfadaki tüm evrakları aktar";
      toast(`${ok}/${buttons.length} evrak aktarıldı.`, ok ? "success" : "error");
    });

    bar.append(label, allBtn);
    document.body.appendChild(bar);
  }

  /* ---------- Dava listesi sayfası yardımcıları ---------- */
  const OPEN_RE = /dosya görüntüle|dosyayı görüntüle|dosya goruntule|görüntüle/i;

  function openButtonsInRow(row) {
    return [...row.querySelectorAll("button, a, input[type='button'], span")].filter((el) => {
      const t = `${el.textContent || ""} ${el.value || ""}`.replace(/\s+/g, " ").trim();
      return t.length < 40 && OPEN_RE.test(t);
    });
  }

  function injectCaseListHelpers() {
    const rows = [...document.querySelectorAll("table tr")];
    let found = 0;
    for (const row of rows) {
      if (row.querySelector(".jurisai-open-btn")) {
        found++;
        continue;
      }
      const [target] = openButtonsInRow(row);
      if (!target) continue;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "jurisai-send-btn jurisai-open-btn";
      btn.textContent = "Dosyayı aç → evrakları aktar";
      btn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        toast(
          "Dosya açılıyor… Açılan ekranda Evraklar sekmesine geçin, düğmeler orada çıkacak.",
          "info",
        );
        target.click();
      });
      (row.lastElementChild || row).appendChild(btn);
      found++;
    }
    if (found > 0) injectHint();
    return found;
  }

  function injectHint() {
    if (document.querySelector(".jurisai-hint")) return;
    const hint = document.createElement("div");
    hint.className = "jurisai-toolbar jurisai-hint";
    hint.textContent =
      "⚖️ NHR Hukuk: Bu sayfa dosya listesi, evraklar burada bulunmaz. Bir dosyayı açın (Dosya Görüntüle) ve Evraklar/Belgeler sekmesine geçin — aktarım düğmeleri orada görünür.";
    document.body.appendChild(hint);
  }

  /** UYAP dosya penceresi önce "Taraf Bilgileri" ile açılır. Evraklar ancak
      bu sekmeye basıldıktan sonra AJAX ile geldiği için sekmeyi kendimiz açarız. */
  function openEvrakTab(scope = document) {
    const candidates = [...scope.querySelectorAll("a, button, [role='tab'], li")];
    const tab = candidates.find((el) => {
      const text = textOf(el).toLocaleLowerCase("tr");
      if (text !== "evrak") return false; // "Evrak Gönderme" sekmesine basma
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
    if (!tab) return false;
    const active =
      tab.classList.contains("active") ||
      tab.parentElement?.classList.contains("active") ||
      tab.getAttribute("aria-selected") === "true";
    if (!active) tab.click();
    return true;
  }

  const preparedDialogs = new WeakSet();
  function prepareOpenCaseDialogs() {
    if (!autoSync) return; // otomatik aktarım kapalıyken pencereye dokunma, hiçbir şey gönderme
    const dialogs = [...document.querySelectorAll("[role='dialog'], .modal")];
    for (const dialog of dialogs) {
      const rect = dialog.getBoundingClientRect();
      if (!rect.width || !rect.height || preparedDialogs.has(dialog)) continue;
      const heading = textOf(dialog.querySelector("h1,h2,h3,h4,.modal-title"));
      if (!esasNoFrom(heading) && !/dava dosyası|takip dosyası/i.test(heading)) continue;
      preparedDialogs.add(dialog);
      const meta = caseMetaFrom(textOf(dialog).slice(0, 6000));
      const bubble = liveToast("Evrak sekmesi açılıyor; belgeler hazırlanıyor…");
      openEvrakTab(dialog);
      setTimeout(() => {
        const docUrls = collectDocUrls(dialog);
        if (docUrls.length) {
          bubble.done(`${docUrls.length} evrak bulundu, aktarım başlatıldı.`, "success", 4000);
          autoIngest({ ...meta, url: location.href }, docUrls);
        } else {
          bubble.done("Evrak listesi yükleniyor…", "info", 2500);
          scheduleDetailSweep(meta, dialog);
        }
      }, 1400);
    }
  }

  function refresh() {
    try {
      prepareOpenCaseDialogs();
      const count = injectRowButtons();
      if (count > 0) {
        document.querySelector(".jurisai-hint")?.remove();
        injectToolbar();
      } else {
        injectCaseListHelpers();
      }
    } catch (_) {
      /* portal DOM'u değişirse sessiz geç */
    }
  }

  /* ---------- Otomatik aktarım (tıklama dinleyicisi) ---------- */

  /** Güncellenebilir bildirim kutusu. */
  function liveToast(message) {
    if (!toastHost) {
      toastHost = document.createElement("div");
      toastHost.className = "jurisai-toasts";
      document.body.appendChild(toastHost);
    }
    const el = document.createElement("div");
    el.className = "jurisai-toast jurisai-live";
    el.textContent = message;
    toastHost.appendChild(el);
    return {
      update(text, kind) {
        el.textContent = text;
        if (kind) el.className = `jurisai-toast jurisai-${kind}`;
      },
      done(text, kind = "success", ms = 6000) {
        el.textContent = text;
        el.className = `jurisai-toast jurisai-${kind}`;
        setTimeout(() => el.remove(), ms);
      },
    };
  }

  const COURT_RE =
    /([A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ.]*\s+)?\d*\.?\s*(Asliye Ceza|Ağır Ceza|Ceza|Asliye Hukuk|Sulh Hukuk|İş|Aile|Tüketici|İcra|İdare|Vergi|Ticaret|Kadastro|Fikri)\s*(Mahkemesi|Dairesi|Müdürlüğü|Hakimliği)/i;
  const DATE_RE = /\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?:\s+(\d{1,2}:\d{2}))?/;

  function courtFrom(text) {
    const m = text.match(COURT_RE);
    if (m) return m[0].replace(/\s+/g, " ").trim().slice(0, 160);
    const m2 = text.match(
      /([\wçğıöşüÇĞİÖŞÜ.]+\s+){0,4}(Mahkemesi|Müdürlüğü|Dairesi|Başsavcılığı)/i,
    );
    return m2 ? m2[0].replace(/\s+/g, " ").trim().slice(0, 160) : "";
  }

  function partyFrom(text) {
    const m = text.match(
      /(?:Taraf|Davacı|Davalı|Müşteki|Sanık|Şüpheli|Alacaklı|Borçlu|Vekil)\s*[:\-]?\s*([A-ZÇĞİÖŞÜ][^|,;\n]{2,60})/i,
    );
    return m ? m[1].replace(/\s+/g, " ").trim().slice(0, 120) : "";
  }

  function caseMetaFrom(scopeText) {
    const text = (scopeText || "").replace(/\s+/g, " ");
    const date = text.match(DATE_RE);
    return {
      mahkeme: courtFrom(text),
      dosyaEsasNo: esasNoFrom(text),
      durusmaTarihi: date ? date[0] : "",
      taraf: partyFrom(text),
      evrakTuru: evrakTuruFrom(text),
      ozet: text.slice(0, 1200),
      url: location.href,
    };
  }

  /** Verilen kapsamdaki tüm belge indirme adreslerini toplar. */
  function collectDocUrls(scope) {
    const out = new Set();
    const nodes = [
      ...(scope || document).querySelectorAll(
        "a[href], [data-url], [data-href], [onclick], [ng-click]",
      ),
    ];
    for (const el of nodes) {
      if (el.closest(CHROME_AREA)) continue; // menü, üst/alt bilgi ve yan paneldeki bağlantılar evrak değildir
      const raw = el.getAttribute("href") || el.dataset?.url || el.dataset?.href || "";
      const url = absolute(raw);
      if (url && isEvrakUrl(url)) out.add(url);
      const script = `${el.getAttribute("onclick") || ""} ${el.getAttribute("ng-click") || ""}`;
      for (const q of script.match(/['"]([^'"\s]{6,400})['"]/g) || []) {
        const u = absolute(q.slice(1, -1));
        if (u && isEvrakUrl(u)) out.add(u);
      }
      if (out.size >= 25) break;
    }
    return [...out];
  }

  const autoSent = new Set();
  let autoBusy = false;

  async function autoIngest(meta, docUrls) {
    if (!autoSync) return;
    const key = `${meta.dosyaEsasNo}|${meta.mahkeme}|${docUrls.slice(0, 3).join(",")}`;
    if (autoSent.has(key) || autoBusy) return;
    autoSent.add(key);
    autoBusy = true;
    const label = meta.mahkeme || meta.dosyaEsasNo || "Dosya";
    const bubble = liveToast("Dosya NHR Hukuk'a aktarılıyor…");
    try {
      const res = await chrome.runtime.sendMessage({
        type: "AUTO_INGEST_CASE",
        payload: { ...meta, docUrls },
      });
      if (res?.ok) {
        bubble.done(
          `${label} dosyası NHR Hukuk'a başarıyla aktarıldı${res.files ? ` (${res.files} evrak)` : ""}`,
          "success",
        );
      } else {
        bubble.done(`Aktarılamadı: ${res?.error || "bilinmeyen hata"}`, "error", 8000);
      }
    } catch (error) {
      bubble.done(`Aktarılamadı: ${error.message}`, "error", 8000);
    } finally {
      autoBusy = false;
    }
  }

  /** Dosya detay ekranı açıldıktan sonra evrakları da yakalar. */
  function scheduleDetailSweep(baseMeta, scope = document) {
    if (!autoSync) return;
    for (const delay of [900, 2500, 6000]) {
      setTimeout(async () => {
        try {
          openEvrakTab(scope);
          await sleep(700);
          const docUrls = collectDocUrls(scope);
          const meta = caseMetaFrom(textOf(scope).slice(0, 6000));
          autoIngest(
            {
              ...baseMeta,
              mahkeme: baseMeta.mahkeme || meta.mahkeme,
              dosyaEsasNo: baseMeta.dosyaEsasNo || meta.dosyaEsasNo,
              durusmaTarihi: baseMeta.durusmaTarihi || meta.durusmaTarihi,
              taraf: baseMeta.taraf || meta.taraf,
              ozet: meta.ozet || baseMeta.ozet,
              url: location.href,
            },
            docUrls,
          );
        } catch (_) {
          /* sessiz */
        }
      }, delay);
    }
  }

  document.addEventListener(
    "click",
    (event) => {
      try {
        if (!autoSync) return; // yalnız açıkça açılmış otomatik aktarımda tıklamalar izlenir
        const target = event.target;
        if (!(target instanceof Element)) return;
        if (target.closest(`.${BTN_CLASS}, .jurisai-toolbar, .jurisai-toast`)) return;
        const row = target.closest("tr, .list-group-item, .card, .evrak-satir");
        const scopeText = textOf(row || target.closest("a, button") || target);
        if (!scopeText) return;
        const meta = caseMetaFrom(scopeText);
        if (!meta.dosyaEsasNo) return; // esas numarası olmayan metin bir dosya değildir
        const docUrls = row ? collectDocUrls(row) : [];
        if (docUrls.length) autoIngest(meta, docUrls);
        scheduleDetailSweep(meta);
      } catch (_) {
        /* sessiz */
      }
    },
    true,
  );

  refresh();

  const observer = new MutationObserver(() => {
    clearTimeout(observer._timer);
    observer._timer = setTimeout(refresh, 600);
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });

  /* ---------- Sayfa tanısı ----------
     Gerçek UYAP sayfası yapısı değiştiğinde seçicileri ayarlamak için YAPI özeti üretir. Hiçbir metin,
     isim, numara ya da bağlantı değeri içermez: yalnız sayılar, rakamları maskelenmiş yol biçimleri ve
     sorgu parametresi ADLARI. Popup'taki "Sayfa tanısını kopyala" düğmesi bunu çağırır. */
  const mask = (value) => String(value).replace(/\d/g, "#").slice(0, 80);
  function urlShape(raw) {
    try {
      const url = new URL(raw, location.href);
      const keys = [...url.searchParams.keys()].slice(0, 8).join(",");
      return `${url.hostname === location.hostname ? "" : "(dış) "}${mask(url.pathname)}${keys ? "?" + keys : ""}`;
    } catch (_) {
      return "(çözümlenemedi)";
    }
  }
  function diagnose() {
    const rows = [...document.querySelectorAll(ROW_SELECTOR)];
    const withUrls = rows.filter((row) => collectDocUrls(row).length);
    const shapes = new Map();
    for (const row of withUrls.slice(0, 40)) {
      for (const url of collectDocUrls(row).slice(0, 3)) {
        const shape = urlShape(url);
        shapes.set(shape, (shapes.get(shape) || 0) + 1);
      }
    }
    return {
      extensionVersion: chrome.runtime.getManifest().version,
      frame: window === window.top ? "üst" : "iç",
      host: location.hostname,
      path: mask(location.pathname),
      caseContext: hasCaseContext(),
      tables: document.querySelectorAll("table").length,
      candidateRows: rows.length,
      rowsWithDocUrls: withUrls.length,
      rowsTooLong: rows.filter((row) => textOf(row).length > MAX_ROW_TEXT).length,
      buttonsInjected: document.querySelectorAll(`.${BTN_CLASS}`).length,
      toolbar: !!document.querySelector(".jurisai-toolbar"),
      docUrlShapes: [...shapes].map(([shape, count]) => ({ shape, count })).slice(0, 12),
      autoSync,
    };
  }
  window.__jurisaiDiagnose = diagnose;

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "JURISAI_TOAST") {
      toast(message.message, message.kind || "info");
      sendResponse({ ok: true });
      return true;
    }
    if (message?.type === "JURISAI_RESCAN") {
      refresh();
      sendResponse({ ok: true, count: document.querySelectorAll(`.${BTN_CLASS}`).length });
      return true;
    }
    return false;
  });
})();

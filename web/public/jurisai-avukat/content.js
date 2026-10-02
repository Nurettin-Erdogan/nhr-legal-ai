/* JurisAI - UYAP Avukat Portalı içerik betiği
   Evrak tablosunu bulur, her satıra "JurisAI'ya Aktar" düğmesi enjekte eder,
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
  // Menü/kenar çubuğu (gerçek portalda <nav>/<aside> değil, sınıf adlarıyla): "Evrak Sorgulama" gibi menü bağlantıları evrak değildir.
  const CHROME_AREA =
    "nav, header, footer, aside, [role='navigation'], [role='contentinfo'], [class*='menu'], [class*='sidebar'], [class*='navbar']";
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
        button.textContent = "JurisAI'ya Aktar";
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
    // Görünen metin (innerText) önce: gerçek portalda gizli pencere/menü metni tablodan önce geldiği için ilk
    // 40.000 karakter esas numarasını içermiyordu.
    const visible = (document.body?.innerText || "").replace(/\s+/g, " ");
    const all = (document.body?.textContent || "").replace(/\s+/g, " ");
    return !!(esasNoFrom(visible.slice(0, 40000)) || esasNoFrom(all.slice(0, 40000)));
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
      button.textContent = "JurisAI'ya Aktar";
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
    label.textContent = "⚖️ JurisAI";

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
          `Bu sayfadaki ${buttons.length} evrak JurisAI hesabınıza aktarılacak. Devam edilsin mi?`,
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
      btn.textContent = "JurisAI: evrakları seç ve çek";
      btn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        openCaseAndChoose(target);
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
      "⚖️ JurisAI: Bu sayfa dosya listesi, evraklar burada bulunmaz. Bir dosyayı açın (Dosya Görüntüle) ve Evraklar/Belgeler sekmesine geçin — aktarım düğmeleri orada görünür.";
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

  let lastRefreshError = "";
  function refresh() {
    // Her adım ayrı korunur: biri patlarsa diğerleri (özellikle sabit düğme) yine çalışır. Hata tanıya yazılır.
    const step = (fn) => {
      try {
        return fn();
      } catch (error) {
        lastRefreshError = `${error?.name || "Error"}: ${String(error?.message || error).slice(0, 120)}`;
        return 0;
      }
    };
    step(prepareOpenCaseDialogs);
    const count = step(injectRowButtons);
    if (count > 0) {
      document.querySelector(".jurisai-hint")?.remove();
      step(injectToolbar);
    } else {
      step(injectCaseListHelpers);
    }
    step(injectLauncher);
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
    const bubble = liveToast("Dosya JurisAI'ya aktarılıyor…");
    try {
      const res = await chrome.runtime.sendMessage({
        type: "AUTO_INGEST_CASE",
        payload: { ...meta, docUrls },
      });
      if (res?.ok) {
        bubble.done(
          `${label} dosyası JurisAI'ya başarıyla aktarıldı${res.files ? ` (${res.files} evrak)` : ""}`,
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
  /* Yapı iskeleti: etiket + sınıf + öznitelik ADLARI ve sayıları. Metin ve öznitelik DEĞERİ yok. */
  const maskClass = (value) => String(value).replace(/\d+/g, "#").slice(0, 40);
  function structureSketch(root) {
    const signatures = new Map();
    let seen = 0;
    for (const el of root.querySelectorAll("*")) {
      if (++seen > 4000) break;
      if (/^(script|style|svg|path|link|meta|noscript|br|hr)$/i.test(el.tagName)) continue;
      const classes = [...el.classList].slice(0, 3).map(maskClass).join(".");
      const attrs = [...el.attributes]
        .map((attr) => attr.name)
        .filter((name) => !["class", "style", "id"].includes(name))
        .sort()
        .slice(0, 6)
        .join(",");
      const key = `${el.tagName.toLowerCase()}${classes ? "." + classes : ""}${attrs ? `[${attrs}]` : ""}`;
      signatures.set(key, (signatures.get(key) || 0) + 1);
    }
    return [...signatures]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 45)
      .map(([element, count]) => ({ element, count }));
  }
  /* Klasör ağacı (jsTree vb.) düğümleri: evraklar bağlantı değil ağaç yaprağıysa seçiciler buna göre yazılır. */
  function treeSketch(root) {
    const nodes = [...root.querySelectorAll("li, a, [role='treeitem'], span, div")].filter(
      (el) => /tree|node|leaf|folder|jstree|dtree|fancytree/i.test(el.className || "") || el.getAttribute("role") === "treeitem",
    );
    const sample = nodes.slice(0, 8).map((el) => {
      const onclick = el.getAttribute("onclick") || "";
      const href = el.getAttribute("href");
      return {
        tag: el.tagName.toLowerCase(),
        classes: [...el.classList].slice(0, 4).map(maskClass),
        attributeNames: [...el.attributes].map((attr) => attr.name).filter((n) => n !== "class").slice(0, 8),
        onclickFunction: onclick ? onclick.replace(/\(.*$/s, "(…)").slice(0, 40) : "",
        href: href === null ? "" : /^(#|javascript)/i.test(href) ? href.slice(0, 20) : urlShape(href),
        hasChildList: !!el.querySelector("ul"),
        isLeaf: !el.querySelector("ul, li"),
      };
    });
    return { count: nodes.length, sample };
  }
  function activeRoot() {
    const dialogs = [...document.querySelectorAll("[role='dialog'], .modal")].filter((el) => {
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
    return dialogs[dialogs.length - 1] || null;
  }
  function diagnose() {
    const root = activeRoot();
    const scope = root || document.body;
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
      scope: root ? "açık pencere" : "sayfa",
      refreshError: lastRefreshError,
      launcher: !!document.querySelector(".jurisai-launcher"),
      caseOpenTargets: caseOpenTargets().length,
      // Düğme etiketleri arayüz metnidir (kişisel veri değil); evrak/kişi adı taşıyan bağlantılar dahil değil.
      buttonLabels: [
        ...new Set(
          [...scope.querySelectorAll("button, input[type='button'], a.btn")]
            .map((el) => textOf(el) || el.value || "")
            .filter((text) => text && text.length <= 40),
        ),
      ].slice(0, 20),
      tabLabels: [
        ...new Set(
          [...scope.querySelectorAll("[role='tab'], .nav-tabs a, .nav-tabs li, ul.nav li")]
            .map((el) => textOf(el))
            .filter((text) => text && text.length <= 30),
        ),
      ].slice(0, 12),
      iframes: [...scope.querySelectorAll("iframe")].slice(0, 5).map((el) => urlShape(el.getAttribute("src") || "about:blank")),
      tree: treeSketch(scope),
      structure: structureSketch(scope),
      autoSync,
    };
  }
  window.__jurisaiDiagnose = diagnose;

  /* ---------- Açık dosya penceresindeki evrakları klasör yapısıyla çekme ----------
     Yalnızca kullanıcı eklenti penceresindeki düğmeye basınca ve onay verince çalışır; otomatik aktarım
     ayarından bağımsızdır. Ağaç (jQuery treeview: li.expandable/collapsable, span.folder, span.file[evrak_id])
     açılır, her evrak yaprağına tıklanır, UYAP'ın ön izleme isteği arka planda yakalanıp belge indirilir. */
  let pulling = null;
  const folderName = (text) => text.replace(/\s*\(\d+\)\s*$/, "").replace(/\s+/g, " ").trim();

  async function waitUntil(check, timeoutMs, stepMs = 200) {
    const end = Date.now() + timeoutMs;
    while (Date.now() < end) {
      if (await check()) return true;
      await sleep(stepMs);
    }
    return false;
  }
  // "İ" harfi büyük/küçük harf duyarsız normal ifadede "i" ile eşleşmez: Türkçe küçük harfe çevrilir.
  const trLower = (text) => String(text || "").toLocaleLowerCase("tr");
  function previewButton(dialog) {
    return [...dialog.querySelectorAll("button, input[type='button']")].find((el) =>
      /ön\s*izleme/.test(trLower(textOf(el) || el.value)),
    );
  }
  /** "Ön İzlemeyi Aktifleştir" düğmesi yalnız kapalıyken basılır (basınca açılıp kapanmasın). */
  async function ensurePreview(dialog) {
    const button = previewButton(dialog);
    if (!button) return false;
    if (/aktifle/.test(trLower(textOf(button) || button.value))) {
      button.click();
      await sleep(1200);
    }
    return true;
  }
  /** Kapalı klasörleri (ve eki olan evrakları) açar. Yaprağın kendisine tıklanmaz: ön izleme isteği tetikler. */
  async function expandAll(dialog) {
    const attempts = new Map();
    for (let pass = 0; pass < 20; pass += 1) {
      const closed = [...dialog.querySelectorAll("li.expandable")].filter((li) => (attempts.get(li) || 0) < 3);
      if (!closed.length) return;
      for (const li of closed) {
        const handle = li.querySelector(":scope > div.hitarea") || li.querySelector(":scope > span.folder");
        attempts.set(li, (attempts.get(li) || 0) + 1);
        handle?.click();
        // Alt düğümler AJAX ile yüklenebilir: açılmasını (class değişimi) kısa süre bekle.
        await waitUntil(() => !li.classList.contains("expandable"), 1500, 100);
      }
    }
  }
  /** Gerçek bir fare tıklaması gibi: üzerine gelme, basma, bırakma, tıklama (UYAP üzerine-gelme sınıfını da kullanıyor). */
  function realClick(element) {
    element.scrollIntoView({ block: "center" });
    for (const type of ["mouseover", "mousedown", "mouseup", "click"]) {
      element.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window, button: 0 }));
    }
  }
  /** Ağaçtaki evrakları klasör yoluyla listeler; "Son 20 Evrak" kısayolu ve yinelenen evrak kimlikleri elenir. */
  function collectEvraklar(dialog) {
    const byId = new Map();
    for (const span of dialog.querySelectorAll("span.file[evrak_id]")) {
      const id = span.getAttribute("evrak_id");
      if (!id) continue;
      const chain = [];
      const folderLabels = [];
      for (let li = span.closest("li")?.parentElement?.closest("li"); li; li = li.parentElement?.closest("li")) {
        const label = li.querySelector(":scope > span.folder, :scope > span.file");
        if (label) {
          chain.unshift(textOf(label));
          if (label.classList.contains("folder")) folderLabels.unshift(textOf(label));
        }
      }
      const inRecent = chain.some((label) => /^Dosyaya Eklenen Son/i.test(label));
      const folders = chain
        .slice(1) // ilk öğe dosyanın kendisi (mahkeme + esas no); klasör yolu onun altından başlar
        .filter((label) => !/^Tüm Evraklar$/i.test(label) && !/^Dosyaya Eklenen Son/i.test(label))
        .map(folderName);
      const isEk = span.hasAttribute("ana_evrak_id");
      // Ekin türü "Ek"; diğerlerinde en yakın klasör adı (bağlı olduğu evrakın başlığı değil).
      const typeName = isEk
        ? "Ek"
        : folderName(folderLabels.filter((l) => !/^Tüm Evraklar$/i.test(l) && !/^Dosyaya Eklenen Son/i.test(l)).pop() || "Evrak");
      const entry = { id, span, title: textOf(span), folders, typeName, inRecent, isEk };
      const existing = byId.get(id);
      if (!existing || (existing.inRecent && !inRecent)) byId.set(id, entry);
    }
    const all = [...byId.values()];
    // "Dosyaya Eklenen Son 20 Evrak", "Tüm Evraklar"daki evrakların kısayol kopyasıdır (gerçek portalda kopyalar
    // farklı evrak_id taşıdığı için 4 evrak 8 görünmüştü): "Tüm Evraklar" varsa yalnız o kullanılır.
    const full = all.filter((entry) => !entry.inRecent);
    return full.length ? full : all;
  }
  function dosyaIdentity(dialog) {
    const title = textOf(dialog.querySelector("h1,h2,h3,h4,.modal-title"));
    return { esas: esasNoFrom(title), birim: (title.split(" - ")[1] || courtFrom(title) || "").trim().slice(0, 160) };
  }

  /** Çekmeden önce kullanıcı hangi evrakların çekileceğini ve ne yapılacağını seçer (metinler textContent ile, innerHTML yok). */
  function chooseEvraklar(items, who, preferred) {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.className = "jurisai-chooser";
      overlay.setAttribute("role", "dialog");
      overlay.style.cssText =
        "position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,.55);display:flex;align-items:center;" +
        "justify-content:center;font:14px system-ui,sans-serif;";
      const box = document.createElement("div");
      box.style.cssText =
        "background:#fff;color:#111;max-width:660px;width:92vw;max-height:86vh;display:flex;flex-direction:column;" +
        "border-radius:10px;box-shadow:0 10px 40px rgba(0,0,0,.4);";
      const make = (tag, css, content) => {
        const el = document.createElement(tag);
        if (css) el.style.cssText = css;
        if (content !== undefined) el.textContent = content;
        return el;
      };
      const head = make("div", "padding:16px 18px 8px;");
      head.append(
        make("div", "font-weight:700;font-size:16px;", "JurisAI: çekilecek evrakları seç"),
        make("div", "color:#555;margin-top:4px;", `${who.esas || "Dosya"}${who.birim ? ` · ${who.birim}` : ""} · ${items.length} evrak`),
      );
      const list = make("div", "padding:0 18px;overflow:auto;flex:1;");
      const boxes = [];
      const groups = new Map();
      for (const item of items) {
        const key = item.folders.join(" / ") || "(klasörsüz)";
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(item);
      }
      const counter = make("div", "color:#333;font-weight:600;");
      const refresh = () => {
        const n = boxes.filter((entry) => entry.input.checked).length;
        counter.textContent = `${n} / ${items.length} evrak seçili`;
        for (const button of [diskButton, uploadButton]) button.disabled = n === 0;
      };
      for (const [label, group] of groups) {
        const heading = make("label", "display:flex;gap:8px;align-items:center;margin:12px 0 4px;font-weight:600;color:#1d4ed8;");
        const groupInput = document.createElement("input");
        groupInput.type = "checkbox";
        groupInput.checked = true;
        heading.append(groupInput, make("span", "", `📁 ${label}`));
        list.append(heading);
        const members = [];
        for (const item of group) {
          const row = make("label", "display:flex;gap:8px;align-items:center;margin:2px 0 2px 24px;");
          const input = document.createElement("input");
          input.type = "checkbox";
          input.checked = true;
          input.className = "jurisai-pick-item";
          input.dataset.index = String(items.indexOf(item));
          input.addEventListener("change", refresh);
          row.append(input, make("span", "", item.isEk ? `↳ ${item.title}` : item.title));
          list.append(row);
          boxes.push({ input, item });
          members.push(input);
        }
        groupInput.addEventListener("change", () => {
          for (const input of members) input.checked = groupInput.checked;
          refresh();
        });
      }
      const note = make(
        "div",
        "padding:8px 18px;color:#92400e;background:#fffbeb;font-size:12px;",
        "Müvekkil verisi içerebilir; yalnızca yetkili olduğun dosyalarda devam et. UYAP'a istekler yavaş gönderilir " +
          "(her evrak için birkaç saniye); eklenti penceresinden durdurabilirsin.",
      );
      const buttons = make("div", "display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:12px 18px 16px;");
      const style = (primary) =>
        `padding:8px 12px;border-radius:8px;border:1px solid #2563eb;cursor:pointer;` +
        (primary ? "background:#2563eb;color:#fff;" : "background:#fff;color:#2563eb;");
      const diskButton = make("button", style(preferred === "disk"), "Seçilenleri bilgisayarıma indir");
      diskButton.id = "jurisai-pick-disk";
      const uploadButton = make("button", style(preferred !== "disk"), "Seçilenleri JurisAI'ya aktar");
      uploadButton.id = "jurisai-pick-upload";
      const cancelButton = make("button", style(false), "İptal");
      cancelButton.id = "jurisai-pick-cancel";
      const toggle = make("button", "padding:4px 8px;border:0;background:none;color:#2563eb;cursor:pointer;", "Tümünü seç / kaldır");
      toggle.addEventListener("click", () => {
        const all = boxes.every((entry) => entry.input.checked);
        for (const entry of boxes) entry.input.checked = !all;
        refresh();
      });
      const finish = (action) => {
        overlay.remove();
        resolve({ action, selected: boxes.filter((entry) => entry.input.checked).map((entry) => entry.item) });
      };
      diskButton.addEventListener("click", () => finish("disk"));
      uploadButton.addEventListener("click", () => finish("upload"));
      cancelButton.addEventListener("click", () => finish(null));
      buttons.append(counter, toggle, make("span", "flex:1"), diskButton, uploadButton, cancelButton);
      box.append(head, list, note, buttons);
      overlay.append(box);
      document.body.append(overlay);
      refresh();
    });
  }

  async function pullDosya(preferred = "upload") {
    if (pulling) return { ok: false, error: "Çekme zaten sürüyor" };
    const dialog = activeRoot();
    if (!dialog) return { ok: false, error: "Açık bir dosya penceresi yok: UYAP'ta dosyayı aç, Evrak sekmesine geç." };
    pulling = { stop: false };
    const stats = { sent: 0, duplicates: 0, sameContent: 0, failed: 0, errors: [] };
    try {
      toast("Evrak ağacı açılıyor…");
      if (!(await ensurePreview(dialog))) return { ok: false, error: "Ön izleme düğmesi bulunamadı (Evrak sekmesinde misin?)" };
      await expandAll(dialog);
      const items = collectEvraklar(dialog);
      if (!items.length) return { ok: false, error: "Ağaçta evrak bulunamadı. Evrak sekmesini aç ve tekrar dene." };
      const who = dosyaIdentity(dialog);
      const choice = await chooseEvraklar(items, who, preferred);
      if (!choice.action) return { ok: true, cancelled: true, found: items.length };
      const mode = choice.action;
      const toDisk = mode === "disk";
      const todo = choice.selected; // evrak sayısı sınırı yok: hız (evrak başına birkaç sn), "Çekmeyi durdur" ve ardışık hata sınırı korur
      // Anahtar/adres denetimi seçimden SONRA ve yalnız JurisAI'ya aktarırken yapılır (bilgisayara indirme anahtar istemez).
      const begin = await chrome.runtime.sendMessage({ type: "JURISAI_PULL_BEGIN", mode });
      if (!begin?.ok) return { ok: false, error: begin?.error || "Ayarlar eksik" };

      let consecutiveFailures = 0;
      for (let index = 0; index < todo.length && !pulling.stop; index += 1) {
        const item = todo[index];
        toast(`Evrak ${index + 1}/${todo.length} çekiliyor…`);
        await chrome.runtime.sendMessage({ type: "JURISAI_PULL_ARM", evrakId: item.id });
        realClick(item.span);
        let status = {};
        const captured = await waitUntil(async () => {
          status = (await chrome.runtime.sendMessage({ type: "JURISAI_PULL_STATUS" })) || {};
          return status.captured;
        }, 10000);
        // Yalnız önizleme sayfası (viewer.jsp) görüldüyse gerçek belge isteğinin düşmesi için kısa süre tanı.
        if (captured && !status.exact) await sleep(600);
        status = (await chrome.runtime.sendMessage({ type: "JURISAI_PULL_STATUS" })) || status;
        let outcome = {
          ok: false,
          error: `evrak adresi yakalanamadı (${
            status.seen?.length
              ? `tıklamadan sonra sayfa şu istekleri yaptı: ${status.seen.join(", ")}`
              : "tıklamadan sonra sayfa hiç istek yapmadı; ön izleme açık mı?"
          })`,
        };
        if (captured) {
          outcome = await chrome.runtime.sendMessage({
            type: "JURISAI_PULL_FETCH",
            mode,
            meta: {
              evrakAdi: item.title,
              evrakId: item.id,
              evrakTuru: item.typeName || "Evrak",
              dosyaEsasNo: who.esas,
              birim: who.birim,
              klasorYolu: item.folders.join(" / "),
            },
          });
        }
        if (outcome?.ok) {
          consecutiveFailures = 0;
          if (outcome.sameContent) stats.sameContent += 1;
          else if (outcome.duplicate) stats.duplicates += 1;
          else stats.sent += 1; // aktarılan ya da (bilgisayara indirme kipinde) kaydedilen
        } else {
          stats.failed += 1;
          consecutiveFailures += 1;
          if (stats.errors.length < 5) stats.errors.push(outcome?.error || "bilinmeyen hata");
          if (consecutiveFailures >= 3) break; // oturum kapanmış ya da portal yanıt vermiyor olabilir
        }
        await sleep(begin.gapMs || 1500);
      }
      const reasons = [...new Set(stats.errors)].slice(0, 2).join(" | ");
      const summary =
        `${stats.sent} evrak ${toDisk ? "bilgisayara kaydedildi" : "aktarıldı"}` +
        (stats.duplicates ? `, ${stats.duplicates} zaten vardı` : "") +
        (stats.sameContent ? `, ${stats.sameContent} aynı içerik atlandı` : "") +
        (stats.failed ? `, ${stats.failed} hata${reasons ? ` (${reasons})` : ""}` : "") +
        (pulling.stop ? " (durduruldu)" : "");
      toast(summary, stats.failed ? "error" : "success");
      return { ok: true, ...stats, found: items.length, chosen: todo.length, mode, stopped: pulling.stop };
    } finally {
      pulling = null;
      chrome.runtime.sendMessage({ type: "JURISAI_PULL_END" }).catch(() => {});
    }
  }

  /* ---------- Sabit "JurisAI: evrak çek" düğmesi ----------
     Satır düğmeleri sayfa yapısına bağlıdır (gerçek portalda eklenmediler). Bu düğme köşede her zaman durur:
     dosya penceresi açıksa evrak seçim penceresini getirir; değilse listedeki "Dosya Görüntüle" düğmelerini sıralar,
     kullanıcı hangi dosyayı açacağını seçer. Hiçbir şeyi kendiliğinden çekmez. */
  function visibleElement(el) {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }
  function caseOpenTargets() {
    return [...document.querySelectorAll("button, a, input[type='button']")].filter((el) => {
      if (el.closest(".jurisai-launcher, .jurisai-case-picker, .jurisai-chooser")) return false;
      const label = `${el.textContent || ""} ${el.value || ""}`.replace(/\s+/g, " ").trim();
      return label.length < 40 && OPEN_RE.test(label) && visibleElement(el);
    });
  }
  function showCasePicker(targets) {
    document.querySelector(".jurisai-case-picker")?.remove();
    const overlay = document.createElement("div");
    overlay.className = "jurisai-case-picker";
    overlay.setAttribute("role", "dialog");
    overlay.style.cssText =
      "position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,.55);display:flex;align-items:center;" +
      "justify-content:center;font:14px system-ui,sans-serif;";
    const box = document.createElement("div");
    box.style.cssText =
      "background:#fff;color:#111;max-width:640px;width:92vw;max-height:84vh;overflow:auto;border-radius:10px;" +
      "padding:16px 18px;box-shadow:0 10px 40px rgba(0,0,0,.4);";
    const title = document.createElement("div");
    title.style.cssText = "font-weight:700;font-size:16px;margin-bottom:10px;";
    title.textContent = "JurisAI: hangi dosyanın evraklarını çekelim?";
    box.append(title);
    for (const target of targets) {
      const row = target.closest("tr");
      const cells = row ? [...row.querySelectorAll("td")].map((td) => textOf(td)).filter((t) => t && t.length < 90) : [];
      const description = cells.filter((t) => !OPEN_RE.test(t)).slice(0, 4).join(" · ") || "Dosya";
      const item = document.createElement("button");
      item.type = "button";
      item.style.cssText =
        "display:block;width:100%;text-align:left;margin:6px 0;padding:10px 12px;border:1px solid #2563eb;" +
        "background:#fff;color:#111;border-radius:8px;cursor:pointer;";
      item.textContent = description;
      item.addEventListener("click", () => {
        overlay.remove();
        openCaseAndChoose(target);
      });
      box.append(item);
    }
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "İptal";
    cancel.style.cssText = "margin-top:6px;padding:8px 12px;border:1px solid #888;background:#fff;border-radius:8px;cursor:pointer;";
    cancel.addEventListener("click", () => overlay.remove());
    box.append(cancel);
    overlay.append(box);
    document.body.append(overlay);
  }
  function injectLauncher() {
    if (document.querySelector(".jurisai-launcher") || !document.body) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "jurisai-launcher";
    button.textContent = "⚖️ JurisAI: evrak çek";
    button.style.cssText =
      "position:fixed;left:16px;bottom:16px;z-index:2147483000;padding:10px 14px;border:0;border-radius:999px;" +
      "background:#2563eb;color:#fff;font:600 13px system-ui,sans-serif;box-shadow:0 4px 14px rgba(0,0,0,.35);cursor:pointer;";
    button.addEventListener("click", () => {
      if (pulling) return toast("Bir çekme zaten sürüyor.", "info");
      const dialog = activeRoot();
      if (dialog && (previewButton(dialog) || dialog.querySelector("span.file[evrak_id], li.expandable"))) {
        pullDosya().then((result) => {
          if (result && result.ok === false) toast(result.error, "error");
        });
        return;
      }
      const targets = caseOpenTargets();
      if (!targets.length) {
        return toast(
          "Önce \"Dosya Sorgulama\" listesini aç ya da bir dosyayı aç (Dosya Görüntüle → Evrak sekmesi).",
          "info",
        );
      }
      showCasePicker(targets);
    });
    document.body.append(button);
  }

  /** Dosya listesindeki satır düğmesi: dosyayı açar, Evrak sekmesine geçer ve evrak seçim penceresini gösterir. */
  async function openCaseAndChoose(openButton) {
    if (pulling) return toast("Bir çekme zaten sürüyor.", "info");
    toast("Dosya açılıyor…");
    openButton.click();
    if (!(await waitUntil(() => !!activeRoot(), 10000))) return toast("Dosya penceresi açılamadı.", "error");
    await sleep(600);
    const dialog = activeRoot();
    openEvrakTab(dialog);
    const hasTree = await waitUntil(() => !!dialog.querySelector("span.file[evrak_id], li.expandable"), 10000);
    if (!hasTree) {
      return toast("Bu ekranda evrak ağacı yok: evrak satırlarındaki \"JurisAI'ya aktar\" düğmelerini kullan.", "info");
    }
    const result = await pullDosya();
    if (result && result.ok === false) toast(result.error, "error");
  }

  /* ---------- Tıklama kaydı ----------
     "Evrak ağacında bir yaprağa tıklayınca ne oluyor?" sorusunu kullanıcıya tarif ettirmeden yanıtlar:
     belirli bir süre boyunca tıklamaları, sayfanın yaptığı ağ isteklerini (yalnız YOL BİÇİMİ), eklenen
     iframe/embed/dialog öğelerini kaydeder. İndirme ve yeni sekme olaylarını arka plan betiği ekler.
     Hiçbir metin, ad, öznitelik değeri, rakam ya da sorgu değeri kaydedilmez. Bitince rapor
     İndirilenler\NHR-Hukuk-UYAP klasörüne bir JSON dosyası olarak yazılır. */
  const STATIC_RESOURCE_RE = /\.(js|css|png|gif|jpe?g|svg|ico|woff2?|ttf|map)(\?|#|$)/i;
  let recorder = null;

  function srcShape(raw) {
    if (!raw) return "";
    if (/^blob:/i.test(raw)) return "blob:";
    if (/^data:/i.test(raw)) return `data:${(raw.slice(5).split(/[;,]/)[0] || "").slice(0, 40)}`;
    return urlShape(raw);
  }
  function describeTarget(el) {
    const chain = [];
    for (let node = el, i = 0; node && node.nodeType === 1 && i < 5; node = node.parentElement, i += 1) {
      const classes = [...node.classList].slice(0, 3).map(maskClass).join(".");
      chain.push(`${node.tagName.toLowerCase()}${classes ? "." + classes : ""}`);
    }
    const onclick = el.getAttribute("onclick") || "";
    const href = el.getAttribute("href");
    return {
      chain,
      attributeNames: [...el.attributes].map((attr) => attr.name).filter((name) => name !== "class").slice(0, 8),
      onclickFunction: onclick ? onclick.replace(/\(.*$/s, "(…)").slice(0, 40) : "",
      href: href === null ? "" : /^(#|javascript)/i.test(href) ? href.slice(0, 20) : urlShape(href),
    };
  }
  function startRecording(seconds) {
    if (recorder) stopRecording("yeniden başlatıldı");
    const started = performance.now();
    const events = [];
    const push = (event) => {
      if (events.length < 300) events.push({ t: Math.round(performance.now() - started), ...event });
    };
    const listeners = ["click", "dblclick", "contextmenu"].map((type) => {
      const handler = (event) => {
        const target = event.target instanceof Element ? event.target : null;
        if (target && !target.closest(".jurisai-toast, .jurisai-toolbar")) {
          push({ kind: type, target: describeTarget(target) });
        }
      };
      document.addEventListener(type, handler, true);
      return [type, handler];
    });
    let skippedStatic = 0;
    let resources = null;
    try {
      resources = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (STATIC_RESOURCE_RE.test(entry.name)) {
            skippedStatic += 1;
            continue;
          }
          push({
            kind: "resource",
            initiator: entry.initiatorType,
            url: urlShape(entry.name),
            bytes: entry.encodedBodySize || entry.transferSize || 0,
            ms: Math.round(entry.duration),
          });
        }
      });
      resources.observe({ type: "resource" });
    } catch (_) {
      /* PerformanceObserver yoksa yalnız tıklama ve DOM olayları kaydedilir */
    }
    const mutations = new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (!(node instanceof Element)) continue;
          const found = [
            node,
            ...node.querySelectorAll("iframe, embed, object, video, audio, canvas, a[download], [role='dialog'], .modal"),
          ];
          for (const el of found) {
            const interesting =
              /^(iframe|embed|object|video|audio|canvas)$/i.test(el.tagName) ||
              el.hasAttribute("download") ||
              el.matches("[role='dialog'], .modal");
            if (!interesting) continue;
            push({
              kind: "dom_added",
              tag: el.tagName.toLowerCase(),
              classes: [...el.classList].slice(0, 3).map(maskClass),
              src: srcShape(el.getAttribute("src") || el.getAttribute("data") || el.getAttribute("href") || ""),
            });
          }
        }
      }
    });
    mutations.observe(document.documentElement, { childList: true, subtree: true });
    const timer = setTimeout(() => stopRecording("süre doldu"), Math.min(180, Math.max(5, seconds || 60)) * 1000);
    recorder = { started, events, listeners, resources, mutations, timer, skipped: () => skippedStatic };
    chrome.runtime.sendMessage({ type: "JURISAI_RECORD_STARTED" }).catch(() => {});
    toast(`Kayıt başladı (${seconds || 60} sn). Şimdi UYAP'ta bir evrak yaprağına tıkla.`, "info");
  }
  async function stopRecording(reason) {
    const active = recorder;
    if (!active) return { ok: false, error: "kayıt yok" };
    recorder = null;
    clearTimeout(active.timer);
    for (const [type, handler] of active.listeners) document.removeEventListener(type, handler, true);
    active.resources?.disconnect();
    active.mutations.disconnect();
    const report = {
      kind: "tıklama kaydı",
      reason,
      seconds: Math.round((performance.now() - active.started) / 1000),
      skippedStaticResources: active.skipped(),
      events: active.events,
      diagnosisAtEnd: diagnose(),
    };
    try {
      const result = await chrome.runtime.sendMessage({ type: "JURISAI_RECORD_FINISHED", report });
      toast(
        result?.ok
          ? `Kayıt dosyası kaydedildi: İndirilenler\\${result.file.replace("/", "\\")}`
          : `Kayıt kaydedilemedi: ${result?.error || "bilinmeyen hata"}`,
        result?.ok ? "success" : "error",
      );
      return result;
    } catch (error) {
      toast(`Kayıt kaydedilemedi: ${error.message}`, "error");
      return { ok: false, error: error.message };
    }
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    // Kayıt yalnız üst çerçevede tutulur; iç çerçeveler (ön izleme iframe'i vb.) "kayıt yok" yanıtıyla araya girmesin.
    if (/^JURISAI_(RECORD_(START|STOP)|PULL_(DOSYA|STOP))$/.test(message?.type || "") && window !== window.top)
      return false;
    if (message?.type === "JURISAI_PULL_DOSYA") {
      pullDosya(message.mode === "disk" ? "disk" : "upload") // yalnız seçim penceresinde öne çıkan düğme
        .then(sendResponse)
        .catch((error) => sendResponse({ ok: false, error: error.message || "bilinmeyen hata" }));
      return true;
    }
    if (message?.type === "JURISAI_PULL_STOP") {
      if (pulling) pulling.stop = true;
      sendResponse({ ok: true, running: !!pulling });
      return true;
    }
    if (message?.type === "JURISAI_RECORD_START") {
      startRecording(Number(message.seconds) || 60);
      sendResponse({ ok: true });
      return true;
    }
    if (message?.type === "JURISAI_RECORD_STOP") {
      stopRecording("elle bitirildi").then(sendResponse);
      return true;
    }
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

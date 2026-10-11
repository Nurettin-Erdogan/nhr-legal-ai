/* JurisAI - UYAP Avukat Portalı içerik betiği
   Evrak tablosunu bulur, her satıra "JurisAI'ya Aktar" düğmesi enjekte eder,
   toplu aktarım için listenin üstüne bir araç çubuğu ekler.
   Kullanıcının kendi UYAP oturumu kullanılır; şifre/e-imza asla okunmaz.

   Otomatik aktarım (dosya açılınca evrakları kendiliğinden gönderme) yalnızca kullanıcı ayar
   penceresinde açıkça açtıysa çalışır; varsayılan KAPALIDIR. Kapalıyken yalnızca düğmeye basılan
   evrak gönderilir. */

(() => {
  // Yeniden yükleme sonrası aynı sekmeye betik yeniden yerleştirilir: eski sürümün (ölü) arayüz parçaları kaldırılır,
  // yoksa ölü bir düğmeye basılınca "Extension context invalidated" hatası çıkardı. Aynı sürüm iki kez çalışmaz.
  const loadedVersion = chrome.runtime.getManifest().version;
  if (window.__jurisaiLoadedVersion === loadedVersion) return;
  window.__jurisaiLoadedVersion = loadedVersion;
  for (const stale of document.querySelectorAll(
    ".jurisai-launcher, .jurisai-toolbar, .jurisai-toasts, .jurisai-chooser, .jurisai-case-picker, .jurisai-send-btn",
  )) {
    stale.remove();
  }
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

  // Sayfa gizliyken (kullanıcı JurisAI sekmesindeyken) Chrome zincirleme zamanlayıcıları dakikada bire kadar seyreltebilir; o zaman
  // bekleme arka plan betiğine yaptırılır (mesaj yanıtı bu kısıta girmez). JurisAI'dan yönetilen aktarım arka planda yavaşlamaz.
  const timerSleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const sleep = (ms) => {
    if (!document.hidden) return timerSleep(ms);
    try {
      return chrome.runtime.sendMessage({ type: "JURISAI_SLEEP", ms }).then(
        () => undefined,
        () => timerSleep(ms),
      );
    } catch (_) {
      return timerSleep(ms); // eklenti yeniden yüklendiyse (yetim betik)
    }
  };

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
  function evrakTabOf(scope) {
    // Bootstrap sekme olayı bağlantıda dinlenir; onu saran li'ye tıklamak
    // bağlantının olayını tetiklemez ve gizli/eski evrak ağacını bırakabilir.
    const candidates = [...scope.querySelectorAll("a, button, [role='tab']")];
    return candidates.find((el) => {
      const text = textOf(el).toLocaleLowerCase("tr");
      if (!["evrak", "evraklar", "evrak bilgileri"].includes(text)) return false; // "Evrak Gönderme" sekmesine basma
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
  }
  function openEvrakTab(scope = document, force = false) {
    const tab = evrakTabOf(scope);
    if (!tab) return false;
    const pane = detailPane(scope, detailPaneId(tab));
    const active =
      tab.classList.contains("active") ||
      tab.parentElement?.classList.contains("active") ||
      tab.getAttribute("aria-selected") === "true";
    // Eski active sınıfı görünür/yüklenmiş içerik değildir; kapalı pane yeniden etkinleştirilmelidir.
    if (force || !active || (pane && !detailPaneShown(pane, scope))) tab.click();
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
  // Yol parçaları kişi/dosya adı da olabilir; tanıya yalnız yolun biçimi girer.
  const mask = (value) => String(value).split("/").map((part) => part ? ":segment" : "").join("/").slice(0, 80);
  function urlShape(raw) {
    try {
      const url = new URL(raw, location.href);
      return `${url.hostname === location.hostname ? "(aynı kaynak) " : "(dış kaynak) "}${mask(url.pathname)}${url.search ? "?param" : ""}`;
    } catch (_) {
      return "(çözümlenemedi)";
    }
  }
  /* Yapı iskeleti: etiket + sınıf + öznitelik ADLARI ve sayıları. Metin ve öznitelik DEĞERİ yok. */
  const maskClass = () => ":class";
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
        hasOnclick: !!onclick,
        href: href === null ? "" : /^(#|javascript)/i.test(href) ? "(yerel)" : urlShape(href),
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
      host: "(UYAP)",
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
      refreshFailed: !!lastRefreshError,
      launcher: !!document.querySelector(".jurisai-launcher"),
      caseOpenTargets: caseOpenTargets().length,
      buttonCount: scope.querySelectorAll("button, input[type='button'], a.btn").length,
      tabCount: scope.querySelectorAll("[role='tab'], .nav-tabs a, .nav-tabs li, ul.nav li").length,
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
  const sameText = (a, b) =>
    trLower(String(a || "").replace(/\s+/g, " ").trim()) === trLower(String(b || "").replace(/\s+/g, " ").trim());
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
  /** Ağaç boyutu (düğüm sayısı) art arda birkaç yoklamada değişmeyene dek bekler: alt düğümler AJAX ile geç gelir. */
  async function waitForTreeToSettle(dialog, maxMs = 20000) {
    const end = Date.now() + maxMs;
    let last = -1;
    let stable = 0;
    while (Date.now() < end && stable < 4) {
      const size = dialog.querySelectorAll("span.file, span.folder, li").length;
      stable = size === last ? stable + 1 : 0;
      last = size;
      await sleep(500);
    }
  }
  async function expandAll(dialog) {
    // Açma + durulma birkaç tur tekrarlanır: açılan düğümler yeni kapalı düğümler getirebilir. İlerleme yoksa (kapalı
    // düğüm sayısı azalmıyorsa) ya da süre dolarsa vazgeçilir: açılamayan düğümler için sonsuza dek beklenmez.
    const deadline = Date.now() + 90000;
    let previous = Infinity;
    let stalls = 0;
    for (let round = 0; round < 8 && Date.now() < deadline; round += 1) {
      await expandPass(dialog);
      await waitForTreeToSettle(dialog, 8000);
      const remaining = dialog.querySelectorAll("li.expandable").length;
      if (!remaining) return;
      stalls = remaining >= previous ? stalls + 1 : 0; // yeni açılan düğümler yeni kapalılar getirebilir: tek duraksamada bırakma
      if (stalls >= 2) return;
      previous = remaining;
    }
  }
  async function expandPass(dialog) {
    const attempts = new Map();
    for (let pass = 0; pass < 20; pass += 1) {
      const closed = [...dialog.querySelectorAll("li.expandable")].filter((li) => (attempts.get(li) || 0) < 5);
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
  const RECENT_RE = /^Dosyaya Eklenen Son/i;
  /** UYAP'ın klasör adının yanına yazdığı sayı ("Kesinleşme Şerhleri (2)") ile klasörün doğrudan altındaki evrak sayısı. */
  function folderStats(dialog) {
    const stats = [];
    for (const li of dialog.querySelectorAll("li")) {
      const label = li.querySelector(":scope > span.folder");
      if (!label) continue;
      const declared = Number((/\((\d+)\)\s*$/.exec(textOf(label)) || [])[1]) || null;
      if (!declared) continue;
      let recent = false; // "Son 20 Evrak" kısayolu sayılmaz
      for (let up = li.parentElement?.closest("li"); up && !recent; up = up.parentElement?.closest("li")) {
        const upLabel = up.querySelector(":scope > span.folder, :scope > span.file");
        recent = !!upLabel && RECENT_RE.test(textOf(upLabel));
      }
      if (recent) continue;
      const leaves = li.querySelectorAll(":scope > ul > li > span.file[evrak_id]:not([ana_evrak_id])").length;
      stats.push({ li, name: folderName(textOf(label)), declared, leaves });
    }
    return stats;
  }
  const leafCount = (li) => li.querySelectorAll(":scope > ul > li > span.file[evrak_id]:not([ana_evrak_id])").length;
  /** Açık görünüp altında hiçbir şey olmayan düğümler: ek listesi ya da klasör içeriği yüklenememiş (UYAP'ın sayısı olmasa da eksiktir). */
  const emptyOpenedNodes = (dialog) =>
    [...dialog.querySelectorAll("li.collapsable")].filter((li) => li.querySelector(":scope > ul") && !li.querySelector(":scope > ul > li"));
  /**
   * Eksik yüklenen düğümler için: önce biraz bekle (yavaş yükleniyor olabilir), sonra düğümü kapatıp yeniden aç (alt düğümleri
   * yeniden yüklemeyi tetikler). Eksik = UYAP'ın yazdığından az evrak görünen klasör ya da açık ama boş düğüm. Canlıda sayı her
   * açılışta değişiyordu (463 → 456 → 449 → 445; ek sayısı 367 → 350): UYAP art arda isteklerde ek listelerini yüklemeyebiliyor.
   */
  async function repairTree(dialog, onGaps) {
    const deadline = Date.now() + 120000;
    for (let round = 0; round < 4 && Date.now() < deadline; round += 1) {
      const gaps = folderStats(dialog).filter((entry) => entry.leaves < entry.declared);
      const gapNodes = new Set(gaps.map((entry) => entry.li));
      const empty = emptyOpenedNodes(dialog).filter((li) => !gapNodes.has(li));
      if (!gaps.length && !empty.length) return;
      onGaps?.(gaps.length + empty.length, round);
      if (round === 0) {
        await waitForTreeToSettle(dialog, 6000);
        continue;
      }
      const targets = [
        ...gaps.map((entry) => ({ li: entry.li, done: () => leafCount(entry.li) >= entry.declared })),
        ...empty.map((li) => ({ li, done: () => !!li.querySelector(":scope > ul > li") })),
      ];
      for (const target of targets) {
        const handle = target.li.querySelector(":scope > div.hitarea") || target.li.querySelector(":scope > span.folder, :scope > span.file");
        if (!handle) continue;
        if (target.li.classList.contains("collapsable")) {
          handle.click(); // açıksa önce kapat
          await sleep(300);
        }
        handle.click();
        await waitUntil(target.done, 1000 * round, 200);
        await sleep(250); // UYAP'ı art arda isteklerle boğma
      }
      await expandAll(dialog);
    }
  }
  /**
   * Evrağın ön izleme adresini tıklamadan kurar. Gerçek portalda ölçüldü (2026-10-05): UYAP'ın kendi menüsü
   * (Görüntüle/Kaydet) yaprağın `evrak_id` özniteliğini, dosya penceresinin satır içi betiğindeki `dosyaId` ve yargı türüyle
   * `view_document*_brd.uyap` / `download_document*_brd.uyap` adresine gönderir (Application.convertObjectToURLParameters:
   * baştaki/sondaki tırnak atılır, değer URL kodlanır). Bilgiler bulunamazsa boş döner; tahmin yapılmaz.
   */
  function directViewUrl(span) {
    try {
      const evrak = span.getAttribute("evrak_id");
      const scripts = [...document.scripts].filter((s) => !s.src && s.textContent.includes("evrakSolClickMenu"));
      const text = scripts.length ? scripts[scripts.length - 1].textContent : "";
      const dosya = (/var dosyaId='([^']+)'/.exec(text) || [])[1];
      const yargi = (/\.contextMenu2?\('([^']+)'/.exec(text) || [])[1];
      if (!evrak || !dosya || !yargi) return "";
      const clean = (value) => {
        let v = String(value).replace(/^['"]|['"]$/g, "");
        if (v.includes("%")) {
          try {
            v = decodeURIComponent(v);
          } catch (_) {
            /* olduğu gibi */
          }
        }
        return encodeURIComponent(v);
      };
      const suffix = yargi === "2" ? "_danistay" : yargi === "3" ? "_yargitay" : "";
      return `${location.origin}/main/jsp/view_document${suffix}_brd.uyap?mimeType=&evrakId=${clean(evrak)}&dosyaId=${clean(dosya)}&yargiTuru=${clean(yargi)}`;
    } catch (_) {
      return "";
    }
  }
  /** Gerçek bir fare tıklaması gibi: üzerine gelme, basma, bırakma, tıklama (UYAP üzerine-gelme sınıfını da kullanıyor). */
  function realClick(element) {
    element.scrollIntoView({ block: "center" });
    for (const type of ["mouseover", "mousedown", "mouseup", "click"]) {
      element.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window, button: 0 }));
    }
  }
  /** Evrak balonundaki (data-original-title ya da title) "Birim Evrak No": UYAP her sayfa yüklemesinde `evrak_id`'yi yeniden şifreler, bu numara değişmez. */
  const evrakNoOf = (span) =>
    (/Birim Evrak No\s*:?\s*(\d+)/i.exec(String(span.getAttribute("data-original-title") || span.getAttribute("title") || "").replace(/<[^>]+>/g, " ")) || [])[1] || "";
  /** Kısa, deterministik özet (3 × 32 bit karıştırma, ~96 bit): kimliği eşzamanlı ve bellekte üretmek için; güvenlik amacı yoktur. */
  function shortFingerprint(value) {
    let h1 = 0xdeadbeef;
    let h2 = 0x41c6ce57;
    let h3 = 0x9e3779b9;
    for (let i = 0; i < value.length; i += 1) {
      const code = value.charCodeAt(i);
      h1 = Math.imul(h1 ^ code, 2654435761);
      h2 = Math.imul(h2 ^ code, 1597334677);
      h3 = Math.imul(h3 ^ code, 2246822519);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h3 ^ (h3 >>> 13), 3266489909);
    h3 = Math.imul(h3 ^ (h3 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return [h1, h2, h3].map((h) => (h >>> 0).toString(16).padStart(8, "0")).join("");
  }
  const tooltipOf = (span) =>
    String(span.getAttribute("data-original-title") || span.getAttribute("title") || "")
      .replace(/<[^>]+>/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  /**
   * Evrağın KALICI kimliği (yüklemeler ve OTURUMLAR arasında değişmez; "zaten aktarıldı" denetimi ve yinelenen elemesi buna dayanır):
   *  - ek: üst evrakın düz `ana_evrak_id`si + "Ek N" başlığı;
   *  - evrak: balondaki "Birim Evrak No";
   *  - "Birim Evrak No"su BOŞ olan evrak (ör. Kapalı E-Tebliğ Mazbatası; canlıda ölçüldü 2026-10-06): balondaki öteki alanların (onay/gönderim
   *    tarihi, kişi, gönderen dosya no/sayı, açıklama, tür, tip) ve başlığın özeti. Birebir aynı iki evrak olabilir; sıra numarası
   *    `collectEvraklar`da eklenir.
   * Dosyanın birimi de eklenir (başka mahkemede aynı numara olabilir). Bunların hiçbiri yoksa şifreli `evrak_id` son çaredir; o
   * HER OTURUMDA değişir, bu yüzden `unstable` işaretlenir ve ağaç "eksiksiz" doğrulanamaz.
   * @returns {{ id: string, kind: "ek" | "no" | "weak" | "raw" }}
   */
  function stableEvrakId(span, birim) {
    const title = textOf(span);
    if (span.hasAttribute("ana_evrak_id")) return { id: `ek:${span.getAttribute("ana_evrak_id")}:${title}@${birim}`, kind: "ek" };
    const no = evrakNoOf(span);
    if (no) return { id: `ev:${no}@${birim}`, kind: "no" };
    const tip = tooltipOf(span);
    if (tip) return { id: `nn:${shortFingerprint(`${tip}\u0001${title}`)}`, kind: "weak" };
    return { id: span.getAttribute("evrak_id"), kind: "raw" };
  }
  /** Ağaçtaki evrakları klasör yoluyla listeler; "Son 20 Evrak" kısayolu ve aynı evrakın tekrarları (kalıcı kimliğe göre) elenir. */
  function collectEvraklar(dialog) {
    const byId = new Map();
    const { birim } = dosyaIdentity(dialog);
    let duplicates = 0; // aynı evrakın "Tüm Evraklar" altında birden çok klasörde görünmesi
    const weakOrdinals = new Map(); // numarasız evrakta birebir aynı özet: ağaç sırasıyla 0, 1, ...
    for (const span of dialog.querySelectorAll("span.file[evrak_id]")) {
      const rawId = span.getAttribute("evrak_id");
      if (!rawId) continue;
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
      const identity = stableEvrakId(span, birim);
      let id = identity.id;
      if (identity.kind === "weak") {
        // Birebir aynı özetli iki evrak (aynı gün aynı kişiye iki mazbata) tek sayılmasın: ağaç sırasına göre numaralanır. "Son 20"
        // kısayol kopyaları ayrı sayılır; asıl ağaç varken zaten elenir ve aynı sıra numarasını alarak asıl evrakla birleşir.
        const bucket = `${inRecent ? "r" : "f"}|${id}`;
        const ordinal = weakOrdinals.get(bucket) || 0;
        weakOrdinals.set(bucket, ordinal + 1);
        id = `${id}#${ordinal}@${birim}`;
      }
      const folders = chain
        .slice(1) // ilk öğe dosyanın kendisi (mahkeme + esas no); klasör yolu onun altından başlar
        .filter((label) => !/^Tüm Evraklar$/i.test(label) && !/^Dosyaya Eklenen Son/i.test(label))
        .map(folderName);
      const isEk = span.hasAttribute("ana_evrak_id");
      // Ekin türü "Ek"; diğerlerinde en yakın klasör adı (bağlı olduğu evrakın başlığı değil).
      const typeName = isEk
        ? "Ek"
        : folderName(folderLabels.filter((l) => !/^Tüm Evraklar$/i.test(l) && !/^Dosyaya Eklenen Son/i.test(l)).pop() || "Evrak");
      // UYAP klasör adının yanına kendi sayısını yazar ("Kesinleşme Şerhleri (2)"): bulduğumuz sayıyla karşılaştırmak için.
      const nearest = folderLabels.filter((l) => !/^Tüm Evraklar$/i.test(l) && !/^Dosyaya Eklenen Son/i.test(l)).pop() || "";
      const declared = isEk ? null : Number((/\((\d+)\)\s*$/.exec(nearest) || [])[1]) || null;
      const entry = { id, rawId, span, title: textOf(span), folders, typeName, inRecent, isEk, declared, unstable: identity.kind === "raw" };
      const existing = byId.get(id);
      if (existing && !existing.inRecent && !inRecent) duplicates += 1;
      if (!existing || (existing.inRecent && !inRecent)) byId.set(id, entry);
    }
    const withoutId = dialog.querySelectorAll("span.file:not([evrak_id])").length;
    const all = [...byId.values()];
    // "Dosyaya Eklenen Son 20 Evrak", "Tüm Evraklar"daki evrakların kısayol kopyasıdır (gerçek portalda kopyalar
    // farklı evrak_id taşıdığı için 4 evrak 8 görünmüştü): "Tüm Evraklar" varsa yalnız o kullanılır.
    const full = all.filter((entry) => !entry.inRecent);
    const result = full.length ? full : all;
    result.withoutId = withoutId; // evrak_id'si olmayan öğeler çekilemez; sayısı seçim penceresinde gösterilir
    result.unstableId = result.filter((entry) => entry.unstable).length;
    result.duplicates = duplicates;
    result.folderStats = folderStats(dialog);
    result.unopened = [...dialog.querySelectorAll("li.expandable")].filter((li) => li.querySelector(":scope > ul")).length;
    result.domLeaves = dialog.querySelectorAll("span.file[evrak_id]").length;
    result.emptyOpened = emptyOpenedNodes(dialog).length;
    return result;
  }
  function dosyaIdentity(dialog) {
    const title = textOf(dialog.querySelector(".modal-title") || dialog.querySelector("h1,h2,h3,h4"));
    return { esas: esasNoFrom(title), birim: (title.split(" - ")[1] || courtFrom(title) || "").trim().slice(0, 160) };
  }

  /** UYAP'ın klasör sayılarıyla bulunan evrakların karşılaştırması (seçim penceresi ve JurisAI sayfası aynı hesabı kullanır). */
  function countSummary(items) {
    const groups = new Map();
    for (const item of items) {
      const key = item.folders.join(" / ") || "(klasörsüz)";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    }
    const countedGroups = [...groups.values()].filter((group) => group[0].declared !== null);
    const folderStats = items.folderStats || [];
    // UYAP'ın sayısı ağaçtaki TÜM sayılı klasörlerden alınır: hiç evrak bulunamayan klasör de toplama girer.
    const declaredTotal = folderStats.length
      ? folderStats.reduce((sum, entry) => sum + entry.declared, 0)
      : countedGroups.reduce((sum, group) => sum + group[0].declared, 0);
    const gapList = folderStats.length
      ? folderStats.filter((entry) => entry.leaves !== entry.declared).map((entry) => `${entry.name} (UYAP ${entry.declared}, bulunan ${entry.leaves})`)
      : countedGroups
          .filter((group) => group[0].declared !== group.length)
          .map((group) => `${group[0].folders[group[0].folders.length - 1]} (UYAP ${group[0].declared}, bulunan ${group.length})`);
    const foundTotal = countedGroups.reduce((sum, group) => sum + group.length, 0);
    const copies = items.duplicates || 0;
    const matches = declaredTotal === foundTotal;
    // Fark açıklanmış sayılır: hiçbir klasörde eksik yok (her klasörün DOM'daki evrak sayısı UYAP'ınkine eşit), yani fark
    // yalnız aynı evrakın birden çok klasörde görünmesinden. (Ek kopyaları da "copies"e girdiği için eşitlik aramak yanıltır.)
    const explained = !matches && (declaredTotal === foundTotal + copies || (folderStats.length > 0 && gapList.length === 0));
    return {
      declaredTotal,
      foundTotal,
      eks: items.filter((item) => item.isEk).length,
      copies,
      matches,
      explained,
      gapList,
      withoutId: items.withoutId || 0,
      unstableId: items.unstableId || 0,
      unopened: items.unopened || 0,
      domLeaves: items.domLeaves ?? null,
      emptyOpened: items.emptyOpened || 0,
    };
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
      // Toplam doğrulama: UYAP'ın klasör sayıları (evraklar, ekler hariç) ile bulunanlar.
      const { declaredTotal, foundTotal, eks, matches, explained, gapList } = countSummary(items);
      const verification = make(
        "div",
        `font-size:12px;margin-top:6px;color:${matches || explained ? "#166534" : "#b91c1c"};`,
        `UYAP klasör sayıları: ${declaredTotal} evrak · bulunan: ${foundTotal}${eks ? ` · ayrıca ${eks} ek` : ""}` +
          (items.withoutId ? ` · kimliksiz öğe: ${items.withoutId} (çekilemez)` : "") +
          (items.unopened ? ` · açılamayan klasör: ${items.unopened}` : "") +
          (matches
            ? " ✓ sayılar tutuyor"
            : explained
              ? ` ✓ fark ${declaredTotal - foundTotal} evrağın iki klasörde birden görünmesinden (tek kez çekilir)`
              : " ⚠ sayılar tutmuyor") +
          // Hangi klasörlerde fark var (en çok 4): sayıyı doğrulamak/düzeltmek için.
          (matches || explained
            ? ""
            : ` — fark: ${gapList.slice(0, 4).join("; ")}${gapList.length > 4 ? ` (+${gapList.length - 4} klasör daha)` : ""}`),
      );
      head.append(verification);
      head.append(
        make(
          "div",
          "font-size:11px;color:#6b7280;margin-top:2px;",
          `ağaç: ${items.domLeaves ?? "?"} yaprak, ${items.length} benzersiz evrak/ek` +
            (items.emptyOpened ? ` · yüklenemeyen açık düğüm: ${items.emptyOpened}` : ""),
        ),
      );
      const rescanButton = make(
        "button",
        "margin-top:6px;padding:4px 10px;border-radius:8px;border:1px solid #b91c1c;background:#fff;color:#b91c1c;cursor:pointer;font-size:12px;",
        "⟳ Ağacı yeniden tara",
      );
      rescanButton.id = "jurisai-pick-rescan";
      rescanButton.type = "button";
      if (!matches && !explained) head.append(rescanButton);
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
        const declared = group[0].declared;
        const mismatch = declared !== null && declared !== group.length;
        heading.append(
          groupInput,
          make("span", "", `📁 ${label}`),
          ...(declared !== null
            ? [make("span", `font-weight:400;font-size:12px;color:${mismatch ? "#b91c1c" : "#555"};`, `${mismatch ? "⚠ " : ""}UYAP: ${declared}, bulunan: ${group.length}`)]
            : []),
        );
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
      const mainCount = items.filter((entry) => !entry.isEk).length;
      const mainOnly = make("button", "padding:4px 8px;border:0;background:none;color:#2563eb;cursor:pointer;", `Yalnızca asıl evraklar (${mainCount})`);
      mainOnly.id = "jurisai-pick-main";
      mainOnly.type = "button";
      mainOnly.title = "Ekleri (Ek 1, Ek 2…) işaretlemeyi kaldırır: çok daha hızlı biter, ekler sonra ayrıca çekilebilir";
      mainOnly.addEventListener("click", () => {
        for (const entry of boxes) entry.input.checked = !entry.item.isEk;
        refresh();
      });
      const finish = (action) => {
        overlay.remove();
        resolve({ action, selected: boxes.filter((entry) => entry.input.checked).map((entry) => entry.item) });
      };
      diskButton.addEventListener("click", () => finish("disk"));
      uploadButton.addEventListener("click", () => finish("upload"));
      cancelButton.addEventListener("click", () => finish(null));
      rescanButton.addEventListener("click", () => finish("rescan"));
      buttons.append(counter, toggle, ...(mainCount && mainCount < items.length ? [mainOnly] : []), make("span", "flex:1"), diskButton, uploadButton, cancelButton);
      box.append(head, list, note, buttons);
      overlay.append(box);
      document.body.append(overlay);
      refresh();
    });
  }

  /** Ağacı açar, eksik yüklenen düğümleri onarır ve evrakları toplar. */
  async function prepareTree(dialog, onGaps) {
    if (!(await ensurePreview(dialog))) return { ok: false, error: "Ön izleme düğmesi bulunamadı (Evrak sekmesinde misin?)" };
    await expandAll(dialog);
    await repairTree(dialog, onGaps);
    const items = collectEvraklar(dialog);
    if (!items.length) return { ok: false, error: "Ağaçta evrak bulunamadı. Evrak sekmesini aç ve tekrar dene." };
    return { ok: true, items };
  }

  // Başarıda aralık, işlem BİTTİKTEN sonra yeniden eklenmez: yakalama/indirme/yükleme
  // süresi de iki evrağın başlangıçları arasındaki güvenli aralığın parçasıdır. Hata
  // geri çekilmesi tam beklenir; eşzamanlı UYAP isteği başlatılmaz.
  function pullPauseMs(gap, baseGap, usedDirect, succeeded, elapsedMs, hasNext) {
    if (!hasNext) return 0;
    if (!succeeded || gap !== baseGap) return gap;
    const interval = usedDirect ? Math.min(gap, 500) : gap;
    return Math.max(0, interval - Math.max(0, elapsedMs));
  }

  function pullItemOnlyError(outcome) {
    // İndirme kesintisi ve doğrulama reddi, iç içe hata mesajında önizleme
    // reddinden söz edilse bile kalıcı evrak hatası değildir.
    if (outcome?.retryable || outcome?.code === "UYAP_VALIDATION_FAILED") return false;
    return /Desteklenmeyen dosya türü|önizlemede vermiyor|çok büyük|sınırını aşıyor|zaten/i.test(outcome?.error || "");
  }

  /**
   * Seçilen evrakları sırayla çeker: tıkla → UYAP'ın önizleme isteğini yakala → indir → JurisAI'ya yükle ya da diske kaydet.
   * `progress` verilirse her adımda güncellenir (JurisAI sayfası oradan izler). `pulling`i çağıran kurar ve kaldırır.
   */
  async function runPull(selected, mode, who, { progress = null, jobId = "" } = {}) {
    const toDisk = mode === "disk";
    const stats = { sent: 0, duplicates: 0, sameContent: 0, failed: 0, known: 0, errors: [] };
    const spent = { clicks: 0, items: 0, capture: 0, download: 0, upload: 0, pause: 0 }; // ms; özet satırında ortalama gösterilir
    const report = (patch = {}) => {
      if (progress) Object.assign(progress, patch, { stats: { ...stats, errors: [...stats.errors] } });
    };
    // Anahtar/adres denetimi seçimden SONRA ve yalnız JurisAI'ya aktarırken yapılır (bilgisayara indirme anahtar istemez).
    const begin = await chrome.runtime.sendMessage({ type: "JURISAI_PULL_BEGIN", mode, jobId });
    if (!begin?.ok) return { ok: false, error: begin?.error || "Ayarlar eksik" };
    if (pulling.stop) await chrome.runtime.sendMessage({ type: "JURISAI_PULL_CANCEL", jobId });
    let todo = selected; // evrak sayısı sınırı yok: hız (evrak başına birkaç sn), "Çekmeyi durdur" ve ardışık hata sınırı korur
    if (!toDisk && !pulling.stop) {
      // JurisAI'da zaten olan evraklara hiç tıklanmaz: yarıda kalan çekme sürdürülür, yeniden deneme hızlanır.
      toast("Daha önce aktarılanlar kontrol ediliyor…");
      report({ phase: "Daha önce aktarılanlar kontrol ediliyor" });
      const answer = await chrome.runtime
        .sendMessage({ type: "JURISAI_PULL_KNOWN", ids: todo.map((item) => item.id), esas: who.esas, birim: who.birim })
        .catch(() => null);
      if (answer?.ok && answer.known.length) {
        const have = new Set(answer.known);
        stats.known = todo.filter((item) => have.has(item.id)).length;
        todo = todo.filter((item) => !have.has(item.id));
      }
    }
    report({ phase: "Aktarılıyor", total: todo.length, done: 0, current: "" });
    let consecutiveFailures = 0;
    const baseGap = begin.gapMs || 1500;
    let gap = baseGap; // hata görülürse iki katına çıkar (en çok 20 sn), başarıda yavaşça normale döner
    for (let index = 0; index < todo.length && !pulling.stop; index += 1) {
      const itemStartedAt = performance.now();
      const item = todo[index];
      toast(`Evrak ${index + 1}/${todo.length} çekiliyor…`);
      report({ done: index, current: item.title });
      const meta = {
        evrakAdi: item.title,
        evrakId: item.id,
        evrakTuru: item.typeName || "Evrak",
        dosyaEsasNo: who.esas,
        birim: who.birim,
        klasorYolu: item.folders.join(" / "),
      };
      await chrome.runtime.sendMessage({ type: "JURISAI_PULL_ARM", evrakId: item.id });
      if (pulling.stop) break;
      // Hızlı yol: evrağın adresi sayfanın kendi bilgilerinden kurulur, tıklama ve ön izlemenin yüklenmesi beklenmez
      // (canlıda evrak başına ~2,2 sn yakalama + 1,5 sn bekleme → ~0,5 sn). Adres kurulamaz ya da belge gelmezse tıklama yoluna dönülür.
      const direct = directViewUrl(item.span);
      let outcome = null;
      let usedDirect = false;
      if (direct) {
        outcome = await chrome.runtime.sendMessage({ type: "JURISAI_PULL_FETCH", mode, direct, meta });
        usedDirect = !!outcome?.ok || pullItemOnlyError(outcome);
      }
      if (outcome?.code === "UYAP_CANCELLED") { pulling.stop = true; break; }
      if (!usedDirect && pulling.stop) break;
      if (!usedDirect) {
        await chrome.runtime.sendMessage({ type: "JURISAI_PULL_ARM", evrakId: item.id });
        if (pulling.stop) break;
        const clickedAt = Date.now();
        realClick(item.span);
        let status = {};
        const captured = await waitUntil(async () => {
          status = (await chrome.runtime.sendMessage({ type: "JURISAI_PULL_STATUS" })) || {};
          return pulling.stop || status.captured;
        }, 10000);
        if (pulling.stop) break;
        // Yalnız önizleme sayfası (viewer.jsp) görüldüyse gerçek belge isteğinin düşmesi için kısa süre tanı.
        if (captured && !status.exact) await sleep(600);
        status = (await chrome.runtime.sendMessage({ type: "JURISAI_PULL_STATUS" })) || status;
        spent.capture += Date.now() - clickedAt;
        spent.clicks += 1;
        const directError = outcome?.error;
        outcome = {
          ...outcome,
          ok: false,
          error:
            directError ||
            `evrak adresi yakalanamadı (${
              status.seen?.length
                ? `tıklamadan sonra sayfa şu istekleri yaptı: ${status.seen.join(", ")}`
                : "tıklamadan sonra sayfa hiç istek yapmadı; ön izleme açık mı?"
            })`,
        };
        if (captured) outcome = await chrome.runtime.sendMessage({ type: "JURISAI_PULL_FETCH", mode, meta });
      }
      // Kullanıcı iptali evrak/oturum hatası değildir; yeniden deneme ve hata sayacı yok.
      if (outcome?.code === "UYAP_CANCELLED") { pulling.stop = true; break; }
      if (outcome?.ms) {
        spent.items += 1;
        spent.download += outcome.ms.download || 0;
        spent.upload += outcome.ms.upload || 0;
      }
      if (outcome?.ok) {
        consecutiveFailures = 0;
        gap = Math.max(baseGap, Math.round(gap * 0.8));
        if (outcome.sameContent) stats.sameContent += 1;
        else if (outcome.duplicate) stats.duplicates += 1;
        else stats.sent += 1; // aktarılan ya da (bilgisayara indirme kipinde) kaydedilen
      } else {
        stats.failed += 1;
        // Evrağın kendisine özgü ret (tür desteklenmiyor, UYAP ön izlemede vermiyor) oturum/portal sorunu değildir: art arda gelse de
        // aktarım durdurulmaz ve yavaşlatılmaz. Canlıda art arda 5 .zip eki 350 evraklık aktarımı 114. evrakta kesmişti.
        const itemOnly = pullItemOnlyError(outcome);
        if (!itemOnly) consecutiveFailures += 1;
        if (stats.errors.length < 5) stats.errors.push(`${item.title.slice(0, 90)}: ${outcome?.error || "bilinmeyen hata"}`);
        if (!itemOnly) gap = Math.min(20000, gap * 2); // UYAP bizi sınırlıyor olabilir: yavaşla
      }
      report({ done: index + 1 });
      if (consecutiveFailures >= 5) break; // oturum kapanmış ya da portal yanıt vermiyor olabilir
      // Tıklamasız yolda sayfa ön izleme yüklemez (evrak başına tek istek): hata yokken kısa bekleme yeter; hata görülünce `gap` büyür.
      const pause = pullPauseMs(gap, baseGap, usedDirect, !!outcome?.ok, performance.now() - itemStartedAt,
        index + 1 < todo.length && !pulling.stop);
      spent.pause += pause;
      if (pause > 0) await chrome.runtime.sendMessage({ type: "JURISAI_PULL_WAIT", ms: pause, jobId });
    }
    const timing = spent.items
      ? {
          items: spent.items,
          capture: Math.round(spent.capture / Math.max(1, spent.clicks)),
          download: Math.round(spent.download / spent.items),
          upload: Math.round(spent.upload / spent.items),
          pause: Math.round(spent.pause / Math.max(1, todo.length)),
        }
      : null;
    const reasons = [...new Set(stats.errors)].slice(0, 2).join(" | ");
    const summary =
      `${stats.sent} evrak ${toDisk ? "bilgisayara kaydedildi" : "aktarıldı"}` +
      (stats.known ? `, ${stats.known} daha önce aktarılmıştı (tıklanmadı)` : "") +
      (stats.duplicates ? `, ${stats.duplicates} zaten vardı` : "") +
      (stats.sameContent ? `, ${stats.sameContent} aynı içerik atlandı` : "") +
      (stats.failed ? `, ${stats.failed} hata${reasons ? ` (${reasons})` : ""}` : "") +
      (pulling.stop ? " (durduruldu)" : "") +
      (timing
        ? ` · evrak başına ort.: yakalama ${(timing.capture / 1000).toFixed(1)} sn, indirme ${(timing.download / 1000).toFixed(1)} sn, ` +
          `${toDisk ? "kayıt" : "yükleme"} ${(timing.upload / 1000).toFixed(1)} sn, bekleme ${(timing.pause / 1000).toFixed(1)} sn`
        : "");
    toast(summary, stats.failed ? "error" : "success");
    report({ phase: pulling.stop ? "Durduruldu" : "Bitti", current: "" });
    return { ok: true, ...stats, chosen: todo.length, mode, stopped: pulling.stop, timing, summary };
  }

  async function pullDosya(preferred = "upload") {
    if (recoveryBusy()) return { ok: false, code: "busy", error: "UYAP sayfası toparlanıyor; bitince tekrar dene." };
    if (pulling) return { ok: false, error: "Çekme zaten sürüyor" };
    const dialog = activeRoot();
    if (!dialog) return { ok: false, error: "Açık bir dosya penceresi yok: UYAP'ta dosyayı aç, Evrak sekmesine geç." };
    pulling = { stop: false };
    try {
      toast("Evrak ağacı açılıyor…");
      const who = dosyaIdentity(dialog);
      let items;
      let choice;
      for (;;) {
        const prepared = await prepareTree(dialog, (gaps) => toast(`${gaps} klasörde evrak eksik görünüyor, yeniden yükleniyor…`));
        if (!prepared.ok) return prepared;
        items = prepared.items;
        choice = await chooseEvraklar(items, who, preferred);
        if (choice.action !== "rescan") break;
        toast("Ağaç yeniden taranıyor…");
      }
      if (!choice.action) return { ok: true, cancelled: true, found: items.length };
      const result = await runPull(choice.selected, choice.action, who);
      return { ...result, found: items.length };
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
  /* ---------- UYAP dosya listesi (Vatandaş Portalı: Dosya Sorgulama) ----------
     Liste kendiliğinden gelmez: "Yargı Türü" seçilip "Dosya Sorgula"ya basılır (DataTables tablosu, varsayılan 15 kayıt/sayfa).
     Tüm dosyalar için her yargı türü sırayla sorgulanır ve sayfa boyutu "Tümü" yapılır. Sorgunun bittiği, ağ isteğinin
     tamamlanmasından (PerformanceObserver) anlaşılır: sonuç değişmese de (aynı tür, boş sonuç) doğru çalışır.
     Liste kişisel veri içerir: yalnız JurisAI sayfasına verilir, sunucuya gönderilmez. */
  let xhrDone = 0;
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) if (/xmlhttprequest|fetch/.test(entry.initiatorType)) xhrDone += 1;
    }).observe({ type: "resource" });
  } catch (_) {
    /* gözlemci yoksa süre sınırı kullanılır */
  }
  const waitForXhr = (since, timeoutMs) => waitUntil(() => xhrDone > since, timeoutMs, 40);

  const selectedTypeLabel = () => {
    const select = document.querySelector("#yargiTuru");
    return select && select.selectedIndex >= 0 ? textOf(select.options[select.selectedIndex]) : "";
  };
  let shownType = ""; // tablonun şu an hangi yargı türünün sonucunu gösterdiği (kullanıcı kendisi sorgulasa da izlenir)
  document.addEventListener(
    "click",
    (event) => {
      if (event.target instanceof Element && event.target.closest("#btnQueryDoc")) shownType = selectedTypeLabel();
    },
    true,
  );
  const currentType = () => shownType || selectedTypeLabel();

  function dosyaQueryForm() {
    const select = document.querySelector("#yargiTuru");
    const button =
      document.querySelector("#btnQueryDoc") ||
      [...document.querySelectorAll("button, input[type='button']")].find(
        (el) => trLower(`${textOf(el)} ${el.value || ""}`).trim() === "dosya sorgula" && visibleElement(el),
      );
    return select && button && select.options.length ? { select, button } : null;
  }
  function dosyaTable() {
    const byId = document.querySelector("#dosya_listesi_table");
    if (byId) return byId;
    return [...document.querySelectorAll("table")].find((table) =>
      [...table.querySelectorAll("button, a, input[type='button']")].some((el) => OPEN_RE.test(`${textOf(el)} ${el.value || ""}`)),
    );
  }
  const HEADER_FIELDS = {
    role: /taraf rol/,
    birim: /mahkeme|birim/,
    esas: /esas/,
    tur: /dosya t[uü]r/,
    acilis: /a[cç][iı]l[iı][sş]/,
    durum: /durum/,
  };
  /** Tablodaki dosya satırları. `seen`: aynı metinli satırlar için sıra numarası (anahtarı benzersiz yapar). */
  function readDosyaRows(table, yargiTuru, seen = new Map()) {
    const headers = [...table.querySelectorAll("thead th")].map((th) => trLower(textOf(th)));
    const index = {};
    for (const [field, pattern] of Object.entries(HEADER_FIELDS)) {
      const found = headers.findIndex((header) => pattern.test(header));
      if (found >= 0) index[field] = found;
    }
    const rows = [];
    for (const tr of table.querySelectorAll("tbody tr")) {
      if (!tr.querySelector("td") || tr.querySelector("td.dataTables_empty")) continue;
      const button = [...tr.querySelectorAll("button, a, input[type='button']")].find(
        (el) => !el.closest(".jurisai-launcher, .jurisai-case-picker, .jurisai-chooser") && OPEN_RE.test(`${textOf(el)} ${el.value || ""}`),
      );
      if (!button) continue;
      const tds = [...tr.querySelectorAll("td")].map((td) => textOf(td).replace(/\s+/g, " ").slice(0, 90));
      const cells = tds.filter((cell) => cell && !OPEN_RE.test(cell)).slice(0, 8);
      const pick = (field) => (index[field] !== undefined ? tds[index[field]] || "" : "");
      const esas = pick("esas") || cells.find((cell) => /^\d{4}\/\d+/.test(cell)) || "";
      const birim = pick("birim") || cells.find((cell) => /mahkeme|daire|müdürlü|savcılı|kurul|hakem/i.test(trLower(cell))) || "";
      const base = `${yargiTuru}|${cells.join(" | ")}`;
      const count = (seen.get(base) || 0) + 1;
      seen.set(base, count);
      rows.push({
        key: `${base}#${count}`,
        esas,
        birim,
        role: pick("role"),
        tur: pick("tur"),
        acilis: pick("acilis"),
        durum: pick("durum"),
        yargiTuru,
        cells,
        button,
      });
    }
    return rows;
  }
  /** Ekranda şu an görünen dosya satırları. */
  function dosyaRows() {
    const table = dosyaTable();
    return table ? readDosyaRows(table, currentType()) : [];
  }
  /** DataTables'ta sayfa boyutunu "Tümü"ne çevirir (yoksa en büyük seçenek). */
  async function showAllRows(table) {
    const length = table.closest(".dataTables_wrapper")?.querySelector("select[name$='_length']");
    if (!length) return;
    const all =
      [...length.options].find((option) => option.value === "-1") ||
      [...length.options].sort((a, b) => Number(b.value) - Number(a.value))[0];
    if (all && length.value !== all.value) {
      length.value = all.value;
      length.dispatchEvent(new Event("change", { bubbles: true }));
      await sleep(400);
    }
  }
  /** Tüm sayfaları okur (sayfa boyutu "Tümü" ise tek sayfadır; değilse "Sonraki" ile gezilir). */
  const dosyaPageSignature = (table) => readDosyaRows(table, "").map((row) => row.key).join("\n");
  async function readAllDosyaPages(table, yargiTuru, seen) {
    const rows = [];
    const signatures = new Set();
    for (let page = 0; page < 80; page += 1) {
      const signature = dosyaPageSignature(table);
      if (signatures.has(signature)) return { rows, error: `${yargiTuru}: sonraki sayfa yüklenmedi; tarama eksik.` };
      signatures.add(signature);
      rows.push(...readDosyaRows(table, yargiTuru, seen));
      const next = table.closest(".dataTables_wrapper")?.querySelector(".paginate_button.next:not(.disabled)");
      if (!next) return { rows, error: null };
      if (page === 79) return { rows, error: `${yargiTuru}: sayfa tarama güvenlik sınırına ulaşıldı; devamı okunamadı.` };
      (next.querySelector("a") || next).click();
      if (!(await waitUntil(() => dosyaPageSignature(table) !== signature, 10000)))
        return { rows, error: `${yargiTuru}: sonraki sayfa yüklenmedi; tarama eksik.` };
    }
    return { rows, error: `${yargiTuru}: sayfa taraması tamamlanamadı.` };
  }
  /** Bir yargı türünü seçip "Dosya Sorgula"ya basar; sorgunun ağ isteği bitene kadar bekler. */
  async function queryDosyaType(form, option) {
    const before = xhrDone;
    form.select.value = option.value;
    form.select.dispatchEvent(new Event("change", { bubbles: true }));
    await waitForXhr(before, 2000); // mahkeme listesi yenilenir (isteği yoksa süre dolar)
    await sleep(250);
    const since = xhrDone;
    shownType = textOf(option);
    // Herhangi bir XHR'nin bitmesi sonuç tablosunun hazır olduğunu kanıtlamaz (mahkeme sorgusu da XHR yapar).
    // Aynı/boş sonuç da tbody'yi yeniden çizer; bu yüzden metin değişimini değil çizim olayını bekle.
    let redrawn = false;
    const redraw = new MutationObserver((records) => {
      const tbody = dosyaTable()?.querySelector("tbody");
      if (tbody && records.some((record) => record.target === tbody || [...record.addedNodes].some((node) => node === tbody || (node instanceof Element && node.contains(tbody)))))
        redrawn = true;
    });
    redraw.observe(document.body, { childList: true, subtree: true });
    try {
      form.button.click();
      if (!(await waitUntil(() => {
        if (!(xhrDone > since && redrawn)) return false;
        const table = dosyaTable();
        if (!table || detailLoading(table.closest(".dataTables_wrapper") || table)) return false;
        // Başarısız AJAX tabloyu yalnız temizleyebilir. Tbody mutasyonu tek başına sonuç değildir:
        // açılabilir satır ya da portalın açık boş-sonuç hücresi gelmiş olmalı.
        return readDosyaRows(table, textOf(option)).length > 0 || !!table.querySelector("tbody td.dataTables_empty");
      }, 20000, 40)))
        return { ok: false, error: `${textOf(option)} sorgusu yanıt vermedi veya tablo yenilenmedi` };
      return { ok: true };
    } finally { redraw.disconnect(); }
  }
  async function listAllDosyalar(form) {
    const items = [];
    const types = [];
    const errors = [];
    const seen = new Map();
    for (const option of [...form.select.options]) {
      const label = textOf(option);
      if (!label) continue;
      const queried = await queryDosyaType(form, option);
      if (!queried.ok) {
        errors.push(queried.error);
        continue;
      }
      const table = dosyaTable();
      if (!table) {
        errors.push(`${label}: dosya tablosu bulunamadı`);
        continue;
      }
      await showAllRows(table);
      const scanned = await readAllDosyaPages(table, label, seen);
      const rows = scanned.rows;
      if (scanned.error) errors.push(scanned.error);
      types.push({ label, count: rows.length });
      items.push(...rows);
    }
    return { items, types, errors };
  }
  /** Anahtarı verilen satırı bulur; görünen listede yoksa onun yargı türünü yeniden sorgular. */
  async function findDosyaRow(key, type) {
    const visible = dosyaRows().find((entry) => entry.key === key);
    if (visible) return visible;
    const form = dosyaQueryForm();
    if (!form) return null;
    const label = type || key.split("|")[0];
    const option = [...form.select.options].find((candidate) => sameText(textOf(candidate), label));
    if (!option) return null;
    const queried = await queryDosyaType(form, option);
    if (!queried.ok) throw Object.assign(new Error(queried.error), { code: "query_failed" });
    const table = dosyaTable();
    if (table) await showAllRows(table);
    if (!table) return null;
    const seen = new Map();
    for (let page = 0; page < 80; page += 1) {
      const found = readDosyaRows(table, label, seen).find((entry) => entry.key === key);
      if (found) return found;
      const next = table.closest(".dataTables_wrapper")?.querySelector(".paginate_button.next:not(.disabled)");
      if (!next) return null;
      const before = dosyaPageSignature(table);
      (next.querySelector("a") || next).click();
      if (!(await waitUntil(() => dosyaPageSignature(table) !== before, 10000))) return null;
    }
    return null;
  }
  /** Dosya Sorgulama sayfasında değilsek yan menüden açar (sayfa yenilenir: yanıt önce verilir, tıklama sonra yapılır). */
  function openDosyaSorgulamaMenu() {
    const links = [...document.querySelectorAll("a")];
    const target = links.find((link) => sameText(textOf(link), "Dosya Sorgulama")); // "Danıştay Dosya Sorgulama" değil
    if (!target) return false;
    // Menü bağlantısı `javascript:menuButtonClick("12573")` biçimindedir: yalıtılmış dünyadan tıklamak sayfanın işlevini çalıştırmaz;
    // işlev sayfanın kendi dünyasında arka plan betiği aracılığıyla (yalnız sayısal kimlikle) çağrılır.
    const menuId = (/menuButtonClick\(\s*["'](\d{1,8})["']\s*\)/.exec(target.getAttribute("href") || "") || [])[1];
    if (menuId) {
      setTimeout(() => chrome.runtime.sendMessage({ type: "JURISAI_MENU", id: menuId }).catch(() => target.click()), 150);
      return true;
    }
    const parent = links.find((link) => sameText(textOf(link), "Sorgulama İşlemleri"));
    if (!visibleElement(target) && parent) parent.click(); // alt menüyü aç
    setTimeout(() => target.click(), 300);
    return true;
  }
  let listing = false;
  let recoveryUntil = 0;
  let recoveryMenuOpened = false;
  const recoveryBusy = () => Date.now() < recoveryUntil;
  /** Çıkış bağlantısı açılır menüde gizli olabilir (innerText'e girmez): gerçek portalın karşılama sayfasında giriş yapılmışken
      "giriş yapılmamış" denmesinin nedeni buydu (2026-10-05). Bağlantının kendisi DOM'da aranır. */
  function hasLogoutLink() {
    return [...document.querySelectorAll("a[href]")].some(
      (link) => /kill_session|logout/i.test(link.getAttribute("href") || "") || /güvenli çıkış|oturumu kapat/.test(trLower(link.textContent || "")),
    );
  }
  async function listDosyalar() {
    if (listing || pulling || recoveryBusy()) return { ok: false, code: "busy", error: "UYAP'ta bir listeleme veya aktarım sürüyor; bitince yeniden dene." };
    listing = true;
    try { return await readDosyalar(); }
    finally { listing = false; }
  }
  async function readDosyalar() {
    const form = dosyaQueryForm();
    if (form) {
      const { items, types, errors } = await listAllDosyalar(form);
      if (!items.length && errors.length) return { ok: false, code: "query_failed", error: errors[0] };
      return { ok: true, items: items.map(({ button: _button, ...info }) => info), types, errors, complete: errors.length === 0, pages: null, page: null };
    }
    const rows = dosyaRows();
    if (rows.length) {
      const paging = /Toplam\s+(\d+)\s+sayfadan\s+(\d+)\.\s*sayfa/i.exec(document.body?.innerText || "");
      return {
        ok: true,
        items: rows.map(({ button: _button, ...info }) => info),
        types: [],
        errors: [],
        complete: false, // bu portalda yalnız görünen satırlar okunabildi
        pages: paging ? Number(paging[1]) : null,
        page: paging ? Number(paging[2]) : null,
      };
    }
    const page = trLower((document.body?.innerText || "").slice(0, 8000));
    const loginPage = /giriş yap|giriş seçenekleri|e-?devlet ile giriş|e-?imza ile giriş/.test(page) && !/güvenli çıkış|çıkış yap|oturumu kapat/.test(page) && !hasLogoutLink();
    if (loginPage) {
      return {
        ok: false,
        code: "login_required",
        error: "UYAP'ta giriş yapılmamış görünüyor: önce giriş yap, sonra Dosya Sorgulama'yı aç.",
      };
    }
    if (openDosyaSorgulamaMenu()) {
      return { ok: false, code: "navigating", error: "UYAP'ta Dosya Sorgulama sayfası açılıyor…" };
    }
    return {
      ok: false,
      code: "no_list",
      error: "Bu UYAP sekmesinde dosya listesi görünmüyor: UYAP'ta Dosya Sorgulama (dosya listesi) sayfasını aç.",
    };
  }
  async function openDosyaByKey(key, type) {
    if (listing || recoveryBusy()) return { ok: false, code: "busy", error: "Dosya listesi taranıyor veya toparlanıyor; bitince tekrar dene." };
    const row = await findDosyaRow(key, type);
    if (!row) return { ok: false, code: "stale", error: "UYAP'taki liste değişmiş: dosyaları yeniden listele." };
    if (pulling) return { ok: false, code: "busy", error: "Bir çekme zaten sürüyor." };
    openCaseAndChoose(row.button); // dosyayı açar, evrak seçim penceresini UYAP sekmesinde gösterir; beklenmez
    return { ok: true };
  }
  /* ---------- JurisAI sayfasından yönetilen işler (köprü) ----------
     JurisAI sayfası bir dosyanın evrak ağacını ister (TREE) ve seçtiklerinin çekilmesini başlatır (PULL). İkisi de hemen döner,
     sayfa ilerlemeyi STATUS ile yoklar. Durum bu içerik betiğinde (UYAP sekmesinde) tutulur: arka plan betiği yeniden başlasa da
     kaybolmaz. Kullanıcı JurisAI sekmesindeyken UYAP sekmesi gizli kalır; beklemeler bu yüzden `sleep` ile kısılmadan yapılır. */
  const bridge = { job: null, tree: null, run: null, detail: null };
  const newJobId = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  const serializeItem = ({ id, title, folders, typeName, isEk, declared }) => ({ id, title, folders, typeName, isEk, declared });

  function closeButtonOf(dialog) {
    return [...dialog.querySelectorAll("button, a, input[type='button'], .close")].find((el) => {
      if (!visibleElement(el)) return false;
      const label = trLower(`${textOf(el)} ${el.value || ""} ${el.getAttribute("aria-label") || ""} ${el.getAttribute("title") || ""}`)
        .replace(/\s+/g, " ")
        .trim();
      return /^(kapat|×|x|close)$/.test(label) || el.classList.contains("close");
    });
  }
  async function closeDialog(dialog) {
    const button = closeButtonOf(dialog);
    if (!button) return false;
    button.click();
    return waitUntil(() => activeRoot() !== dialog, 8000);
  }
  /**
   * Satırın "Dosya Görüntüle" düğmesine basar ve pencerenin açılmasını bekler. Bootstrap modalı kapanırken (≈300 ms animasyon) gelen
   * "aç" komutunu yutar; liste de yeniden çizilmiş olabilir: her denemede satır yeniden bulunur, açılmazsa bekleyip yeniden denenir.
   */
  async function clickOpenWithRetry(key, type) {
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const row = await findDosyaRow(key, type);
      if (!row) return false;
      row.button.click();
      if (await waitUntil(() => {
        const dialog = activeRoot();
        if (!dialog) return false;
        const who = dosyaIdentity(dialog);
        return who.esas && sameText(who.esas, row.esas) && (!row.birim || sameText(who.birim, row.birim));
      }, 6000)) return true;
      await sleep(1200);
    }
    return false;
  }
  /** Listede anahtarı verilen dosyayı açar (başka bir dosya açıksa önce kapatır) ve Evrak sekmesine geçer. */
  async function openDosyaForTree(key, type, { tree = true } = {}) {
    // Başka yargı türünü sorgulamadan önce modal kapanmalı: açık modal varken arkadaki listeyi sorgulamak portalın
    // AJAX durumunu bozabilir. Aynı satır görünüyorsa aynı dosya penceresi aşağıda yeniden kullanılabilir.
    let dialog = activeRoot();
    if (dialog && key && dosyaQueryForm() && !dosyaRows().some((entry) => entry.key === key)) {
      if (!(await closeDialog(dialog)))
        return { ok: false, code: "cannot_close", error: "UYAP'ta açık olan dosya penceresi kapatılamadı: pencereyi kapatıp tekrar dene." };
      dialog = null;
      await sleep(700);
    }
    const row = key ? await findDosyaRow(key, type) : null;
    if (key && !row) return { ok: false, code: "stale", error: "UYAP'taki liste değişmiş: dosyaları yeniden listele." };
    dialog = activeRoot();
    if (dialog && row) {
      const open = dosyaIdentity(dialog);
      if (open.esas && sameText(open.esas, row.esas) && (!row.birim || sameText(open.birim, row.birim))) {
        if (tree) openEvrakTab(dialog);
      } else {
        if (!(await closeDialog(dialog)))
          return { ok: false, code: "cannot_close", error: "UYAP'ta açık olan dosya penceresi kapatılamadı: pencereyi kapatıp tekrar dene." };
        dialog = null;
        await sleep(700); // kapanış animasyonu bitsin
      }
    }
    if (!dialog) {
      if (!row) return { ok: false, code: "stale", error: "UYAP'taki liste değişmiş: dosyaları yeniden listele." };
      if (!(await clickOpenWithRetry(key, type))) return { ok: false, code: "open_failed", error: "UYAP'ta istenen dosya penceresi açılamadı veya kimliği doğrulanamadı." };
      await sleep(600);
      dialog = activeRoot();
      if (tree) openEvrakTab(dialog);
    }
    if (!tree) return { ok: true, dialog };
    // Sekmeye ilk tıklama Bootstrap/AJAX geçişinde yutulabilir. Görünür pane ve bağlı dosya penceresi
    // doğrulanmadan gizli/eski ağacı kabul etme; yalnız SALT OKUNUR evrak sekmesini bir kez daha etkinleştir.
    let hasTree = false;
    for (let attempt = 0; attempt < 2 && !hasTree && !pulling?.stop; attempt += 1) {
      if (attempt) openEvrakTab(dialog, true);
      hasTree = await waitUntil(() => {
        if (pulling?.stop) return true; // aşağıdaki iptal denetimine hemen dön
        if (!dialog.isConnected || activeRoot() !== dialog) return false;
        const tab = evrakTabOf(dialog);
        const pane = tab && detailPane(dialog, detailPaneId(tab));
        if (pane && !detailPaneShown(pane, dialog)) return false;
        return !!dialog.querySelector("span.file[evrak_id], li.expandable");
      }, 10000);
    }
    if (pulling?.stop) return { ok: false, code: "aborted", error: "İptal edildi." };
    if (!hasTree) {
      const empty = /dosyaya ait evrak bilgisi bulunamadı/i.test(dialog.textContent || "");
      return {
        ok: false,
        code: empty ? "empty_tree" : "no_tree",
        error: empty
          ? "UYAP bu dosyada evrak bilgisi bulunmadığını bildiriyor."
          : "Bu dosyanın evrak sekmesi/ağacı iki denemede yüklenmedi; UYAP penceresindeki Evrak sekmesini ve uyarıları kontrol et.",
      };
    }
    return { ok: true, dialog };
  }
  /* ---------- Dosya detayı: dosya bilgileri, dosya hesabı, taraflar, safahat, tahsilat/reddiyat ----------
     Dosya penceresinin evrak dışındaki sekmeleri SALT OKUNUR okunur (gerçek portalda ölçüldü, 2026-10-06): sekmeye geçilir, tablolar
     "Tümü" sayfa boyutuyla ya da sayfa sayfa tamamen okunur, UYAP'ın kendi "N Kayıttan" sayısıyla karşılaştırılır. "Evrak Gönderme" ve
     "Ödeme" sekmelerine (form/ödeme düğmeleri) ve "Borç Öde" gibi düğmelere hiç dokunulmaz. Değerler yorumlanmaz, UYAP'ın yazdığı
     metin olarak saklanır. */
  const DETAIL_TABS = [
    { key: "bilgiler", label: "dosya bilgileri", paneId: "dosya_ayrinti_bilgileri_tab" },
    { key: "hesap", label: "dosya hesabı", paneId: "dosya_hesap_bilgileri_tab" },
    { key: "taraflar", label: "taraf bilgileri", paneId: "dosya_taraf_bilgileri_tab" },
    { key: "safahat", label: "safahat", paneId: "dosya_safahat_bilgileri_tab", press: "#btnQuerySafahatInfo" },
    { key: "tahsilat", label: "tah./red. bilgileri", paneId: "dosya_tahsilat_reddiyat_bilgileri_tab" },
  ];
  const TAB_LINK_SELECTOR = "a[data-toggle='tab'], [data-bs-toggle='tab'], ul.nav-tabs a, ul.nav-pills a, [role='tab']";
  // Hedef bir CSS seçicisi gibi çalıştırılmaz: yalnız dosya penceresinin içindeki tam id eşleşmesi kullanılır.
  function detailPaneId(link) {
    const target = link.getAttribute("data-target") || link.getAttribute("data-bs-target") || link.getAttribute("href") || "";
    return target.startsWith("#") && target.length > 1 ? target.slice(1) : link.getAttribute("aria-controls") || "";
  }
  function detailPane(dialog, id) {
    return [...dialog.querySelectorAll("[id]")].find((el) => el.id === id) || null;
  }
  // Float/absolute çocuklar veya display:contents yüzünden açık pane'in kendi kutusu 0 px olabilir.
  // Görünürlüğü zorlamadan tüm üst öğelerin CSS durumunu kontrol et; gizli üst öğeyi asla açık sayma.
  function detailPaneShown(pane, dialog) {
    if (!pane?.isConnected) return false;
    const boundary = dialog instanceof Document ? dialog.documentElement : dialog;
    for (let el = pane; el; el = el.parentElement) {
      const style = getComputedStyle(el);
      if (el.hidden || style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse") return false;
      if (el === boundary) return true;
    }
    return false;
  }
  const detailLoading = (pane) => [pane, ...pane.querySelectorAll(".dataTables_processing, [aria-busy='true']")].some((el) =>
    (el.getAttribute("aria-busy") === "true" || el.classList.contains("dataTables_processing")) && detailPaneShown(el, pane));
  const explicitEmptyDetail = (pane) => /kayıt (?:yok|bulunamadı)|bilgi(?:si)? bulunamadı|herhangi bir veri mevcut değil/.test(trLower(textOf(pane)));
  function confirmedEmptyTable(table) {
    const cells = [...table.querySelectorAll("tbody td.dataTables_empty")];
    return cells.some(explicitEmptyDetail) && readDetailTable(table).rows.length === 0 && !detailLoading(table);
  }
  const declaredTableRows = (table) => declaredRows(table.closest(".dataTables_wrapper")) ?? (confirmedEmptyTable(table) ? 0 : null);
  function assertDetailActive(dialog) {
    if (pulling?.stop) throw Object.assign(new Error("İptal edildi."), { code: "aborted" });
    if (!dialog.isConnected || !visibleElement(dialog)) throw Object.assign(new Error("Dosya penceresi kapandı; bilgiler okunamadı."), { code: "no_dialog" });
  }
  const cellText = (el) => textOf(el).replace(/\s+/g, " ").slice(0, 4000);
  const isHiddenColumn = (el) => el.classList.contains("hidden") || el.classList.contains("hide") || el.style.display === "none";
  const hasActionControl = (el) => !!el.querySelector("button, input[type='button'], a.btn");

  /** DataTables'ın "N Kayıttan M - K Arası Kayıtlar" yazısından UYAP'ın söylediği toplam; yazı yoksa null. */
  function declaredRows(wrapper) {
    const info = textOf(wrapper?.querySelector(".dataTables_info"));
    const found = /([\d.]+)\s+kay[ıi]ttan/i.exec(info);
    if (found) return Number(found[1].replace(/\./g, ""));
    if (/kay[ıi]t yok/i.test(info)) return 0;
    return null;
  }
  const tableTitle = (table) => {
    const holder = table.closest(".panel, .box, .portlet, fieldset, .card, .widget-box");
    const head = holder?.querySelector(".panel-heading, .box-title, .portlet-title, legend, .card-header, .widget-title");
    return textOf(head || table.querySelector("caption")).slice(0, 80);
  };
  /** Bir tablonun görünen (gizli sütunsuz) başlık ve hücrelerini okur; evrak/etkileşim satırı yoktur. */
  function readDetailTable(table) {
    const headRow = table.querySelector("thead tr");
    const headCells = headRow ? [...headRow.children] : [];
    const columns = headCells.map((th, index) => ({ th, index })).filter(({ th }) => !isHiddenColumn(th));
    const headers = columns.map(({ th }) => cellText(th));
    const rows = [];
    for (const tr of table.querySelectorAll("tbody tr")) {
      if (tr.querySelector("td.dataTables_empty")) continue;
      const tds = [...tr.children];
      const picked = headCells.length ? columns.map(({ index }) => tds[index]) : tds.filter((td) => !isHiddenColumn(td));
      // Düğme taşıyan hücre ("Detay" gibi eylem sütunu) veri değildir: düğme yazısı değer diye saklanmaz.
      rows.push(picked.map((td) => (td && !hasActionControl(td) ? cellText(td) : "")));
    }
    return { headers, rows };
  }
  /** DataTables'ın AJAX ile dolmasını bekler: "N Kayıttan" yazısı, satır sayısı ve boşluk durumu iki turda değişmeden kalmalı. */
  async function settleTable(table) {
    const wrapper = table.closest(".dataTables_wrapper");
    if (!wrapper) return table.isConnected && !detailLoading(table);
    let last = "";
    for (let i = 0; i < 40; i += 1) {
      if (pulling?.stop) throw Object.assign(new Error("İptal edildi."), { code: "aborted" });
      const state = `${declaredTableRows(table)}|${textOf(table.querySelector("tbody"))}`;
      if (table.isConnected && !detailLoading(wrapper) && declaredTableRows(table) !== null && state === last && i >= 2) return true;
      last = state;
      await sleep(500);
    }
    return false;
  }
  /** Sayfa boyutunu "Tümü"ne alır; olmazsa sayfaları gezer. Okunan satırların UYAP'ın sayısıyla uyuşup uyuşmadığını da döndürür. */
  async function readAllDetailRows(table, problems, label) {
    const wrapper = table.closest(".dataTables_wrapper");
    let settled = await settleTable(table);
    const length = wrapper?.querySelector("select[name$='_length']");
    if (length) {
      const all = [...length.options].find((option) => option.value === "-1") || [...length.options].sort((a, b) => Number(b.value) - Number(a.value))[0];
      if (all && length.value !== all.value) {
        length.value = all.value;
        length.dispatchEvent(new Event("change", { bubbles: true }));
        await sleep(700);
        settled = await settleTable(table);
      }
    }
    let declared = declaredTableRows(table);
    let result = readDetailTable(table);
    // Vatandaş Portalı statik reddiyat detaylarını ana tabloyla birlikte gizli DIV'lerde
    // üretir; DataTables sayacı yoktur. Yalnız eşleşen Detay düğmesi + tam başlık şeması
    // + kararlı ve yüklenmeyen tbody bu özel boş sonuç için kanıttır. Genel boş tablo
    // hâlâ belirsizdir; Detay düğmesine (ve ödeme/işlem düğmelerine) basılmaz.
    let emptyEvidence;
    const detailId = /^tahsilatDetay(\d+)$/.exec(table.parentElement?.id || "");
    const pane = table.closest("#dosya_tahsilat_reddiyat_bilgileri_tab");
    const detailButton = detailId && pane && [...pane.querySelectorAll("input[type='button']")]
      .find((button) => button.id === `makbuzDetayGoster${detailId[1]}` && trLower(button.value) === "detay");
    const headers = result.headers.map(trLower);
    if (declared === null && !result.rows.length && !wrapper && detailButton &&
        headers.length === 12 && headers[0] === "makbuz no" && headers[1] === "reddiyat tarihi" &&
        headers[2] === "reddiyat nedeni" && headers[11] === "ödenecek tutar" && table.querySelector("tbody")) {
      await sleep(1000);
      result = readDetailTable(table);
      if (table.isConnected && !detailLoading(pane) && !detailLoading(table) && !result.rows.length &&
          result.headers.map(trLower).join("|") === headers.join("|")) {
        declared = 0;
        settled = true;
        emptyEvidence = "uyap_static_reddiyat_detail";
      }
    }
    const signature = () => readDetailTable(table).rows.map((row) => row.join("\u0001")).join("\n");
    if (declared !== null && result.rows.length < declared) {
      // Sayfa boyutu "Tümü" olmadı: sayfa sayfa gez (her sayfa ayrı okunur, tekrar eden sayfa durdurur).
      const collected = [];
      const seen = new Set();
      for (let page = 0; page < 500; page += 1) {
        const sig = signature();
        if (seen.has(sig)) break;
        seen.add(sig);
        collected.push(...readDetailTable(table).rows);
        const next = wrapper?.querySelector(".paginate_button.next:not(.disabled)");
        if (!next || collected.length >= declared) break;
        (next.querySelector("a") || next).click();
        if (!(await waitUntil(() => signature() !== sig, 8000))) {
          problems.push(`${label}: sonraki sayfa yüklenmedi.`);
          break;
        }
        if (!(await settleTable(table))) { settled = false; break; }
      }
      result = { headers: result.headers, rows: collected };
    }
    const complete = settled && (declared === null ? result.rows.length > 0 : result.rows.length === declared);
    if (!settled) problems.push(`${label}: tablo yüklemesi veya kayıt sayısı doğrulanamadı.`);
    else if (!complete) problems.push(`${label}: UYAP ${declared ?? "belirsiz"} kayıt yazıyor, ${result.rows.length} okundu.`);
    return { ...result, declared, complete, ...(emptyEvidence ? { empty_evidence: emptyEvidence } : {}) };
  }
  /** İki sütunlu "etiket: değer" tablosu (dosya bilgileri, dosya hesabı). Düğme taşıyan satır (ör. "Borç Öde") okunmaz. */
  function readPairs(pane) {
    const pairs = [];
    for (const table of pane.querySelectorAll("table")) {
      if (table.querySelector("thead th")) continue;
      for (const tr of table.querySelectorAll("tbody tr, tr")) {
        const tds = [...tr.children].filter((cell) => !isHiddenColumn(cell));
        if (tds.length < 2 || tds.some(hasActionControl)) continue;
        const label = cellText(tds[0]);
        if (label && !pairs.some((pair) => pair.label === label)) pairs.push({ label, value: cellText(tds[1]) });
      }
    }
    return pairs;
  }
  async function readDetailTab(dialog, spec, problems) {
    assertDetailActive(dialog);
    const link = [...dialog.querySelectorAll(TAB_LINK_SELECTOR)].find((el) => visibleElement(el) && (detailPaneId(el) === spec.paneId || trLower(textOf(el)) === spec.label));
    if (!link) return null; // bu dosya türünde bu sekme yok
    link.click();
    const paneId = detailPaneId(link) || spec.paneId;
    const opened = await waitUntil(() => {
      assertDetailActive(dialog);
      const current = detailPane(dialog, paneId);
      return detailPaneShown(current, dialog);
    }, 8000);
    if (!opened) {
      problems.push(`${textOf(link)}: sekme açılmadı.`);
      return { key: spec.key, label: textOf(link), pairs: [], tables: [], complete: false };
    }
    let pane = detailPane(dialog, paneId);
    await sleep(500); // sekme içeriği AJAX ile dolar
    if (spec.press) {
      const button = pane.querySelector(spec.press);
      if (button) {
        // Eski tablo ekranda kalabilir: yalnız eski satırın varlığı değil yeni sorgunun çizimi de görülmeli.
        let redrawn = false;
        const observer = new MutationObserver((records) => {
          if (records.some((record) => {
            const el = record.target.nodeType === 1 ? record.target : record.target.parentElement;
            return el && !el.closest(".jurisai-toolbar, .jurisai-send-btn") && (el.closest("tbody, .dataTables_info") ||
              [...record.addedNodes].some((node) => node instanceof Element && (node.matches("table, tbody, .dataTables_wrapper, .dataTables_empty") || node.querySelector("table, tbody, .dataTables_empty"))));
          })) redrawn = true;
        });
        observer.observe(pane, { childList: true, subtree: true, characterData: true });
        let drawn;
        try {
          button.click();
          drawn = await waitUntil(() => {
            assertDetailActive(dialog);
            pane = detailPane(dialog, paneId);
            if (!pane || !redrawn || detailLoading(pane)) return false;
            return [...pane.querySelectorAll("table")].some((table) => declaredTableRows(table) !== null);
          }, 30000);
        } finally { observer.disconnect(); }
        if (!drawn) {
          problems.push(`${textOf(link)}: sorgu sonucu gelmedi.`);
          return { key: spec.key, label: textOf(link), pairs: [], tables: [], complete: false };
        }
        await sleep(400);
      }
    } else {
      await waitUntil(() => {
        assertDetailActive(dialog);
        pane = detailPane(dialog, paneId);
        return pane && !detailLoading(pane) && (pane.querySelector("table tbody tr") || explicitEmptyDetail(pane));
      }, 10000);
    }
    assertDetailActive(dialog);
    pane = detailPane(dialog, paneId);
    if (!pane || detailLoading(pane)) return { key: spec.key, label: textOf(link), pairs: [], tables: [], complete: false };
    const pairs = readPairs(pane);
    const tables = [];
    let complete = true;
    for (const table of pane.querySelectorAll("table")) {
      if (!table.querySelector("thead th")) continue; // etiket/değer tablosu yukarıda okundu
      const title = /^tahsilatDetay\d+$/.test(table.parentElement?.id || "") ? "Reddiyat detayı" : tableTitle(table);
      const read = await readAllDetailRows(table, problems, `${textOf(link)}${title ? ` / ${title}` : ""}`);
      if (!read.complete) complete = false;
      tables.push({ title, headers: read.headers, rows: read.rows, declared: read.declared, complete: read.complete,
        ...(read.empty_evidence ? { empty_evidence: read.empty_evidence } : {}) });
    }
    if (!pairs.length && !tables.length) {
      if (explicitEmptyDetail(pane)) tables.push({ title: "", headers: [], rows: [], declared: 0, complete: true });
      else {
        complete = false;
        problems.push(`${textOf(link)}: içerik yüklenmedi; boş sonuç doğrulanamadı.`);
      }
    }
    return { key: spec.key, label: textOf(link), pairs, tables, complete };
  }
  /** Açık dosya penceresinin evrak dışı bilgileri; her sekme ayrı raporlanır, biri okunamazsa diğerleri yine gelir. */
  async function readDosyaDetail(dialog, onPhase = () => {}) {
    const problems = [];
    const tabs = [];
    for (const spec of DETAIL_TABS) {
      onPhase(`${spec.label} okunuyor`);
      try {
        let tab;
        let tabProblems = [];
        for (let attempt = 0; attempt < 2; attempt += 1) {
          assertDetailActive(dialog);
          tabProblems = [];
          tab = await readDetailTab(dialog, spec, tabProblems);
          if (!tab || tab.complete) break;
          if (attempt === 0) {
            onPhase(`${spec.label} yeniden okunuyor`);
            await sleep(2000);
          }
        }
        problems.push(...tabProblems);
        if (tab) tabs.push(tab);
      } catch (error) {
        if (error?.code === "aborted" || error?.code === "no_dialog") throw error;
        problems.push(`${spec.label}: ${error?.message || "okunamadı"}`);
        tabs.push({ key: spec.key, label: spec.label, pairs: [], tables: [], complete: false });
      }
    }
    return { tabs, problems: problems.slice(0, 12), complete: tabs.length > 0 && tabs.every((tab) => tab.complete) };
  }
  function startDetailJob(key, type) {
    if (listing || recoveryBusy()) return { ok: false, code: "busy", error: "Dosya listesi taranıyor veya toparlanıyor; bitince tekrar dene." };
    if (pulling) return { ok: false, code: "busy", error: "UYAP sekmesinde bir işlem sürüyor; bitince tekrar dene." };
    if (!key && !activeRoot()) return { ok: false, code: "no_dialog", error: "UYAP'ta açık bir dosya yok." };
    const job = { id: newJobId(), kind: "detail", state: "running", phase: "Dosya açılıyor", startedAt: Date.now() };
    bridge.job = job;
    bridge.detail = null;
    pulling = { stop: false };
    (async () => {
      const opened = key ? await openDosyaForTree(key, type, { tree: false }) : { ok: true, dialog: activeRoot() };
      if (!opened.ok) throw Object.assign(new Error(opened.error), { code: opened.code });
      const detail = await readDosyaDetail(opened.dialog, (phase) => {
        job.phase = phase;
      });
      bridge.detail = { who: dosyaIdentity(opened.dialog), ...detail };
      Object.assign(job, { state: "done", phase: "Hazır", count: detail.tabs.length, finishedAt: Date.now() });
    })()
      .catch((error) =>
        Object.assign(job, { state: "error", error: error.message || "bilinmeyen hata", code: error.code, finishedAt: Date.now() }),
      )
      .finally(() => {
        pulling = null;
      });
    return { ok: true, jobId: job.id };
  }
  function startTreeJob(key, type) {
    if (listing || recoveryBusy()) return { ok: false, code: "busy", error: "Dosya listesi taranıyor veya toparlanıyor; bitince tekrar dene." };
    if (pulling) return { ok: false, code: "busy", error: "UYAP sekmesinde bir işlem sürüyor; bitince tekrar dene." };
    if (!key && !activeRoot()) return { ok: false, code: "no_dialog", error: "UYAP'ta açık bir dosya yok." };
    const job = { id: newJobId(), kind: "tree", state: "running", phase: "Dosya açılıyor", startedAt: Date.now() };
    bridge.job = job;
    bridge.tree = null;
    pulling = { stop: false };
    (async () => {
      const opened = key ? await openDosyaForTree(key, type) : { ok: true, dialog: activeRoot() };
      if (!opened.ok) throw Object.assign(new Error(opened.error), { code: opened.code });
      job.phase = "Evrak ağacı açılıyor";
      const prepared = await prepareTree(opened.dialog, (gaps) => {
        job.phase = `${gaps} klasör yeniden yükleniyor`;
      });
      if (!prepared.ok) throw new Error(prepared.error);
      job.phase = "Daha önce aktarılanlar kontrol ediliyor";
      const who = dosyaIdentity(opened.dialog);
      const known = await chrome.runtime
        .sendMessage({ type: "JURISAI_PULL_KNOWN", ids: prepared.items.map((item) => item.id), esas: who.esas, birim: who.birim })
        .catch(() => null);
      bridge.tree = { key, who, items: prepared.items, known: known?.ok ? known.known : [], knownChecked: !!known?.ok };
      Object.assign(job, { state: "done", phase: "Hazır", count: prepared.items.length, finishedAt: Date.now() });
    })()
      .catch((error) =>
        Object.assign(job, { state: "error", error: error.message || "bilinmeyen hata", code: error.code, finishedAt: Date.now() }),
      )
      .finally(() => {
        pulling = null;
      });
    return { ok: true, jobId: job.id };
  }
  function startPullJob(ids, mode) {
    if (pulling || listing || recoveryBusy()) return { ok: false, code: "busy", error: "UYAP sekmesinde bir işlem sürüyor; bitince tekrar dene." };
    if (!bridge.tree) return { ok: false, code: "no_tree", error: "Önce evrakları listele." };
    const wanted = new Set(Array.isArray(ids) ? ids.map(String) : []);
    const items = bridge.tree.items.filter((item) => wanted.has(item.id));
    if (!items.length) return { ok: false, code: "empty", error: "Seçili evrak yok." };
    if (items.some((item) => !item.span.isConnected))
      return { ok: false, code: "stale_tree", error: "UYAP'taki dosya penceresi değişti: evrakları yeniden listele." };
    const job = { id: newJobId(), kind: "pull", state: "running", phase: "Başlıyor", startedAt: Date.now() };
    const run = { mode: mode === "disk" ? "disk" : "upload", chosen: items.length, total: items.length, done: 0, current: "", startedAt: Date.now() };
    bridge.job = job;
    bridge.run = run;
    pulling = { stop: false };
    runPull(items, run.mode, bridge.tree.who, { progress: run, jobId: job.id })
      .then((result) => {
        run.result = result;
        Object.assign(job, result.ok ? { state: "done", phase: run.phase || "Bitti" } : { state: "error", error: result.error }, { finishedAt: Date.now() });
      })
      .catch((error) => Object.assign(job, { state: "error", error: error.message || "bilinmeyen hata", finishedAt: Date.now() }))
      .finally(() => {
        pulling = null;
        chrome.runtime.sendMessage({ type: "JURISAI_PULL_END", jobId: job.id }).catch(() => {});
      });
    return { ok: true, jobId: job.id, total: items.length };
  }
  function loginRequiredForRecovery() {
    return !hasLogoutLink() && /giriş yap|giriş seçenekleri|e-?devlet ile giriş|e-?imza ile giriş/.test(trLower((document.body?.innerText || "").slice(0, 8000)));
  }
  function prepareReadRecovery(jobId) {
    const job = bridge.job;
    if (listing || pulling || recoveryBusy()) return { ok: false, code: "busy", error: "Süren iş otomatik yenilenemez." };
    if (!job || job.id !== jobId || job.state !== "error" || !["tree", "detail"].includes(job.kind) ||
        !["open_failed", "no_tree", "query_failed", "cannot_close"].includes(job.code) || Date.now() - job.finishedAt > 120000)
      return { ok: false, code: "recovery_refused", error: "Yalnız yeni başarısız salt okunur iş toparlanabilir." };
    if (loginRequiredForRecovery()) return { ok: false, code: "login_required", error: "UYAP oturumu kapanmış; tekrar giriş yap." };
    if (!dosyaQueryForm() && !dosyaRows().length) return { ok: false, code: "no_list", error: "Dosya listesi doğrulanamadı; sayfa yenilenmedi." };
    // Be deliberately conservative: never discard an open editor, credentials,
    // selected file or user-entered text (ordinary blank table filters are harmless).
    const editing = [...document.querySelectorAll("input,textarea,[contenteditable='true']")].some(el =>
      visibleElement(el) && (el === document.activeElement || el.matches("textarea,[contenteditable='true'],input[type='password'],input[type='file']") ||
        (!el.matches("input[type='button'],input[type='submit'],input[type='checkbox'],input[type='radio'],input[type='hidden']") && !!String(el.value || "").trim())));
    if (editing) return { ok: false, code: "editing", error: "Açık giriş/düzenleme alanı var; sayfa otomatik yenilenmedi." };
    recoveryUntil = Date.now() + 5000;
    return { ok: true };
  }
  function recoveryReady() {
    if (loginRequiredForRecovery()) return { ok: false, code: "login_required", error: "UYAP oturumu kapanmış; tekrar giriş yap." };
    if (listing || pulling) return { ok: false, code: "busy", error: "UYAP'ta başka işlem başladı; toparlanma durdu." };
    if (dosyaQueryForm() || dosyaRows().length) return { ok: true };
    if (!recoveryMenuOpened && hasLogoutLink()) {
      recoveryMenuOpened = true;
      openDosyaSorgulamaMenu();
    }
    return { ok: false, code: "navigating", error: "Dosya Sorgulama sayfası bekleniyor." };
  }
  function jobStatus(jobId, withTree, withDetail) {
    if (!bridge.job || bridge.job.id !== jobId) return { ok: false, code: "unknown_job", error: "Bu iş bu sekmede yok." };
    const out = { ok: true, job: { ...bridge.job } };
    if (bridge.job.kind === "pull" && bridge.run) out.run = JSON.parse(JSON.stringify(bridge.run));
    if (withDetail && bridge.job.kind === "detail" && bridge.detail) out.detail = JSON.parse(JSON.stringify(bridge.detail));
    if (withTree && bridge.job.kind === "tree" && bridge.tree) {
      out.tree = {
        who: bridge.tree.who,
        items: bridge.tree.items.map(serializeItem),
        counts: countSummary(bridge.tree.items),
        known: bridge.tree.known,
        knownChecked: bridge.tree.knownChecked,
      };
    }
    return out;
  }
  /** Bu sekmede o an süren iş (JurisAI sayfası yenilendiğinde ya da yeniden açıldığında süren aktarıma yeniden bağlanabilsin). */
  function currentJob() {
    const out = { ok: true, busy: !!(listing || pulling || recoveryBusy()), listing: !!listing, job: null };
    if (bridge.job && bridge.job.state === "running") {
      out.job = { ...bridge.job };
      if (bridge.job.kind === "pull" && bridge.run) out.run = JSON.parse(JSON.stringify(bridge.run));
    }
    return out;
  }
  function stopJob(jobId) {
    if (!pulling || !bridge.job || bridge.job.id !== jobId) return { ok: false, code: "idle", error: "Süren işlem yok." };
    stopPull();
    return { ok: true };
  }
  function stopPull() {
    if (!pulling) return;
    pulling.stop = true;
    const jobId = bridge.job?.kind === "pull" && bridge.job.state === "running" ? bridge.job.id : "";
    chrome.runtime.sendMessage({ type: "JURISAI_PULL_CANCEL", jobId }).catch(() => {});
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

  /** Doğrudan indirme denemesi: ilk iki evrağı normal yoldan alır, ikincisini kurulan adresle karşılaştırır (hiçbir belge saklanmaz). */
  async function probeDirect() {
    if (recoveryBusy()) return { ok: false, code: "busy", error: "UYAP sayfası toparlanıyor; bitince tekrar dene." };
    const dialog = activeRoot();
    if (!dialog) return { ok: false, error: "Açık bir dosya penceresi yok." };
    if (pulling) return { ok: false, error: "Bir çekme zaten sürüyor." };
    pulling = { stop: false };
    try {
      if (!(await ensurePreview(dialog))) return { ok: false, error: "Ön izleme düğmesi bulunamadı." };
      await expandAll(dialog);
      const items = collectEvraklar(dialog).filter((item) => !item.isEk).slice(0, 2);
      if (items.length < 2) return { ok: false, error: "Deneme için en az iki evrak gerekir." };
      await chrome.runtime.sendMessage({ type: "JURISAI_PROBE_BEGIN" });
      for (const item of items) {
        await chrome.runtime.sendMessage({ type: "JURISAI_PULL_ARM", evrakId: item.id });
        realClick(item.span);
        const captured = await waitUntil(
          async () => (await chrome.runtime.sendMessage({ type: "JURISAI_PULL_STATUS" }))?.captured,
          10000,
        );
        if (!captured) return { ok: false, error: "evrak adresi yakalanamadı (ön izleme açık mı?)" };
        await sleep(700);
        const kept = await chrome.runtime.sendMessage({ type: "JURISAI_PROBE_KEEP" });
        if (!kept?.ok) return { ok: false, error: "adres saklanamadı" };
        await sleep(1500);
      }
      const result = await chrome.runtime.sendMessage({ type: "JURISAI_PROBE_RUN", attrIds: items.map((item) => item.id) });
      if (result?.ok) toast(`Deneme dosyası kaydedildi: İndirilenler\\${result.file.replace("/", "\\")}`, "success");
      else toast(`Deneme başarısız: ${result?.error || "bilinmeyen hata"}`, "error");
      return result;
    } finally {
      pulling = null;
      chrome.runtime.sendMessage({ type: "JURISAI_PULL_END" }).catch(() => {});
    }
  }

  /** Dosya listesindeki satır düğmesi: dosyayı açar, Evrak sekmesine geçer ve evrak seçim penceresini gösterir. */
  async function openCaseAndChoose(openButton) {
    if (recoveryBusy()) return toast("UYAP sayfası toparlanıyor; bitince tekrar dene.", "info");
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
    if (
      /^JURISAI_(RECORD_(START|STOP)|PULL_(DOSYA|STOP|PROBE|IDS)|LIST_DOSYALAR|OPEN_DOSYA|TREE|DETAIL|PREPARE_RECOVERY|RECOVERY_READY|JOB_STATUS|CURRENT_JOB|BRIDGE_STOP)$/.test(message?.type || "") &&
      window !== window.top
    )
      return false;
    if (message?.type === "JURISAI_PREPARE_RECOVERY") {
      sendResponse(prepareReadRecovery(String(message.jobId || "")));
      return false;
    }
    if (message?.type === "JURISAI_RECOVERY_READY") {
      sendResponse(recoveryReady());
      return false;
    }
    if (message?.type === "JURISAI_TREE") {
      sendResponse(startTreeJob(String(message.key || ""), String(message.yargiTuru || "")));
      return true;
    }
    if (message?.type === "JURISAI_DETAIL") {
      sendResponse(startDetailJob(String(message.key || ""), String(message.yargiTuru || "")));
      return true;
    }
    if (message?.type === "JURISAI_PULL_IDS") {
      sendResponse(startPullJob(message.ids, message.mode));
      return true;
    }
    if (message?.type === "JURISAI_JOB_STATUS") {
      sendResponse(jobStatus(String(message.jobId || ""), !!message.withTree, !!message.withDetail));
      return true;
    }
    if (message?.type === "JURISAI_CURRENT_JOB") {
      sendResponse(currentJob());
      return true;
    }
    if (message?.type === "JURISAI_BRIDGE_STOP") {
      sendResponse(stopJob(String(message.jobId || "")));
      return true;
    }
    if (message?.type === "JURISAI_LIST_DOSYALAR") {
      listDosyalar()
        .then(sendResponse)
        .catch((error) => sendResponse({ ok: false, error: error.message || "bilinmeyen hata" }));
      return true;
    }
    if (message?.type === "JURISAI_OPEN_DOSYA") {
      openDosyaByKey(String(message.key || ""), String(message.yargiTuru || ""))
        .then(sendResponse)
        .catch((error) => sendResponse({ ok: false, code: error.code, error: error.message || "bilinmeyen hata" }));
      return true;
    }
    if (message?.type === "JURISAI_PULL_PROBE") {
      probeDirect()
        .then(sendResponse)
        .catch((error) => sendResponse({ ok: false, error: error.message || "bilinmeyen hata" }));
      return true;
    }
    if (message?.type === "JURISAI_PULL_DOSYA") {
      pullDosya(message.mode === "disk" ? "disk" : "upload") // yalnız seçim penceresinde öne çıkan düğme
        .then(sendResponse)
        .catch((error) => sendResponse({ ok: false, error: error.message || "bilinmeyen hata" }));
      return true;
    }
    if (message?.type === "JURISAI_PULL_STOP") {
      stopPull();
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

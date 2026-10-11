/* JurisAI web uygulaması ↔ eklenti köprüsü.
   Yalnızca JurisAI sayfalarında (manifest `content_scripts`) çalışır. Sayfa `window.postMessage` ile komut yollar; yalnız
   aşağıdaki beyaz listedeki komutlar eklentiye iletilir, yanıt aynı yoldan döner. Başka sitelerdeki sayfalar bu betiğe ulaşamaz
   (betik orada yüklenmez); arka plan betiği de gönderenin JurisAI kaynağından geldiğini ayrıca denetler.
   Köprü UYAP şifresi, e-imza ya da oturum çerezi taşımaz: yalnız komut ve sonuç (dosya listesi gibi) geçer. */
(() => {
  const COMMANDS = new Set(["PING", "LIST_DOSYALAR", "OPEN_DOSYA", "SET_KEY", "TREE", "DETAIL", "RECOVER_READ", "JOB_STATUS", "CURRENT_JOB", "PULL_IDS", "STOP_JOB"]);

  function onMessage(event) {
    // Eklenti yeniden yüklendiyse bu kopya yetim kalır (chrome.runtime.id yok): yeni kopya yanıt versin.
    if (!chrome.runtime?.id) return;
    if (event.source !== window || event.origin !== location.origin) return;
    const data = event.data;
    if (!data || data.source !== "jurisai-web" || typeof data.id !== "string" || !COMMANDS.has(data.type)) return;
    const reply = (body) => window.postMessage({ source: "jurisai-extension", id: data.id, ...body }, location.origin);
    chrome.runtime
      .sendMessage({ type: `BRIDGE_${data.type}`, payload: data.payload && typeof data.payload === "object" ? data.payload : {} })
      .then((out) => reply(out || { ok: false, error: "Eklenti yanıt vermedi" }))
      .catch((error) => reply({ ok: false, error: error?.message || "Eklentiye ulaşılamadı" }));
  }

  window.__jurisaiBridgeStop?.(); // aynı dünyada eski bir kopya varsa dinleyicisini bırakır
  window.addEventListener("message", onMessage);
  window.__jurisaiBridgeStop = () => window.removeEventListener("message", onMessage);
  // Sayfa eklentiden sonra yüklenirse ya da eklenti güncellenirse yeniden algılayabilsin.
  window.postMessage(
    { source: "jurisai-extension", type: "READY", version: chrome.runtime.getManifest().version },
    location.origin,
  );
})();

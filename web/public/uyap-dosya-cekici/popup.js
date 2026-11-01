/* UYAP Dosya Çekici - popup arayüzü.
   Tüm ağır iş service worker'da; burada yalnızca durum gösterimi ve ayarlar var. */

const el = (id) => document.getElementById(id);
const SETTING_KEYS = [
  "folder",
  "apiKey",
  "apiUrl",
  "delayMs",
  "maxPages",
  "theme",
  "jurisaiToken",
  "jurisaiApiUrl",
];

const STATUS_TR = {
  waiting: "beklemede",
  sending: "gönderiliyor",
  sent: "gönderildi",
  error: "hata",
};
const esc = (t) => String(t).replace(/[<>&"]/g, (c) => `&#${c.charCodeAt(0)};`);

function renderFiles(files) {
  const box = el("fileList");
  if (!files || !files.length) {
    box.innerHTML = '<div class="hint">Liste boş. UYAP sekmesinde "Listeyi Tara"ya bas.</div>';
    return;
  }
  box.innerHTML = files
    .map(
      (f, i) => `<div class="file-row">
        <div class="file-info">
          <span class="file-name" title="${esc(f.name)}">${esc(f.name)}</span>
          <span class="file-status ${f.status}">${STATUS_TR[f.status] || f.status}${f.error ? " · " + esc(f.error) : ""}</span>
        </div>
        <div class="row tight">
          <button class="ghost small" data-send="${i}">Oku &amp; Gönder</button>
          <button class="ghost small" data-dl="${i}">İndir</button>
        </div>
      </div>`,
    )
    .join("");
  box.querySelectorAll("[data-send]").forEach((btn) => {
    btn.addEventListener("click", () => {
      btn.disabled = true;
      chrome.runtime
        .sendMessage({ type: "UYAP_SEND_ONE", url: files[Number(btn.dataset.send)].url })
        .catch(() => {});
    });
  });
  box.querySelectorAll("[data-dl]").forEach((btn) => {
    btn.addEventListener("click", () => {
      chrome.runtime
        .sendMessage({ type: "UYAP_DOWNLOAD_ONE", url: files[Number(btn.dataset.dl)].url })
        .catch(() => {});
    });
  });
}

async function refreshSession() {
  const data = await chrome.storage.local.get(["jurisaiToken"]);
  el("keyState").textContent =
    (data.jurisaiToken || "").length >= 8 ? "•••• kayıtlı" : "tanımlı değil";
  const info = await chrome.runtime.sendMessage({ type: "UYAP_SESSION_INFO" }).catch(() => null);
  el("sessionState").textContent = info?.active
    ? `✓ açık${info.user ? " · " + info.user : ""}`
    : `✗ ${info?.reason || "kapalı"}`;
}

function renderState(state) {
  if (!state) return;
  const total = state.total || 0;
  const done = state.done || 0;
  const pct = total ? Math.round((done / total) * 100) : 0;
  el("bar").style.width = `${pct}%`;
  el("percent").textContent = `%${pct}`;
  el("counter").textContent = `${done} / ${total}`;
  el("okCount").textContent = state.ok || 0;
  el("failCount").textContent = state.failed || 0;
  el("stateText").textContent = state.running ? "çalışıyor" : "hazır";
  el("startBtn").disabled = !!state.running;
  el("autoBtn").disabled = !!state.running;
  el("stopBtn").disabled = !state.running;

  const logs = state.logs || [];
  el("logs").innerHTML = logs.length
    ? logs
        .map((entry) => {
          const time = new Date(entry.at).toLocaleTimeString("tr-TR");
          const text = `${time} · ${entry.message}`.replace(
            /[<>&]/g,
            (c) => `&#${c.charCodeAt(0)};`,
          );
          return `<div class="log ${entry.level}">${text}</div>`;
        })
        .join("")
    : '<div class="log info">Günlük boş.</div>';
  el("logs").scrollTop = el("logs").scrollHeight;
  renderFiles(state.files);
}

async function loadSettings() {
  const data = await chrome.storage.local.get(SETTING_KEYS);
  el("folder").value = data.folder || "UYAP";
  el("apiKey").value = data.apiKey || "";
  el("apiUrl").value = data.apiUrl || "";
  el("delay").value = data.delayMs || 700;
  el("maxPages").value = data.maxPages || 50;
  el("jurisaiToken").value = data.jurisaiToken || "";
  el("jurisaiApiUrl").value = data.jurisaiApiUrl || "http://localhost:8766";
  if (data.theme === "dark") document.body.classList.add("dark");
}

el("saveBtn").addEventListener("click", async () => {
  await chrome.storage.local.set({
    folder: (el("folder").value.trim() || "UYAP").replace(/[^\w\-./]+/g, "_"),
    apiKey: el("apiKey").value.trim(),
    apiUrl: el("apiUrl").value.trim(),
    delayMs: Math.min(5000, Math.max(200, Number(el("delay").value) || 700)),
    maxPages: Math.min(200, Math.max(1, Number(el("maxPages").value) || 50)),
    jurisaiToken: el("jurisaiToken").value.trim(),
    jurisaiApiUrl: (el("jurisaiApiUrl").value.trim() || "http://localhost:8766").replace(/\/$/, ""),
  });
  el("saveMsg").textContent = "Ayarlar kaydedildi.";
  refreshSession();
  setTimeout(() => (el("saveMsg").textContent = ""), 2000);
});

el("startBtn").addEventListener("click", async () => {
  el("startBtn").disabled = true;
  const res = await chrome.runtime.sendMessage({ type: "UYAP_START" }).catch(() => null);
  if (res && res.ok === false) el("saveMsg").textContent = res.error || "Başlatılamadı.";
});

el("autoBtn").addEventListener("click", async () => {
  el("autoBtn").disabled = true;
  const res = await chrome.runtime.sendMessage({ type: "UYAP_AUTO_START" }).catch(() => null);
  if (res && res.ok === false) el("saveMsg").textContent = res.error || "Otomasyon başlatılamadı.";
});

el("scanBtn").addEventListener("click", async () => {
  el("scanBtn").disabled = true;
  el("scanBtn").textContent = "Taranıyor…";
  const res = await chrome.runtime.sendMessage({ type: "UYAP_SCAN" }).catch(() => null);
  el("scanBtn").disabled = false;
  el("scanBtn").textContent = "Listeyi Tara";
  if (res?.files) renderFiles(res.files);
  else el("saveMsg").textContent = res?.error || "Liste alınamadı.";
});

el("stopBtn").addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "UYAP_STOP" }).catch(() => {});
});

el("clearBtn").addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "UYAP_CLEAR_LOGS" }).catch(() => {});
});

el("openBtn").addEventListener("click", () => {
  chrome.tabs.create({ url: "chrome://downloads" });
});

el("themeToggle").addEventListener("click", async () => {
  const dark = document.body.classList.toggle("dark");
  await chrome.storage.local.set({ theme: dark ? "dark" : "light" });
});

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "UYAP_STATE") renderState(message.state);
});

(async function init() {
  await loadSettings();
  await refreshSession();
  const res = await chrome.runtime.sendMessage({ type: "UYAP_GET_STATE" }).catch(() => null);
  if (res?.state) renderState(res.state);
  else {
    const { uyapState } = await chrome.storage.local.get("uyapState");
    if (uyapState) renderState(uyapState);
  }
})();

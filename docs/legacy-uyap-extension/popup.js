const tokenEl = document.getElementById("token");
const apiEl = document.getElementById("api");
const msgEl = document.getElementById("msg");

chrome.storage.sync.get(["jurisaiToken", "jurisaiApiUrl"], (data) => {
  if (data.jurisaiToken) tokenEl.value = data.jurisaiToken;
  apiEl.value = data.jurisaiApiUrl || "http://localhost:8766";
});

document.getElementById("save").addEventListener("click", () => {
  const token = tokenEl.value.trim();
  const apiUrl = (apiEl.value.trim() || "http://localhost:8766").replace(/\/$/, "");
  if (token.length < 20) {
    msgEl.style.color = "#fca5a5";
    msgEl.textContent = "Geçerli bir bağlantı anahtarı gir.";
    return;
  }
  chrome.storage.sync.set({ jurisaiToken: token, jurisaiApiUrl: apiUrl }, () => {
    msgEl.style.color = "#86efac";
    msgEl.textContent = "Kaydedildi. UYAP sayfasını yenile.";
  });
});

/* Office.js task pane: no document text/token persisted in browser storage. */
"use strict";
const byId = (id) => document.getElementById(id);
const api = ["localhost", "127.0.0.1"].includes(location.hostname)
  ? "http://localhost:8766"
  : location.origin;
let token = "",
  epoch = 0,
  jobId = "",
  timer,
  officeReady = false;
const status = (message, error = false) => {
  byId("status").textContent = message;
  byId("status").dataset.error = String(error);
};
async function request(path, body, access = token) {
  const response = await fetch(api + path, {
    method: body === undefined ? "GET" : "POST",
    credentials: "omit",
    headers: {
      ...(access ? { Authorization: "Bearer " + access } : {}),
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      typeof result?.detail === "string"
        ? result.detail
        : `İşlem tamamlanamadı (${response.status}).`,
    );
  return result;
}
function reset() {
  epoch++;
  clearTimeout(timer);
  token = "";
  jobId = "";
  byId("input").value = "";
  byId("output").value = "";
  byId("insert").disabled = true;
  byId("start").disabled = false;
  byId("cancel").hidden = true;
  byId("workspace").hidden = true;
  byId("login").hidden = false;
}
Office.onReady((info) => {
  officeReady =
    info.host === Office.HostType.Word &&
    Office.context.requirements.isSetSupported("WordApi", "1.1");
  if (!officeReady) status("Bu bölmeyi Word içinde açın. WordApi 1.1 desteği gerekiyor.", true);
});
byId("login").addEventListener("submit", async (event) => {
  event.preventDefault();
  const generation = epoch;
  const button = event.submitter;
  button.disabled = true;
  const password = byId("password").value;
  byId("password").value = "";
  try {
    const result = await request(
      "/api/auth/login",
      { email: byId("email").value.trim(), password },
      "",
    );
    if (generation !== epoch) return;
    if (typeof result.access_token !== "string") throw new Error("Giriş jetonu alınamadı.");
    token = result.access_token;
    byId("login").hidden = true;
    byId("workspace").hidden = false;
    status("Bağlandı. Göndermek istediğiniz metni seçin.");
  } catch (error) {
    if (generation === epoch) status(error.message, true);
  } finally {
    button.disabled = false;
  }
});
byId("logout").onclick = () => {
  reset();
  status("Bağlantı kapatıldı. Sunucuda başlamış iş ayrıca durdurulmadı.");
};
async function readWord(full) {
  if (!officeReady) return status("Word bağlantısı henüz hazır değil.", true);
  const generation = epoch;
  try {
    await Word.run(async (context) => {
      const range = full ? context.document.body : context.document.getSelection();
      range.load("text");
      await context.sync();
      if (generation !== epoch) return;
      if (range.text.length > 2000000)
        throw new Error("Metin 2 milyon karakter sınırını aşıyor; belgeyi bölerek gönderin.");
      byId("input").value = range.text;
      byId("scope").textContent =
        `${full ? "Açık belgenin metni" : "Word seçimi"}: ${range.text.length.toLocaleString("tr-TR")} karakter. Henüz gönderilmedi.`;
    });
  } catch (error) {
    if (generation === epoch) status(error.message, true);
  }
}
byId("selection").onclick = () => readWord(false);
byId("body").onclick = () => readWord(true);
byId("start").onclick = async () => {
  const generation = epoch,
    access = token,
    text = byId("input").value;
  if (!text.trim()) return status("Önce gönderilecek metni seçin.", true);
  byId("start").disabled = true;
  byId("output").value = "";
  byId("insert").disabled = true;
  try {
    const result = await request(
      "/api/office-ai/jobs",
      {
        module: byId("module").value,
        text,
        title: "Word belge çalışması",
        prompt: "Belgeyi incele; eksik veya doğrulanamayan bilgileri açıkça belirt.",
      },
      access,
    );
    if (generation !== epoch) return;
    jobId = result.job_id;
    byId("cancel").hidden = false;
    const poll = async () => {
      try {
        const job = await request(
          "/api/office-ai/jobs/" + encodeURIComponent(jobId),
          undefined,
          access,
        );
        if (generation !== epoch) return;
        status(`${job.state} · ${job.progress.done}/${job.progress.total} belge`);
        if (["queued", "running"].includes(job.state)) timer = setTimeout(poll, 2500);
        else {
          byId("start").disabled = false;
          byId("cancel").hidden = true;
          byId("output").value = job.output || "";
          byId("insert").disabled = !job.output;
          if (job.error) status(job.error, true);
        }
      } catch (error) {
        if (generation === epoch) {
          status(error.message + " JurisAI'daki Belge iş kuyruğundan da sürdürebilirsiniz.", true);
          byId("start").disabled = false;
        }
      }
    };
    await poll();
  } catch (error) {
    if (generation === epoch) {
      status(error.message, true);
      byId("start").disabled = false;
    }
  }
};
byId("cancel").onclick = async () => {
  try {
    await request("/api/office-ai/jobs/" + encodeURIComponent(jobId) + "/cancel", {});
    status("İş durduruldu; halen çalışan model çağrısı tamamlanana kadar bekleyebilir.");
  } catch (error) {
    status(error.message, true);
  }
};
byId("insert").onclick = async () => {
  const text = byId("output").value;
  if (!officeReady || !text) return;
  try {
    await Word.run(async (context) => {
      context.document.getSelection().insertText("\n\n" + text, Word.InsertLocation.after);
      await context.sync();
    });
    status("Sonuç seçimin sonuna eklendi. Mevcut metin korunuyor.");
  } catch (error) {
    status(error.message, true);
  }
};
window.addEventListener("pagehide", reset);

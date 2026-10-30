import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(
  new URL("../public/jurisai-avukat/background.js", import.meta.url),
  "utf8",
);
// Anonymized structure of the user-supplied UYAP Hata.html. Never execute it.
const errorPage =
  "<html><head><title>UYAP Internet Adli Bilgi Sistemi</title></head><body>" +
  '<h1>Hata Oluştu</h1><table><tr><a href="/">Ana Sayfa</a>' +
  '<a href="/kill_session.uyap">Güvenli Çıkış</a></tr><tr><td><b>Hata Mesajı:</b></td>' +
  "<td>Doğrulama hatası.Lütfen tekrar deneyiniz.</td></tr></table></body></html>";
const url = "https://vatandas.uyap.gov.tr/view_document_brd.uyap?evrakId=opaque";

function harness(type, { captured = true, body = errorPage, status = 200 } = {}) {
  const calls = [];
  let sleeps = 0;
  let uploads = 0;
  const context = vm.createContext({
    Blob,
    URL,
    TextDecoder,
    AbortController,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    DEFAULTS: { timeoutMs: 45000 },
    pull: null,
    pullRun: null,
    getSettings: async () => ({ timeoutMs: 1000 }),
    pullTargetUrl: () => (captured ? url : ""),
    sleep: async () => {
      sleeps++;
    },
    uploadDocument: async () => {
      uploads++;
      return {};
    },
    fetch: async (target) => {
      calls.push(target);
      return new Response(typeof body === "function" ? body(calls.length) : body, {
        status,
        headers: { "Content-Type": typeof type === "function" ? type(calls.length) : type },
      });
    },
  });
  vm.runInContext(
    source.slice(
      source.indexOf("const SITE_HOST_RE ="),
      source.indexOf("async function saveLocally("),
    ) +
      source.slice(
        source.indexOf("function acceptedDirectUrl("),
        source.indexOf("/* ---------- Doğrudan indirme denemesi ----------"),
      ) +
      "\nglobalThis.helpers = {fetchDocument, handlePullFetch, isUyapReceipt, isUyapKepDocument};",
    context,
  );
  return { ...context.helpers, calls, stats: () => ({ sleeps, uploads }) };
}

for (const type of ["text/html", "application/download", "application/zip"]) {
  test(`validation error disguised as ${type} is rejected without claiming session expiry`, async () => {
    const h = harness(type);
    await assert.rejects(
      h.fetchDocument(url, 1000, { evrakTuru: "Ek", evrakAdi: "Ek 41" }),
      (error) => {
        assert.equal(error.code, "UYAP_VALIDATION_FAILED");
        assert.equal(error.notDocument, true);
        assert.equal(error.freshRequestRequired, true);
        assert.notEqual(error.retryable, true);
        assert.match(error.message, /Doğrulama hatası/);
        assert.doesNotMatch(error.message, /oturum kapanmış olabilir|opaque|kill_session/);
        return true;
      },
    );
  });
}

for (const captured of [true, false]) {
  test(`validation rejection does not retry the rejected URL or derive a save URL (${captured ? "captured" : "direct"})`, async () => {
    const h = harness("application/download", { captured });
    const result = await h.handlePullFetch(
      { evrakTuru: "Ek", evrakAdi: "Ek 41" },
      "upload",
      captured ? "" : url,
    );
    assert.equal(result.ok, false);
    assert.equal(result.code, "UYAP_VALIDATION_FAILED");
    assert.deepEqual(h.calls, [url]);
    assert.deepEqual(h.stats(), { sleeps: 0, uploads: 0 });
  });
}

test("validation error cannot borrow the receipt or KEP HTML exception", async () => {
  const body = errorPage.replace(
    "</body>",
    "<div>VEKALET PULU MAKBUZU ADALET BAKANLIĞI Makbuz No 123</div>" +
      "<div>KEP İletisi: kurum@banka.com.tr Konu: Yanıt Tarih: 01.01.2025</div></body>",
  );
  const h = harness("text/html", { body });
  const blob = new Blob([body]);
  assert.equal(await h.isUyapReceipt(blob, { evrakTuru: "Ek", evrakAdi: "Ek 41" }), false);
  assert.equal(await h.isUyapKepDocument(blob, { evrakTuru: "Ek", evrakAdi: "Ek 41" }), false);
  await assert.rejects(
    h.fetchDocument(url, 1000, { evrakTuru: "Ek", evrakAdi: "Ek 41" }),
    (error) => error.code === "UYAP_VALIDATION_FAILED",
  );
});

test("validation rejected by the save endpoint is preserved instead of repeating preview or save", async () => {
  const h = harness((n) => (n === 1 ? "text/plain" : "application/download"), {
    body: (n) =>
      n === 1 ? "Evrakın boyutu çok büyük. Evrakı sisteminize kaydederek açınız." : errorPage,
  });
  const result = await h.handlePullFetch({ evrakTuru: "Ek", evrakAdi: "Ek 41" });
  assert.equal(result.ok, false);
  assert.equal(result.code, "UYAP_VALIDATION_FAILED");
  assert.deepEqual(h.calls, [url, url.replace("view_document", "download_document")]);
  assert.deepEqual(h.stats(), { sleeps: 0, uploads: 0 });
});

for (const saveFailure of [
  { message: "synthetic abort", name: "AbortError" },
  {
    message: "UYAP 120 sn boyunca veri göndermedi; indirme durdu (19.4 MB geldi).",
    retryable: true,
  },
  { message: "HTTP 503" },
  { message: "HTTP 429" },
])
  test(`direct save failure stays transient: ${saveFailure.message}`, async () => {
    const h = harness((n) => (n === 1 ? "text/plain" : "application/zip"), {
      captured: false,
      body: (n) => {
        if (n === 1) return "Evrakın boyutu çok büyük. Evrakı sisteminize kaydederek açınız.";
        throw Object.assign(new Error(saveFailure.message), saveFailure);
      },
    });
    const result = await h.handlePullFetch({ evrakTuru: "Ek", evrakAdi: "Ek 41" }, "upload", url);
    assert.equal(result.ok, false);
    assert.equal(
      result.retryable,
      true,
      "a transient save failure must allow the caller to capture a fresh normal UI request",
    );
    assert.match(result.error, /Kaydet.*alınamadı/);
    assert.deepEqual(h.stats(), { sleeps: 0, uploads: 0 });
  });

test("an HTTP 403 save refusal does not masquerade as a transient download interruption", async () => {
  const h = harness("text/plain", {
    captured: false,
    body: (n) => {
      if (n === 1) return "Evrakın boyutu çok büyük. Evrakı sisteminize kaydederek açınız.";
      throw new Error("HTTP 403");
    },
  });
  const result = await h.handlePullFetch({ evrakTuru: "Ek", evrakAdi: "Ek 41" }, "upload", url);
  assert.equal(result.ok, false);
  assert.notEqual(result.retryable, true);
  assert.match(result.error, /Kaydet.*HTTP 403/);
  assert.deepEqual(h.stats(), { sleeps: 0, uploads: 0 });
});

test("a real document quoting validation words is not mistaken for the UYAP error template", async () => {
  const body =
    "<html><body>KEP İletisi: kurum@banka.com.tr Konu: Doğrulama hatası Tarih: 01.01.2025</body></html>";
  const h = harness("text/html", { body });
  assert.equal((await h.fetchDocument(url, 1000, { evrakTuru: "KEP Cevabı" })).type, "text/html");
});

test("generic UYAP error with logout navigation and an internal service URL is not session expiry", async () => {
  const body =
    "<html><head><title>UYAP Internet Adli Bilgi Sistemi</title></head><body>" +
    '<h1>Hata Oluştu</h1><a href="/kill_session.uyap">Güvenli Çıkış</a>' +
    "<b>Hata Mesajı:</b> http://avukatic.uyap.gov.tr/AVUKATWeb/servis erişilemedi</body></html>";
  const h = harness("application/download", { body });
  await assert.rejects(h.fetchDocument(url, 1000), (error) => {
    assert.equal(error.code, "UYAP_PORTAL_ERROR");
    assert.equal(error.retryable, true);
    assert.doesNotMatch(error.message, /oturum kapanmış olabilir/);
    return true;
  });
  assert.equal(h.stats().uploads, 0);
});

for (const body of [
  "<html><body>OTURUMUNUZ SONA ERDİ. Yeniden giriş yapınız.</body></html>",
  "<html><body>Oturum süresi dolmuştur.</body></html>",
  "<html><body>" + "Başlık ".repeat(80) + "Geçerli bir oturum bulunamadı.</body></html>",
  "<html><head><title>UYAP Giriş Ekranı</title></head><body>Kimliğinizi doğrulayın</body></html>",
  '<html><form><input type="password"></form></html>',
])
  test(
    "explicit login evidence stops without retrying preview or save: " + body.slice(0, 65),
    async () => {
      const h = harness("application/download", { body });
      const result = await h.handlePullFetch({ evrakTuru: "Ek", evrakAdi: "Ek 1" });
      assert.equal(result.ok, false);
      assert.equal(result.code, "UYAP_SESSION_EXPIRED");
      assert.notEqual(result.retryable, true);
      assert.deepEqual(h.calls, [url]);
      assert.deepEqual(h.stats(), { sleeps: 0, uploads: 0 });
    },
  );

for (const [status, code] of [
  [401, "UYAP_SESSION_EXPIRED"],
  [403, "UYAP_ACCESS_DENIED"],
]) {
  test(`HTTP ${status} is classified without speculative save/retry requests`, async () => {
    const h = harness("text/plain", { body: "Ret", status });
    const result = await h.handlePullFetch({ evrakTuru: "Ek", evrakAdi: "Ek 1" });
    assert.equal(result.code, code);
    assert.deepEqual(h.calls, [url]);
    assert.deepEqual(h.stats(), { sleeps: 0, uploads: 0 });
  });
}

test("an explicit permission refusal is a document/access error, not session expiry", async () => {
  const h = harness("text/html", {
    body: "<html><body>Bu evrağı görüntüleme yetkiniz yok.</body></html>",
  });
  const result = await h.handlePullFetch({ evrakTuru: "Karar" });
  assert.equal(result.code, "UYAP_ACCESS_DENIED");
  assert.notEqual(result.retryable, true);
  assert.deepEqual(h.calls, [url]);
});

for (const [body, code] of [
  ["Oturumunuz sona erdi. Yeniden giriş yapınız.", "UYAP_SESSION_EXPIRED"],
  ["Bu evrağı görüntüleme yetkiniz yok (kod 777).", "UYAP_ACCESS_DENIED"],
])
  test("short plain-text refusal preserves the auth/access distinction: " + code, async () => {
    const h = harness("text/plain; charset=utf-8", { body });
    const result = await h.handlePullFetch({ evrakTuru: "Karar" });
    assert.equal(result.code, code);
    assert.notEqual(result.retryable, true);
    assert.deepEqual(h.calls, [url]);
    assert.deepEqual(h.stats(), { sleeps: 0, uploads: 0 });
  });

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

// Production classification code, synthetic content only; no account/case or
// live portal is required to exercise the format contract.
const source = readFileSync(
  new URL("../public/jurisai-avukat/background.js", import.meta.url),
  "utf8",
);
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
  fetch: async () => {
    throw Error("unexpected network");
  },
});
vm.runInContext(
  source.slice(
    source.indexOf("function fileNameFor("),
    source.indexOf("async function saveLocally("),
  ) + "\nglobalThis.h = {fileNameFor,fetchDocument,isUyapKepDocument,isUyapReceipt};",
  context,
);
const h = context.h;
const url = "https://vatandas.uyap.gov.tr/view_document_brd.uyap?evrakId=synthetic";
const kep =
  "<html><body>KEP İletisi: kurum@hs01.kep.tr Konu: Yanıt Tarih: 01.01.2025</body></html>";

for (const label of [
  "Karar",
  "Bankadan Gelen Cevap Yazısı",
  "Ek",
  "Diğer Evrak",
  "Bilinmeyen tür",
  "",
  null,
]) {
  test(`KEP format recognition is independent of the account's label: ${label}`, async () => {
    context.fetch = async () =>
      new Response(kep, { headers: { "Content-Type": "application/download" } });
    const out = await h.fetchDocument(url, 1000, label === null ? null : { evrakTuru: label });
    assert.equal(out.type, "text/html");
    assert.equal(await out.blob.text(), kep);
  });
}

for (const extension of [
  "bin",
  "dat",
  "enc",
  "dcm",
  "heic",
  "webm",
  "flac",
  "gz",
  "tar",
  "customformat",
  "exe",
  "ps1",
  "js",
  "msi",
  "lnk",
  "svg",
]) {
  test(`unknown ${extension} is preserved as opaque bytes, never renamed to PDF`, async () => {
    const raw = new Uint8Array([0x80, 0, 1, 2, 3, 0xff]);
    context.fetch = async () =>
      new Response(raw, { headers: { "Content-Type": "application/download" } });
    const out = await h.fetchDocument(url, 1000, { evrakAdi: "Attachment" });
    assert.deepEqual(new Uint8Array(await out.blob.arrayBuffer()), raw);
    const name = h.fileNameFor({ evrakAdi: "Attachment", fileExt: extension }, out.type);
    assert.equal(name, extension === "bin" ? "Attachment.bin" : `Attachment.${extension}.bin`);
    assert.notEqual(out.type, "application/pdf");
  });
}

test("short genuine named text attachments are not classified as portal messages", async () => {
  for (const [extension, type, text] of [
    ["txt", "text/plain", "Sentetik kısa belge"],
    ["csv", "text/csv", "a,b\n1,2"],
    ["eml", "text/plain", "From: example@example.test\nSubject: Test\n\nBody"],
  ]) {
    context.fetch = async () =>
      new Response(text, {
        headers: {
          "Content-Type": type,
          "Content-Disposition": `attachment; filename="document.${extension}"`,
        },
      });
    const out = await h.fetchDocument(url, 1000);
    assert.equal(await out.blob.text(), text);
    assert.equal(out.filename, `document.${extension}`);
  }
});

test("generic passive HTML requires a real named attachment, not a tree label", async () => {
  const body =
    "<html><head><title>Belge</title></head><body>Sentetik belge içeriği ve açıklaması.</body></html>";
  context.fetch = async () =>
    new Response(body, {
      headers: {
        "Content-Type": "text/html",
        "Content-Disposition": 'attachment; filename="document.html"',
      },
    });
  const out = await h.fetchDocument(url, 1000, { evrakTuru: "Herhangi bir tür" });
  assert.equal(await out.blob.text(), body);
  context.fetch = async () => new Response(body, { headers: { "Content-Type": "text/html" } });
  await assert.rejects(h.fetchDocument(url, 1000), (error) => error.notDocument === true);
});

for (const [type, body] of [
  ["application/octet-stream", '<div><input type="password">Giriş yap</div>'],
  [
    "application/octet-stream",
    "<!-- portal response -->\n<html><body>Oturumunuz sona erdi</body></html>",
  ],
  ["application/download", "<html><body>Hata Oluştu Hata Mesajı: Doğrulama hatası.</body></html>"],
  ["application/pdf", "<html><body>Oturumunuz sona erdi</body></html>"],
  [
    "text/html",
    "<html><body>KEP İletisi: kurum@hs01.kep.tr Konu: X Tarih: 01.01.2025<script>void(0)</script></body></html>",
  ],
  ["text/plain", "Oturumunuz sona erdi"],
  [
    "text/html",
    "<html><head><title>Hata</title></head><body>Bağlantı kurulamadı. Tekrar deneyin.</body></html>",
  ],
])
  test(`portal/active response stays an error despite attachment headers and ${type}`, async () => {
    context.fetch = async () =>
      new Response(body, {
        headers: {
          "Content-Type": type,
          "Content-Disposition": 'attachment; filename="document.html"',
        },
      });
    await assert.rejects(
      h.fetchDocument(url, 1000, { evrakTuru: "Bankadan Gelen Cevap Yazısı" }),
      (error) => error.notDocument === true,
    );
  });

test("UTF-16 login pages cannot hide under an unknown binary MIME", async () => {
  const bytes = new Uint8Array(
    Buffer.from("\ufeff<html><body>Oturumunuz sona erdi</body></html>", "utf16le"),
  );
  context.fetch = async () =>
    new Response(bytes, { headers: { "Content-Type": "application/octet-stream" } });
  await assert.rejects(
    h.fetchDocument(url, 1000),
    (error) => error.notDocument === true && error.code === "UYAP_SESSION_EXPIRED",
  );
});

test("HTTP 200 JSON errors and octet-stream login messages are not opaque documents", async () => {
  for (const [type, body] of [
    ["application/json", '{"ok":false,"error":"synthetic failure"}'],
    ["application/octet-stream", "Oturumunuz sona erdi"],
    ["application/download", "Yetkiniz bulunmamaktadır"],
  ]) {
    context.fetch = async () => new Response(body, { headers: { "Content-Type": type } });
    await assert.rejects(h.fetchDocument(url, 1000), (error) => error.notDocument === true);
  }
  const genuine = '{"error":"synthetic log file content"}';
  context.fetch = async () =>
    new Response(genuine, {
      headers: {
        "Content-Type": "application/json",
        "Content-Disposition": 'attachment; filename="log.json"',
      },
    });
  assert.equal(await (await h.fetchDocument(url, 1000)).blob.text(), genuine);
});

test("opaque names are bounded, traversal-safe and keep the final inert suffix", () => {
  const name = h.fileNameFor(
    { evrakAdi: "../" + "X".repeat(300) + ".bin" },
    "application/download",
  );
  assert.ok(name.endsWith(".bin"));
  assert.ok(name.length <= 144);
  assert.doesNotMatch(name, /[\\/]/);
});

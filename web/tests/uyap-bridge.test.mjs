import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";

const require = createRequire(import.meta.url);
function compile(relative) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(require, module, module.exports);
  return module.exports;
}

const bridge = compile("../src/lib/uyap-bridge.ts");

/** window.postMessage/addEventListener'ı taklit eden küçük bir ortam; `onPost` eklentinin yerine yanıtı üretir. */
function fakeWindow(onPost) {
  const listeners = new Set();
  const origin = "https://jurisai.example";
  const fake = {
    location: { origin },
    addEventListener: (_type, listener) => listeners.add(listener),
    removeEventListener: (_type, listener) => listeners.delete(listener),
    postMessage: (message, targetOrigin) => {
      assert.equal(targetOrigin, origin); // yalnız kendi kaynağına gönderir
      onPost(message, (data, options = {}) => {
        for (const listener of [...listeners])
          listener({ source: options.source ?? fake, origin: options.origin ?? origin, data });
      });
    },
    listenerCount: () => listeners.size,
  };
  globalThis.window = fake;
  return fake;
}

test("a request resolves with the extension's reply and cleans up its listener", async () => {
  const fake = fakeWindow((message, deliver) => {
    assert.equal(message.source, "jurisai-web");
    assert.equal(message.type, "PING");
    deliver({ source: "jurisai-extension", id: message.id, ok: true, version: "2.21.0", connected: true });
  });
  const status = await bridge.detectExtension(500);
  assert.deepEqual(status, { installed: true, version: "2.21.0", connected: true });
  assert.equal(fake.listenerCount(), 0);
});

test("no reply means the extension is not installed (timeout) and nothing leaks", async () => {
  const fake = fakeWindow(() => {});
  const reply = await bridge.bridgeRequest("PING", {}, 30);
  assert.equal(reply.ok, false);
  assert.equal(reply.code, "timeout");
  assert.equal(fake.listenerCount(), 0);
  assert.deepEqual(await bridge.detectExtension(30), { installed: false });
});

test("replies from another window, origin or request id are ignored", async () => {
  fakeWindow((message, deliver) => {
    deliver({ source: "jurisai-extension", id: message.id, ok: true, version: "evil" }, { origin: "https://evil.example" });
    deliver({ source: "jurisai-extension", id: message.id, ok: true, version: "evil" }, { source: {} });
    deliver({ source: "jurisai-extension", id: "baska-istek", ok: true, version: "evil" });
    deliver({ source: "baska", id: message.id, ok: true, version: "evil" });
    deliver({ source: "jurisai-extension", id: message.id, ok: true, version: "real", connected: false });
  });
  assert.deepEqual(await bridge.detectExtension(500), { installed: true, version: "real", connected: false });
});

test("a failure reply keeps its message and code", async () => {
  fakeWindow((message, deliver) => {
    deliver({ source: "jurisai-extension", id: message.id, ok: false, code: "no_uyap_tab", error: "UYAP sekmesi yok" });
  });
  const result = await bridge.listUyapDosyalari();
  assert.deepEqual(result, { ok: false, code: "no_uyap_tab", error: "UYAP sekmesi yok" });
});

test("the dosya list is parsed defensively", async () => {
  const liste = bridge.parseDosyaListe({
    items: [
      { key: "a#1", esas: "2024/124", birim: "Ankara 33. Ağır Ceza Mahkemesi", cells: ["2024/124", "Ankara 33. Ağır Ceza Mahkemesi", "Ceza"] },
      { key: "", esas: "x" }, // anahtarsız satır atılır
      null,
      "bozuk",
      { key: "b#1", cells: "liste-değil", esas: 5 },
      { key: "c#1", esas: "x".repeat(500), cells: ["  çok   boşluklu  ", ""] },
    ],
    pages: 3,
    page: 1,
  });
  assert.equal(liste.items.length, 3);
  assert.deepEqual(liste.items[1], { key: "b#1", esas: "", birim: "", cells: [] });
  assert.equal(liste.items[2].esas.length, 60);
  assert.deepEqual(liste.items[2].cells, ["çok boşluklu"]);
  assert.equal(liste.pages, 3);
  assert.equal(liste.page, 1);
  assert.deepEqual(bridge.parseDosyaListe(null), { items: [], pages: null, page: null });
  assert.equal(bridge.parseDosyaListe({ pages: -1, page: "2" }).pages, null);
  assert.deepEqual(bridge.otherCells(liste.items[0]), ["Ceza"]);
});

test("opening a dosya sends its key to the extension", async () => {
  let sent;
  fakeWindow((message, deliver) => {
    sent = message;
    deliver({ source: "jurisai-extension", id: message.id, ok: true });
  });
  const reply = await bridge.openUyapDosya("a#1");
  assert.equal(reply.ok, true);
  assert.equal(sent.type, "OPEN_DOSYA");
  assert.deepEqual(sent.payload, { key: "a#1" });
});

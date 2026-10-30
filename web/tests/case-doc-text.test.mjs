import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function load(relative) {
  const code = readFileSync(new URL(relative, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(code, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("module", "exports", outputText)(module, module.exports);
  return module.exports;
}
const { docTextState, docTextNote, docSourceLabel, READING_WINDOW_MS } = load(
  "../src/lib/case-doc-text.ts",
);
const now = Date.parse("2026-10-06T09:00:00Z");

test("metni okunmuş belge hazırdır ve satırına ek yazılmaz", () => {
  assert.equal(docTextState("Kira sözleşmesi…", "2026-10-01T09:00:00Z", now), "ready");
  assert.equal(docTextNote("ready"), "");
});

test("yeni yüklenen belge okunana kadar 'çıkarılamadı' diye gösterilmez", () => {
  assert.equal(docTextState(null, "2026-10-06T08:59:50Z", now), "reading");
  assert.equal(docTextState("   ", "2026-10-06T08:59:50Z", now), "reading");
  assert.equal(docTextNote("reading"), "metni okunuyor…");
});

test("okuma süresi geçtiği hâlde metni olmayan belge okunamamış sayılır", () => {
  const old = new Date(now - READING_WINDOW_MS - 1000).toISOString();
  assert.equal(docTextState("", old, now), "none");
  assert.equal(docTextState(null, null, now), "none");
  assert.equal(docTextState(null, "tarih değil", now), "none");
  assert.equal(docTextNote("none"), "metin çıkarılamadı");
});

test("kaynak teknik adıyla değil, anlaşılır adıyla gösterilir", () => {
  assert.equal(docSourceLabel("manual"), "Elle yüklendi");
  assert.equal(docSourceLabel(null), "Elle yüklendi");
  assert.equal(docSourceLabel("uyap-avukat-eklentisi"), "UYAP");
  assert.equal(docSourceLabel("e-posta"), "e-posta");
});

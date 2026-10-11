import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
const require = createRequire(import.meta.url);
function compile(path, deps) {
  const { outputText } = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(n => deps[n] ?? require(n), module, module.exports);
  return module.exports;
}
const sync = compile("../src/lib/uyap-sync-all.ts", { "@/lib/uyap-bridge": {}, "@/lib/steady-timer": {} });
function render(loaded, user = "alice") {
  const { UyapRunHistory } = compile("../src/components/UyapRunHistory.tsx", {
    react: { useState: () => [loaded, () => {}], useEffect() {}, useSyncExternalStore: () => ({ savedVersion: 1 }) },
    "@/components/AuthProvider": { useAuth: () => ({ user: { id: user } }) },
    "@/lib/uyap-sync-api": { loadAuditRuns() { throw new Error("History rendering must not start a transfer"); } },
    "@/lib/uyap-sync-store": {}, "@/lib/uyap-sync-all": sync,
  });
  return renderToStaticMarkup(createElement(UyapRunHistory));
}
test("history explains loading, unavailable and empty separately", () => {
  assert.match(render(undefined), /Raporlar yükleniyor/);
  assert.match(render({ ownerId: "alice", runs: null }), /okunamadı; rapor yok olarak kabul edilmedi/);
  assert.match(render({ ownerId: "alice", runs: [] }), /Henüz tam koşu raporu kaydedilmedi/);
});
test("account switch never flashes the old owner's report", () => {
  assert.match(render({ ownerId: "alice", runs: [] }, "bob"), /Raporlar yükleniyor/);
  assert.doesNotMatch(render({ ownerId: "alice", runs: [] }, "bob"), /Henüz tam koşu raporu/);
});
test("unfinished full report is expandable, dated and escaped; pending is not empty", () => {
  const reports = [sync.blankReport({ key: "k", esas: "2026/1", birim: "<script>private</script>", yargiTuru: "İcra" })];
  const saved = { id: "1", finished: false, verifyOnly: true, listComplete: true, updatedAt: "2026-10-09T10:00:00Z",
    run: { reports, summary: sync.summarize(reports), aborted: false } };
  const html = render({ ownerId: "alice", runs: [saved] });
  assert.match(html, /<details/);
  assert.match(html, /Yarım kalmış koşu kaydı/);
  assert.match(html, /İŞLENMEDİ/);
  assert.match(html, /&lt;script&gt;private&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>|EVRAK YOK/);
});

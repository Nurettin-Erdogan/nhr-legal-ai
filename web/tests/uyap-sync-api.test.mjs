import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function compile(relative, requires = {}) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8").replaceAll("import.meta.env", "({})");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)((name) => requires[name], module, module.exports);
  return module.exports;
}

const bridge = compile("../src/lib/uyap-bridge.ts", { "@/lib/steady-timer": {} });
const sync = compile("../src/lib/uyap-sync-all.ts", { "@/lib/uyap-bridge": {}, "@/lib/steady-timer": {} });
const api = compile("../src/lib/uyap-sync-api.ts", {
  "@/lib/auth-api": { inMemoryAccessToken: () => "test-token" },
  "@/lib/uyap-sync-all": sync,
  "@/lib/uyap-bridge": bridge,
});
const detail = { who: { esas: "2025/1", birim: "Test Mahkemesi" }, tabs: [], complete: true, problems: [] };
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("doğrulama kaydı parçalara ayrılır; oturum ve zaman aşımı koruması her istekte vardır", async (t) => {
  const sizes = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "http://localhost:8766/api/office/uyap/sync-report");
    assert.equal(options.credentials, "include");
    assert.equal(options.headers.Authorization, "Bearer test-token");
    assert.ok(options.signal instanceof AbortSignal);
    const { items } = JSON.parse(options.body);
    sizes.push(items.length);
    return json({ results: items.map((item) => ({ ...item, status: "saved" })) });
  });
  const items = Array.from({ length: 201 }, (_, i) => ({ esas: `2025/${i}`, birim: "Test Mahkemesi", complete: true }));
  assert.deepEqual(await api.saveSyncReport(items), { saved: 201, downgraded: [], unmatched: 0 });
  assert.deepEqual(sizes, [200, 1]);
});

test("bozuk, eksik veya yanlış dosyaya ait sunucu yanıtı başarı sayılmaz", async (t) => {
  const item = { esas: "2025/1", birim: "Test Mahkemesi", complete: true };
  for (const body of [null, {}, { results: [{ status: "saved", complete: true }] }, { results: [{ status: "saved", esas: "2025/2", complete: true }] }]) {
    t.mock.method(globalThis, "fetch", async () => json(body));
    assert.deepEqual(await api.saveSyncReport([item]), { saved: 0, downgraded: [], unmatched: 1 });
    t.mock.restoreAll();
  }
});

test("bilgi kaydı sunucu eksiksizliğini aynen döndürür; belirsiz dava veya oturum kaybı hata olarak kalır", async (t) => {
  t.mock.method(globalThis, "fetch", async (_url, options) => {
    assert.ok(options.signal instanceof AbortSignal);
    return json({ status: "saved", complete: false, case_created: false });
  });
  assert.deepEqual(await api.saveCaseDetail(detail), { complete: false, caseCreated: false });
  t.mock.restoreAll();
  for (const [body, status, message] of [
    [{ status: "ambiguous" }, 200, /birden çok dava/],
    [{}, 401, /Oturumunuz sona ermiş/],
  ]) {
    t.mock.method(globalThis, "fetch", async () => json(body, status));
    await assert.rejects(api.saveCaseDetail(detail), message);
    t.mock.restoreAll();
  }
});

test("sunucu ağ veya zaman aşımı hatasında sonuç kaydedilmiş sayılmaz", async (t) => {
  t.mock.method(globalThis, "fetch", async () => { throw new DOMException("timeout", "TimeoutError"); });
  await assert.rejects(api.saveCaseDetail(detail), /zaman aşımına.*kaydedilmiş sayılmadı/);
  await assert.rejects(api.saveSyncReport([{ esas: "2025/1", birim: "A", complete: true }]), /kaydedilmiş sayılmadı/);
});

test("eski kaydın complete rozeti yüklenmemiş sekmeyi veya tutarsız tabloyu tamam saydırmaz", async (t) => {
  const tab = { key: "safahat", label: "Safahat", complete: true, pairs: [], tables: [] };
  for (const tables of [[], [{ rows: [["a"]], declared: 2, complete: true }], [{ rows: [], declared: null, complete: true }]]) {
    t.mock.method(globalThis, "fetch", async () => json({ tabs: [{ ...tab, tables }], complete: true }));
    const result = await api.loadCaseDetail("test-case");
    assert.equal(result.complete, false);
    assert.equal(result.detail.complete, false);
    t.mock.restoreAll();
  }
  t.mock.method(globalThis, "fetch", async () => json({ tabs: [{ ...tab, tables: [{ rows: [], declared: 0, complete: true }] }], complete: true }));
  assert.equal((await api.loadCaseDetail("test-case")).complete, true);
});

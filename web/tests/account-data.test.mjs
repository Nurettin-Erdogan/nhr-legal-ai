import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";

const require = createRequire(import.meta.url);
function compile(relative) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8").replace("import.meta.env?.VITE_API_URL", "undefined");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)((name) => (name === "@/lib/auth-api" ? { inMemoryAccessToken: () => null } : require(name)), module, module.exports);
  return module.exports;
}

const lib = compile("../src/lib/account-data.ts");

test("an export is summarised and a malformed body is rejected", () => {
  const summary = lib.summarizeExport({ office: { clients: [{}, {}], cases: [{}] }, conversations: [{}], truncated_tables: ["tasks", 5] });
  assert.deepEqual(summary, { clients: 2, cases: 1, conversations: 1, truncated: ["tasks"] });
  assert.equal(lib.summarizeExport(null), null);
  assert.equal(lib.summarizeExport({}), null);
  assert.equal(lib.summarizeExport({ office: null }), null);
  assert.deepEqual(lib.summarizeExport({ office: {} }), { clients: 0, cases: 0, conversations: 0, truncated: [] });
});

test("the message always says when records may be missing", () => {
  assert.equal(lib.exportMessage({ clients: 2, cases: 1, conversations: 3, truncated: [] }), "Dosya indirildi: 2 müvekkil, 1 dava, 3 sohbet.");
  assert.match(lib.exportMessage({ clients: 0, cases: 0, conversations: 0, truncated: ["tasks"] }), /tasks kayıtları sınır nedeniyle eksik olabilir/);
});

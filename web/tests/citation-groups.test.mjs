import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function load(relative) {
  const code = readFileSync(new URL(relative, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const module = { exports: {} };
  new Function("module", "exports", outputText)(module, module.exports);
  return module.exports;
}
const { groupCitations } = load("../src/lib/citation-groups.ts");
const article = (marker) => ({ marker, reference: "İŞ KANUNU (1475) m. 14 — Kıdem tazminatı:", source_url: "https://mevzuat.gov.tr/x", verification: "official" });

test("aynı maddeye giden ardışık atıflar tek satırda aralık olarak gösterilir", () => {
  const groups = groupCitations([article("K1"), article("K2"), article("K3"), article("K4")]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].label, "K1–K4");
  assert.deepEqual(groups[0].markers, ["K1", "K2", "K3", "K4"]);
});

test("ardışık olmayan işaretler virgülle listelenir ve sıra korunur", () => {
  const other = { marker: "K2", reference: "Yargıtay 9. HD, E. 2011/1, K. 2013/2", source_url: null, verification: "official" };
  const groups = groupCitations([article("K1"), other, article("K3")]);
  assert.deepEqual(groups.map((group) => group.label), ["K1, K3", "K2"]);
});

test("künyesi aynı olsa da doğrulama durumu farklı atıflar birleştirilmez", () => {
  const unverified = { ...article("K2"), verification: "third_party" };
  assert.equal(groupCitations([article("K1"), unverified]).length, 2);
});

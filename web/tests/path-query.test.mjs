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
const { splitPathQuery, searchParamText } = load("../src/lib/path-query.ts");

test("sorgusuz yol olduğu gibi kalır", () => {
  assert.deepEqual(splitPathQuery("/dashboard/cases"), { to: "/dashboard/cases" });
  assert.deepEqual(splitPathQuery("/dashboard/cases?"), { to: "/dashboard/cases" });
});

test("sorgu ve çapa yoldan ayrılır; Türkçe ve özel karakterler çözülür", () => {
  assert.deepEqual(splitPathQuery("/dashboard/clients?q=Ay%C5%9Fe%20Demir"), {
    to: "/dashboard/clients",
    search: { q: "Ayşe Demir" },
  });
  assert.deepEqual(splitPathQuery("/dashboard/cases/c1?tab=evraklar#ust"), {
    to: "/dashboard/cases/c1",
    search: { tab: "evraklar" },
    hash: "ust",
  });
  assert.deepEqual(splitPathQuery("/dashboard/files?q=demir%20%26%20o%C4%9Fullar%C4%B1.docx"), {
    to: "/dashboard/files",
    search: { q: "demir & oğulları.docx" },
  });
  assert.deepEqual(splitPathQuery("/#fiyat"), { to: "/", hash: "fiyat" });
});

test("yönlendiricinin sayıya ya da mantıksal değere çevirdiği sorgu değeri metne döner", () => {
  assert.equal(searchParamText("2025/321"), "2025/321");
  assert.equal(searchParamText(10000000146), "10000000146");
  assert.equal(searchParamText(true), "true");
  assert.equal(searchParamText(undefined), "");
  assert.equal(searchParamText({ a: 1 }), "");
});

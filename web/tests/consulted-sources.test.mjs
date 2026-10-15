import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";

const require = createRequire(import.meta.url);
function compile(relative, dependencies = {}) {
  const code = readFileSync(new URL(relative, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(code, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
    },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(
    (id) => dependencies[id] ?? require(id),
    module,
    module.exports,
  );
  return module.exports;
}

const model = compile("../src/lib/consulted-sources.ts");
const scope = compile("../src/lib/document-scope.ts");
const { ConsultedSourceList } = compile("../src/components/ChatCitations.tsx", {
  "@/lib/document-scope": scope,
  "@/lib/citation-groups": compile("../src/lib/citation-groups.ts"),
  "@/lib/source-label": compile("../src/lib/source-label.ts"),
});

const official = {
  marker: "I1",
  source_id: "a",
  reference: "Yargıtay 3. Hukuk Dairesi, E. 2020/1, K. 2021/2",
  source_url: "https://karararama.yargitay.gov.tr/getDokuman?id=1",
  excerpt: "Kiracı ihtiyaç nedeniyle tahliye edilebilir.",
  verification: "official",
};

test("only official sources and the user's own documents are ever listed", () => {
  const parsed = model.parseConsultedSources([
    official,
    { ...official, marker: "I2", source_id: "b", reference: "Üçüncü taraf kayıt", verification: "third_party" },
    { ...official, marker: "I3", source_id: "c", reference: "kira.txt", verification: "user_document", source_url: null },
    { ...official, marker: "I4", source_id: "d", reference: "Bilinmeyen", verification: "pending" },
  ]);
  assert.deepEqual(
    parsed.map((s) => s.reference),
    [official.reference, "kira.txt"],
  );
});

test("malformed payloads are dropped, never invented", () => {
  for (const value of [undefined, null, {}, "x", 7, [null], [{}], [{ marker: "I1" }]]) {
    assert.deepEqual(model.parseConsultedSources(value), []);
  }
  const parsed = model.parseConsultedSources([{ ...official, reference: "   " }]);
  assert.deepEqual(parsed, []);
});

test("the same source is listed once, the list and the excerpt are bounded", () => {
  const many = Array.from({ length: 20 }, (_, i) => ({
    ...official,
    marker: `I${i + 1}`,
    source_id: String(i),
    reference: `Karar ${i}`,
    excerpt: "x".repeat(2000),
  }));
  const parsed = model.parseConsultedSources([official, official, ...many]);
  assert.equal(parsed.length, model.MAX_CONSULTED_SOURCES);
  assert.ok(parsed.every((s) => s.excerpt.length <= 500));
  assert.equal(parsed.filter((s) => s.reference === official.reference).length, 1);
});

test("unsafe links are not forwarded", () => {
  const [item] = model.parseConsultedSources([{ ...official, source_url: "javascript:alert(1)" }]);
  assert.equal(item.source_url, null);
});

test("the section says these are not the basis of the answer and shows each passage", () => {
  const sources = model.parseConsultedSources([official]);
  const html = renderToStaticMarkup(createElement(ConsultedSourceList, { sources }));
  assert.ok(html.includes("İncelenen diğer kaynaklar (1)"));
  assert.ok(html.includes("cevabın dayanağı değildir"));
  assert.ok(html.includes(official.reference));
  assert.ok(html.includes("ihtiyaç nedeniyle tahliye"));
  assert.ok(html.includes('href="https://karararama.yargitay.gov.tr/getDokuman?id=1"'));
  assert.ok(!html.includes("doğrulanmadı"));
});

test("a user's own document carries its label and has no link", () => {
  const sources = model.parseConsultedSources([
    { ...official, reference: "kira.txt", verification: "user_document", source_url: null },
  ]);
  const html = renderToStaticMarkup(createElement(ConsultedSourceList, { sources }));
  assert.ok(html.includes("kullanıcı belgesi"));
  assert.ok(!html.includes("<a "));
});

test("nothing is rendered when there is nothing to list", () => {
  assert.equal(renderToStaticMarkup(createElement(ConsultedSourceList, { sources: [] })), "");
});

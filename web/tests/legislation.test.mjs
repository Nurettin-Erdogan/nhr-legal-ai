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
  new Function("require", "module", "exports", outputText)(require, module, module.exports);
  return module.exports;
}

const lib = compile("../src/lib/legislation.ts");

const article = (articleNo, articleTitle = null, id = articleNo) => ({ id: String(id), articleNo, articleTitle, versionDate: null });
const ARTICLES = [
  article("1", "Amaç"),
  article("18", "Feshin geçerli sebebe dayandırılması"),
  article("18/A", "Ek hüküm"),
  article("118", "Başka"),
  article("Geçici Madde 1", null),
  article("25", "İşverenin haklı nedenle derhal fesih hakkı"),
];

test("the law list is parsed defensively and unknown types fall back to other", () => {
  const page = lib.parseLawPage({
    query: "is",
    total: 3,
    offset: 0,
    article_reference: { law_no: "4857", article_no: "18" },
    results: [
      { law_no: "4857", law_name: "İŞ  KANUNU", legislation_type: "law", articles: 122, latest_version: "2026-05-07", gazette_date: "2003-06-10" },
      { law_no: "1", law_name: "X", legislation_type: "bilinmeyen", articles: "x" },
      { law_no: "", law_name: "Kimliksiz" },
      null,
    ],
  });
  assert.equal(page.results.length, 2);
  assert.equal(page.results[0].lawName, "İŞ KANUNU");
  assert.equal(page.results[1].legislationType, "other");
  assert.equal(page.results[1].articles, 0);
  assert.deepEqual(page.articleReference, { lawNo: "4857", articleNo: "18" });
  assert.equal(lib.parseLawPage(null), null);
  assert.equal(lib.parseLawPage({ results: "x" }), null);
  assert.equal(lib.parseLawPage({ results: [], article_reference: { law_no: "4857" } }).articleReference, null);
});

test("a law detail drops articles without an id and keeps the truncation flag", () => {
  const detail = lib.parseLawDetail({
    law_no: "4857",
    law_name: "İŞ KANUNU",
    legislation_type: "law",
    truncated: true,
    articles: [{ id: "a", article_no: "1", article_title: "Amaç" }, { article_no: "2" }, null],
  });
  assert.equal(detail.articles.length, 1);
  assert.equal(detail.truncated, true);
  assert.equal(lib.parseLawDetail({ law_no: "1" }), null);
});

test("article filtering matches numbers exactly (with suffixes) and titles, folding Turkish letters", () => {
  const numbers = (query) => lib.filterArticles(ARTICLES, query).map((item) => item.articleNo);
  assert.deepEqual(numbers("18"), ["18", "18/A"]);
  assert.deepEqual(numbers("madde 18"), ["18", "18/A"]);
  assert.deepEqual(numbers("m. 25"), ["25"]);
  assert.ok(numbers("gecici").includes("Geçici Madde 1"));
  assert.deepEqual(numbers("HAKLI NEDENLE"), ["25"]);
  assert.deepEqual(numbers("yok böyle"), []);
  assert.equal(numbers("").length, ARTICLES.length);
  assert.ok(!numbers("1").includes("118")); // "1" ile 118 karışmaz
});

test("an article is found by its number and labelled for display", () => {
  assert.equal(lib.findArticle(ARTICLES, "18/a").articleNo, "18/A");
  assert.equal(lib.findArticle(ARTICLES, "999"), undefined);
  assert.equal(lib.articleLabel(ARTICLES[1]), "Madde 18 — Feshin geçerli sebebe dayandırılması");
  assert.equal(lib.articleLabel(ARTICLES[4]), "Geçici Madde 1");
  assert.equal(lib.articleLabel(article("14", "Kıdem tazminatı:")), "Madde 14 — Kıdem tazminatı");
});

test("citations name the law, its number and the article", () => {
  const law = { lawNo: "4857", lawName: "İŞ KANUNU" };
  assert.equal(lib.citationFor(law, ARTICLES[1]), "İŞ KANUNU (4857) m. 18");
  assert.equal(lib.citationFor(law, ARTICLES[4]), "İŞ KANUNU (4857) Geçici Madde 1");
  assert.equal(lib.dateTr("2003-06-10"), "10.06.2003");
  assert.equal(lib.dateTr(null), "");
});

test("requests carry the filters and map failures to readable errors", async () => {
  const calls = [];
  const respond = (status, body) => async (url) => {
    calls.push(String(url));
    return { ok: status >= 200 && status < 300, status, json: async () => body };
  };
  const original = globalThis.fetch;
  try {
    globalThis.fetch = respond(200, { total: 0, results: [] });
    await lib.searchLaws("  is kanunu ", { kind: "law", offset: 30 });
    const query = new URL(calls[0]).searchParams;
    assert.equal(query.get("q"), "is kanunu");
    assert.equal(query.get("kind"), "law");
    assert.equal(query.get("offset"), "30");
    await lib.searchLaws("x");
    assert.equal(new URL(calls[1]).searchParams.get("kind"), null);
    globalThis.fetch = respond(404, { detail: "Bu numarayla doğrulanmış mevzuat bulunamadı" });
    await assert.rejects(lib.loadLaw("123"), (error) => error.status === 404 && /bulunamadı/.test(error.message));
    globalThis.fetch = respond(200, { articles: "x" });
    await assert.rejects(lib.loadLaw("123"), (error) => /geçersiz/.test(error.message));
    globalThis.fetch = respond(200, { results: "x" });
    await assert.rejects(lib.searchLaws("x"), (error) => /geçersiz/.test(error.message));
    globalThis.fetch = async () => {
      throw new TypeError("network");
    };
    await assert.rejects(lib.searchLaws("x"), (error) => /ulaşılamadı/.test(error.message));
  } finally {
    globalThis.fetch = original;
  }
});

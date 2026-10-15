import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";

const require = createRequire(import.meta.url);
function compile(relative) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8").replace("import.meta.env?.VITE_API_URL", "undefined");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(require, module, module.exports);
  return module.exports;
}

const search = compile("../src/lib/decision-search.ts");

const row = (overrides = {}) => ({
  id: "1",
  source_type: "court_decision",
  title: "Yargıtay 9. Hukuk Dairesi, E. 2020/1, K. 2021/2",
  authority: "Yargıtay",
  court_name: "Yargıtay",
  chamber: "9. Hukuk Dairesi",
  docket_no: "2020/1",
  decision_no: "2021/2",
  decision_date: "2021-03-04",
  excerpt: "işçinin kıdem tazminatı",
  rank: 0.5,
  verification: "official",
  ...overrides,
});

const hit = (overrides) => search.parseSearchPage({ results: [row(overrides)] }).hits[0];

test("a missing or unknown verification is never shown as official", () => {
  for (const verification of [undefined, null, "", "verified", "OFFICIAL", 1]) {
    assert.equal(hit({ verification }).verification, "unknown");
  }
  assert.equal(hit({ verification: "third_party" }).verification, "third_party");
  assert.equal(hit({ verification: "official" }).verification, "official");
  // AGENTS.md (2026-10-15): resmî metinle karşılaştırılmış kayıt "Resmî metin ✓"; karşılaştırılmamış kayıt olumsuz ibare olmadan
  // kaynak adıyla gösterilir ve hiçbir zaman ✓ ya da "resmî" almaz.
  assert.deepEqual(search.verificationBadge("official"), { label: "Resmî metin ✓", tone: "ok" });
  for (const [args, label] of [
    [["third_party", "https://karararama.yargitay.gov.tr/getDokuman?id=1"], "Yargıtay kararı"],
    [["third_party", "https://karararama.danistay.gov.tr/getDokuman?id=2"], "Danıştay kararı"],
    [["third_party", null, "Yargıtay 9. Hukuk Dairesi"], "Yargıtay kararı"],
    [["unknown", "https://example.com/x"], "Karar"],
  ]) {
    const badge = search.verificationBadge(...args);
    assert.deepEqual(badge, { label, tone: "neutral" });
    assert.doesNotMatch(badge.label, /resmî|doğrula|✓/i);
  }
});

test("the parser drops rows without an id or title and survives malformed bodies", () => {
  assert.equal(search.parseSearchPage(null), null);
  assert.equal(search.parseSearchPage("x"), null);
  const page = search.parseSearchPage({
    total: 3,
    partial: true,
    results: [row(), row({ id: "" }), row({ title: "  " }), null, "x", row({ id: "2", rank: "yüksek", source_type: undefined })],
  });
  assert.deepEqual(page.hits.map((item) => item.id), ["1", "2"]);
  assert.equal(page.hits[1].rank, 0);
  assert.equal(page.hits[1].sourceType, "other");
  assert.equal(page.total, 3);
  assert.equal(page.partial, true);
  assert.equal(search.parseSearchPage({ results: [row()], partial: "true" }).partial, false);
  assert.equal(search.parseSearchPage({ results: [row()], total: -4 }).total, 1);
  assert.equal(search.parseSearchPage({}).hits.length, 0);
});

test("citations follow the court-decision and statute conventions", () => {
  assert.equal(search.citationOf(hit()), "Yargıtay 9. Hukuk Dairesi, E. 2020/1, K. 2021/2, T. 04.03.2021");
  const statute = hit({
    source_type: "legislation", law_name: "İş Kanunu", law_no: "4857", article_no: "25", court_name: null, chamber: null, docket_no: null,
  });
  assert.equal(search.citationOf(statute), "İş Kanunu (4857 sayılı) m. 25");
  assert.equal(search.citationOf(hit({ court_name: null, authority: null, chamber: null, docket_no: null, decision_no: null, decision_date: null })), "Yargıtay 9. Hukuk Dairesi, E. 2020/1, K. 2021/2");
  const bare = search.parseSearchPage({ results: [{ id: "9", title: "Başlık", source_type: "other" }] }).hits[0];
  assert.equal(search.citationOf(bare), "Başlık");
});

test("filters combine and sorting is stable", () => {
  const hits = search.parseSearchPage({
    results: [
      row({ id: "a", authority: "Yargıtay", decision_date: "2019-01-01", verification: "third_party" }),
      row({ id: "b", authority: "Danıştay", decision_date: "2022-05-05", verification: "official" }),
      row({ id: "c", authority: "Yargıtay", decision_date: "2022-01-01", verification: "official" }),
      row({ id: "d", source_type: "legislation", authority: "TBMM", decision_date: null, verification: "unknown" }),
    ],
  }).hits;
  const ids = (filters) => search.filterAndSort(hits, { ...search.DEFAULT_FILTERS, ...filters }).map((item) => item.id);
  assert.deepEqual(ids({}), ["a", "b", "c", "d"]);
  assert.deepEqual(ids({ onlyOfficial: true }), ["b", "c"]);
  assert.deepEqual(ids({ authority: "Yargıtay" }), ["a", "c"]);
  assert.deepEqual(ids({ authority: "Yargıtay", onlyOfficial: true }), ["c"]);
  assert.deepEqual(ids({ year: "2022" }), ["b", "c"]);
  assert.deepEqual(ids({ sourceType: "legislation" }), ["d"]);
  assert.deepEqual(ids({ sort: "newest" }), ["b", "c", "a", "d"]);
  assert.deepEqual(ids({ sort: "official_first" }), ["b", "c", "a", "d"]);
  assert.deepEqual(ids({ authority: "Yok" }), []);
});

test("facets count what is loaded and report how many are not officially verified", () => {
  const hits = search.parseSearchPage({
    results: [
      row({ id: "a", verification: "third_party", decision_date: "2019-01-01" }),
      row({ id: "b", decision_date: "2022-05-05" }),
      row({ id: "c", authority: "Danıştay", decision_date: "2022-01-01", verification: "unknown" }),
    ],
  }).hits;
  const facets = search.facetsOf(hits);
  assert.deepEqual(facets.authorities, [{ value: "Yargıtay", count: 2 }, { value: "Danıştay", count: 1 }]);
  assert.deepEqual(facets.years.map((year) => year.value), ["2022", "2019"]);
  assert.equal(facets.unverified, 2);
});

test("highlighting marks query words by stem and never produces markup", () => {
  const segments = search.highlightSegments("İşçinin kıdem tazminatı <b>hakkı</b> doğdu.", "kıdem tazminatı");
  assert.equal(segments.map((segment) => segment.text).join(""), "İşçinin kıdem tazminatı <b>hakkı</b> doğdu.");
  assert.deepEqual(segments.filter((segment) => segment.match).map((segment) => segment.text), ["kıdem", "tazminatı"]);
  assert.deepEqual(search.highlightSegments("metin", "yok"), [{ text: "metin", match: false }]);
  assert.deepEqual(search.highlightSegments("", "kıdem"), [{ text: "", match: false }]);
  assert.deepEqual(search.highlightSegments("kıdem", "ve bir"), [{ text: "kıdem", match: false }]);
  // Türkçe büyük harf: "İŞÇİ" küçültüldüğünde uzunluk değişirse (i̇) işaretleme güvenli biçimde atlanır, metin bozulmaz.
  const upper = search.highlightSegments("KIDEM TAZMİNATI", "kıdem tazminatı");
  assert.equal(upper.map((segment) => segment.text).join(""), "KIDEM TAZMİNATI");
});

test("the search call picks the endpoint by mode and turns failures into readable errors", async () => {
  const calls = [];
  const respond = (status, body) => async (url, init) => {
    calls.push({ url: String(url), init });
    return { ok: status >= 200 && status < 300, status, json: async () => body };
  };
  const original = globalThis.fetch;
  try {
    globalThis.fetch = respond(200, { query: "q", total: 1, partial: false, limit: 10, offset: 0, results: [row()] });
    const keyword = await search.searchDecisions("  kıdem tazminatı ");
    assert.equal(keyword.hits.length, 1);
    assert.match(calls[0].url, /\/api\/legal\/search\?/);
    assert.equal(new URL(calls[0].url).searchParams.get("q"), "kıdem tazminatı");
    assert.equal(calls[0].init.credentials, "include");

    await search.searchDecisions("işçi haklı nedenle feshetti", { mode: "narrative", limit: 5, offset: 10 });
    assert.match(calls[1].url, /\/api\/legal\/semantic\?/);
    assert.equal(new URL(calls[1].url).searchParams.get("limit"), "5");
    assert.equal(new URL(calls[1].url).searchParams.get("offset"), "10");

    globalThis.fetch = respond(504, {});
    await assert.rejects(search.searchDecisions("kıdem"), (error) => error.status === 504 && /zaman aşımı/.test(error.message));
    globalThis.fetch = respond(422, {});
    await assert.rejects(search.searchDecisions("k"), (error) => /en az 2/.test(error.message));
    await assert.rejects(search.searchDecisions("kısa", { mode: "narrative" }), (error) => /en az 10/.test(error.message));
    globalThis.fetch = respond(500, {});
    await assert.rejects(search.searchDecisions("kıdem"), (error) => error.status === 500);
    globalThis.fetch = respond(200, null);
    await assert.rejects(search.searchDecisions("kıdem"), (error) => /geçersiz/.test(error.message));
    globalThis.fetch = async () => {
      throw new TypeError("network");
    };
    await assert.rejects(search.searchDecisions("kıdem"), (error) => /ulaşılamadı/.test(error.message));
  } finally {
    globalThis.fetch = original;
  }
});

test("a minimum length is defined per mode and matches the server", () => {
  assert.equal(search.MIN_QUERY_LENGTH.keyword, 2);
  assert.equal(search.MIN_QUERY_LENGTH.narrative, 10);
});

test("source detail keeps only non-empty chunks and reports a missing source", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => ({
      ok: true,
      status: 200,
      json: async () => ({ title: " Başlık ", source_url: "https://example.test/x", chunks: [{ content: "bir" }, { content: "  " }, null, { content: "iki" }] }),
    });
    const detail = await search.loadSourceDetail("abc/def");
    assert.deepEqual(detail.chunks, ["bir", "iki"]);
    assert.equal(detail.title, "Başlık");
    globalThis.fetch = async () => ({ ok: false, status: 404, json: async () => ({}) });
    await assert.rejects(search.loadSourceDetail("x"), (error) => error.status === 404);
  } finally {
    globalThis.fetch = original;
  }
});

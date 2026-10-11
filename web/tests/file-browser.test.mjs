import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/lib/file-browser.ts", import.meta.url), "utf8").replace(
  "import.meta.env.VITE_API_URL",
  '"http://test.local"',
);
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const module = { exports: {} };
new Function("require", "module", "exports", outputText)(
  () => ({ inMemoryAccessToken: () => "test-token" }),
  module,
  module.exports,
);
const { listFileBrowser, loadAllFileBrowserDocuments } = module.exports;
const filters = { q: "", source: "uyap", category: "", folder: "folder", order: "recent" };
const reply = (rows, total) =>
  new Response(JSON.stringify({ rows, total, folders: [], categories: [] }));

test("one folder returns all 213 documents, including the final partial batch", async (t) => {
  const records = Array.from({ length: 213 }, (_, i) => ({ id: String(i) }));
  const offsets = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    const query = new URL(url).searchParams;
    const offset = Number(query.get("offset"));
    offsets.push(offset);
    assert.equal(query.get("folder"), "folder");
    assert.equal(query.get("limit"), "100");
    return reply(records.slice(offset, offset + 100), records.length);
  });
  const result = await loadAllFileBrowserDocuments(filters, new AbortController().signal);
  assert.deepEqual(offsets, [0, 100, 200]);
  assert.equal(result.rows.length, 213);
  assert.equal(result.rows.at(-1).id, "212");
});

test("failed later batches remain errors rather than appearing as a complete folder", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => {
    if (calls++ === 0)
      return reply(
        Array.from({ length: 100 }, (_, i) => ({ id: String(i) })),
        150,
      );
    return new Response(JSON.stringify({ detail: "Servis hatası" }), { status: 503 });
  });
  await assert.rejects(
    loadAllFileBrowserDocuments(filters, new AbortController().signal),
    /Servis hatası/,
  );
  assert.equal(calls, 2);
});

test("closed-folder directory requests metadata only with the existing user session and cancellation signal", async (t) => {
  const controller = new AbortController();
  t.mock.method(globalThis, "fetch", async (url, init) => {
    assert.equal(new URL(url).searchParams.get("summary_only"), "true");
    assert.equal(init.credentials, "include");
    assert.equal(init.headers.Authorization, "Bearer test-token");
    assert.equal(init.signal, controller.signal);
    return reply([], 213);
  });
  assert.equal((await listFileBrowser(filters, controller.signal, true)).total, 213);
});

test("content mode sends an explicit scope and preserves excerpts and indexing coverage", async (t) => {
  const content_match = {
    before: "Ödeme ",
    match: "emri",
    after: " bildirildi.",
    page_number: 12,
    section_title: null,
  };
  const content_coverage = { total: 6, ready: 4, failed: 1, pending: 1, needs_ocr: 0 };
  t.mock.method(globalThis, "fetch", async (url) => {
    const query = new URL(url).searchParams;
    assert.equal(query.get("search_in"), "content");
    assert.equal(query.get("q"), "%50_belgesi");
    return new Response(
      JSON.stringify({
        rows: [{ id: "1", content_match }],
        total: 1,
        folders: [],
        categories: [],
        content_coverage,
      }),
    );
  });
  const result = await loadAllFileBrowserDocuments(
    { ...filters, q: "%50_belgesi", search_in: "content" },
    new AbortController().signal,
  );
  assert.deepEqual(result.rows[0].content_match, content_match);
  assert.deepEqual(result.content_coverage, content_coverage);
});

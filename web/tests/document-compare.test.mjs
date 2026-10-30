import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";

const require = createRequire(import.meta.url);
function compile(relative) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8").replace(
    "import.meta.env?.VITE_API_URL",
    "undefined",
  );
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(require, module, module.exports);
  return module.exports;
}

const compare = compile("../src/lib/document-compare.ts");

const payload = (overrides = {}) => ({
  case_id: "c1",
  left: { id: "a", file_name: "v1.pdf", ocr: false },
  right: { id: "b", file_name: "v2.pdf", ocr: true },
  similarity: 0.75,
  left_units: 4,
  right_units: 4,
  counts: { equal: 3, changed: 1, removed: 0, added: 0 },
  blocks: [
    { kind: "equal", units: ["bir", "iki", "üç"] },
    {
      kind: "changed",
      left: "ücret 20.000",
      right: "ücret 25.000",
      words: [
        { op: "equal", text: "ücret" },
        { op: "delete", text: "20.000" },
        { op: "insert", text: "25.000" },
      ],
    },
  ],
  ...overrides,
});

test("a valid response is parsed with its OCR flags and counts", () => {
  const result = compare.parseCompare(payload());
  assert.equal(result.left.fileName, "v1.pdf");
  assert.equal(result.right.ocr, true);
  assert.deepEqual(result.counts, { equal: 3, changed: 1, removed: 0, added: 0 });
  assert.equal(result.blocks.length, 2);
  assert.equal(result.similarity, 0.75);
});

test("a malformed response is rejected as a whole instead of showing a partial diff as 'no differences'", () => {
  assert.equal(compare.parseCompare(null), null);
  assert.equal(compare.parseCompare({}), null);
  assert.equal(compare.parseCompare(payload({ blocks: "x" })), null);
  assert.equal(
    compare.parseCompare(
      payload({ blocks: [{ kind: "equal", units: ["bir"] }, { kind: "bilinmeyen" }] }),
    ),
    null,
  );
  assert.equal(compare.parseCompare(payload({ blocks: [{ kind: "added" }] })), null);
  assert.equal(compare.parseCompare(payload({ left: { file_name: "x" } })), null);
  // sayılar geçersizse sıfıra düşer, sahte "değişiklik yok" üretmez ama çökmez
  const odd = compare.parseCompare(payload({ counts: { equal: -1, changed: "x" }, similarity: 7 }));
  assert.deepEqual(odd.counts, { equal: 0, changed: 0, removed: 0, added: 0 });
  assert.equal(odd.similarity, 0);
});

test("counts are described in plain Turkish and 'no difference' is explicit", () => {
  assert.match(
    compare.describeCounts({ equal: 5, changed: 0, removed: 0, added: 0 }),
    /fark(ı)? bulunamadı/,
  );
  assert.equal(
    compare.describeCounts({ equal: 7, changed: 2, removed: 1, added: 3 }),
    "2 cümle değişti, 3 cümle eklendi, 1 cümle silindi; 7 cümle aynı.",
  );
  assert.equal(compare.hasDifferences({ equal: 1, changed: 0, removed: 0, added: 1 }), true);
  assert.equal(compare.hasDifferences({ equal: 1, changed: 0, removed: 0, added: 0 }), false);
});

const units = (n) => Array.from({ length: n }, (_, i) => `cümle ${i}`);

test("long equal runs are folded around the changes and the document edges keep only the side that touches a change", () => {
  const blocks = [
    { kind: "equal", units: units(6) },
    { kind: "removed", text: "silinen" },
    { kind: "equal", units: units(6) },
    { kind: "added", text: "eklenen" },
    { kind: "equal", units: units(6) },
  ];
  const folded = compare.foldBlocks(blocks, 1);
  assert.deepEqual(
    folded.map((item) => `${item.kind}${item.units ? ":" + item.units.length : ""}`),
    ["fold:5", "equal:1", "removed", "equal:1", "fold:4", "equal:1", "added", "equal:1", "fold:5"],
  );
  // Baştaki bölümde yalnız değişikliğe bakan son cümle görünür; sondaki bölümde yalnız ilk cümle.
  assert.deepEqual(folded[1].units, ["cümle 5"]);
  assert.deepEqual(folded.at(-2).units, ["cümle 0"]);
  // Hiçbir cümle kaybolmaz: katlananlar ve görünenler birlikte özgün cümleleri verir.
  const total = folded.flatMap((item) => item.units ?? []).length;
  assert.equal(total, 18);
});

test("short equal runs stay visible and a large context unfolds everything", () => {
  const blocks = [
    { kind: "removed", text: "x" },
    { kind: "equal", units: ["a", "b", "c"] },
    { kind: "added", text: "y" },
  ];
  assert.deepEqual(
    compare.foldBlocks(blocks, 1).map((item) => item.kind),
    ["removed", "equal", "added"],
  );
  const wide = compare.foldBlocks(
    [
      { kind: "equal", units: units(50) },
      { kind: "added", text: "y" },
    ],
    Number.MAX_SAFE_INTEGER,
  );
  assert.deepEqual(
    wide.map((item) => item.kind),
    ["equal", "added"],
  );
  const identical = compare.foldBlocks([{ kind: "equal", units: units(50) }], 1);
  assert.deepEqual(
    identical.map((item) => `${item.kind}:${item.units.length}`),
    ["fold:50"],
  );
});

test("the request carries both ids and the token, and failures become readable errors", async () => {
  const calls = [];
  const respond = (status, body) => async (url, init) => {
    calls.push({ url: String(url), init });
    return { ok: status >= 200 && status < 300, status, json: async () => body };
  };
  const original = globalThis.fetch;
  try {
    globalThis.fetch = respond(200, payload());
    const result = await compare.compareDocuments("case/1", "a", "b", { token: "tok" });
    assert.equal(result.blocks.length, 2);
    assert.match(calls[0].url, /\/api\/office\/cases\/case%2F1\/documents\/compare\?/);
    const query = new URL(calls[0].url).searchParams;
    assert.equal(query.get("left"), "a");
    assert.equal(query.get("right"), "b");
    assert.equal(calls[0].init.credentials, "include");
    assert.equal(calls[0].init.headers.Authorization, "Bearer tok");

    await compare.compareDocuments("c", "a", "b");
    assert.equal(calls[1].init.headers, undefined);

    globalThis.fetch = respond(409, { detail: '"tarama.tif" karşılaştırılamıyor: OCR gerekli' });
    await assert.rejects(
      compare.compareDocuments("c", "a", "b"),
      (error) => error.status === 409 && /OCR gerekli/.test(error.message),
    );
    globalThis.fetch = respond(413, {});
    await assert.rejects(compare.compareDocuments("c", "a", "b"), (error) =>
      /çok uzun/.test(error.message),
    );
    globalThis.fetch = respond(401, {});
    await assert.rejects(compare.compareDocuments("c", "a", "b"), (error) =>
      /Oturumunuz/.test(error.message),
    );
    globalThis.fetch = respond(500, {});
    await assert.rejects(compare.compareDocuments("c", "a", "b"), (error) => error.status === 500);
    globalThis.fetch = respond(200, { blocks: [] });
    await assert.rejects(compare.compareDocuments("c", "a", "b"), (error) =>
      /geçersiz/.test(error.message),
    );
    globalThis.fetch = async () => {
      throw new TypeError("network");
    };
    await assert.rejects(compare.compareDocuments("c", "a", "b"), (error) =>
      /ulaşılamadı/.test(error.message),
    );
  } finally {
    globalThis.fetch = original;
  }
});

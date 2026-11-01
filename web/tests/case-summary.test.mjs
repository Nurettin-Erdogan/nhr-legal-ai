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

const lib = compile("../src/lib/case-summary.ts");

const doc = (overrides = {}) => ({
  document_id: "d1",
  file_name: "dilekce.udf",
  ocr: false,
  coverage: 1,
  bullets: ["Davacı çalışmıştır."],
  dropped: 0,
  error: null,
  ...overrides,
});

test("facts are parsed defensively and empty cells render as a dash", () => {
  const parsed = lib.parseFacts({
    total: 3,
    ready: 2,
    documents: [
      {
        id: "a",
        file_name: "bilirkisi.udf",
        ocr: true,
        dates: ["01.03.2015", 5],
        amounts: ["340.000 TL"],
        esas: ["2025/412"],
        karar: [],
        numbers: [],
        laws: ["4857"],
        characters: 392,
      },
      { id: "", file_name: "kimliksiz" },
      null,
      { id: "b" },
    ],
  });
  assert.equal(parsed.total, 3);
  assert.deepEqual(
    parsed.documents.map((item) => item.id),
    ["a", "b"],
  );
  assert.deepEqual(parsed.documents[0].dates, ["01.03.2015"]);
  assert.equal(parsed.documents[0].ocr, true);
  assert.equal(parsed.documents[1].fileName, "Adsız belge");
  assert.equal(lib.hasFacts(parsed.documents[0]), true);
  assert.equal(lib.hasFacts(parsed.documents[1]), false);
  assert.equal(lib.parseFacts(null), null);
  assert.equal(lib.parseFacts({ documents: "x" }), null);
  assert.equal(lib.cell([]), "—");
  assert.equal(lib.cell(["a", "b"]), "a, b");
  assert.equal(lib.cell(["1", "2", "3", "4", "5", "6"]), "1, 2, 3, 4 +2");
});

test("a job state is parsed with its per-document results and a malformed job is rejected", () => {
  const state = lib.parseSummaryState({
    job: {
      id: "j",
      state: "running",
      total: 3,
      done: 1,
      error: null,
      results: [doc()],
      saved_id: null,
    },
    latest: {
      id: "s",
      created_at: "2026-10-04T12:00:00+00:00",
      documents: [doc({ coverage: 0.5 })],
      markdown: "x",
      model: "qwen3.5:4b",
    },
  });
  assert.equal(state.job.state, "running");
  assert.equal(state.job.results[0].fileName, "dilekce.udf");
  assert.equal(state.latest.documents[0].coverage, 0.5);
  assert.equal(state.latest.model, "qwen3.5:4b");
  assert.deepEqual(lib.parseSummaryState({ job: null, latest: null }), { job: null, latest: null });
  assert.equal(lib.parseSummaryState({ job: { state: "running" }, latest: null }), null);
  assert.equal(lib.parseSummaryState(null), null);
  // bilinmeyen durum "bitti" sayılmaz: çalışıyor varsayılır, böylece yoklama sürer
  assert.equal(
    lib.parseSummaryState({ job: { id: "j", state: "weird" }, latest: null }).job.state,
    "running",
  );
  // geçersiz kapsam tam kapsam gibi gösterilmez ama çökmez
  assert.equal(
    lib.parseSummaryState({
      job: { id: "j", state: "done", results: [doc({ coverage: 7 })] },
      latest: null,
    }).job.results[0].coverage,
    1,
  );
});

test("coverage and progress are explained in plain Turkish", () => {
  assert.equal(lib.coverageNote({ coverage: 1 }), "");
  assert.equal(lib.coverageNote({ coverage: 0.5 }), "Belgenin yaklaşık %50'i özetlendi.");
  const job = (state, extra = {}) => ({
    id: "j",
    state,
    total: 3,
    done: 1,
    error: null,
    results: [],
    savedId: null,
    ...extra,
  });
  assert.equal(lib.progressText(job("running")), "1/3 belge özetlendi…");
  assert.equal(
    lib.progressText(job("failed", { error: "Hiçbiri doğrulanamadı." })),
    "Hiçbiri doğrulanamadı.",
  );
  assert.equal(
    lib.progressText(job("done", { results: [{ error: null }, { error: null }, { error: null }] })),
    "3 belge özetlendi.",
  );
  assert.equal(
    lib.progressText(job("done", { results: [{ error: null }, { error: "x" }, { error: "y" }] })),
    "3 belgeden 1 tanesi özetlendi; 2 belge için özet üretilemedi.",
  );
});

test("the copied markdown states the limits of the summary", () => {
  const parsed = lib.parseSummaryState({
    job: null,
    latest: {
      id: "s",
      documents: [
        doc({ ocr: true, coverage: 0.4, dropped: 2 }),
        doc({ document_id: "d2", file_name: "hata.pdf", bullets: [], error: "Doğrulanamadı." }),
      ],
    },
  });
  const markdown = lib.summaryMarkdown(parsed.latest.documents);
  assert.match(markdown, /hukuki dayanak/);
  assert.match(markdown, /## 1\. dilekce\.udf/);
  assert.match(markdown, /OCR ile okundu/);
  assert.match(markdown, /%40/);
  assert.match(markdown, /2 madde belgeyle eşleşmediği için gösterilmedi/);
  assert.match(markdown, /## 2\. hata\.pdf[\s\S]*Doğrulanamadı\./);
});

test("requests carry the token and ids, and failures become readable errors", async () => {
  const calls = [];
  const respond = (status, body) => async (url, init) => {
    calls.push({ url: String(url), init });
    return { ok: status >= 200 && status < 300, status, json: async () => body };
  };
  const original = globalThis.fetch;
  try {
    globalThis.fetch = respond(202, { job_id: "j1", total: 2 });
    const started = await lib.startSummary("case/1", ["a", "b"], { token: "tok" });
    assert.deepEqual(started, { jobId: "j1", total: 2 });
    assert.match(calls[0].url, /\/api\/office-ai\/cases\/case%2F1\/summary$/);
    assert.equal(calls[0].init.method, "POST");
    assert.deepEqual(JSON.parse(calls[0].init.body), { document_ids: ["a", "b"] });
    assert.equal(calls[0].init.headers.Authorization, "Bearer tok");
    assert.equal(calls[0].init.headers["Content-Type"], "application/json");

    globalThis.fetch = respond(200, { case_id: "c", total: 1, ready: 1, documents: [] });
    await lib.loadFacts("c");
    assert.match(calls[1].url, /\/api\/office\/cases\/c\/documents\/facts\?offset=0&limit=100$/);
    assert.equal(calls[1].init.headers.Authorization, undefined);

    globalThis.fetch = respond(409, {
      detail: "Devam eden bir özet işiniz var; bitmesini bekleyin.",
    });
    await assert.rejects(
      lib.startSummary("c", ["a"]),
      (error) => error.status === 409 && /Devam eden/.test(error.message),
    );
    globalThis.fetch = respond(401, {});
    await assert.rejects(lib.loadFacts("c"), (error) => /Oturumunuz/.test(error.message));
    globalThis.fetch = respond(200, { job_id: 5 });
    await assert.rejects(lib.startSummary("c", ["a"]), (error) => /geçersiz/.test(error.message));
    globalThis.fetch = respond(200, { documents: "x" });
    await assert.rejects(lib.loadFacts("c"), (error) => /geçersiz/.test(error.message));
    globalThis.fetch = respond(200, { job: { state: "running" }, latest: null });
    await assert.rejects(lib.loadSummaryState("c"), (error) => /geçersiz/.test(error.message));
    globalThis.fetch = async () => {
      throw new TypeError("network");
    };
    await assert.rejects(lib.loadSummaryState("c"), (error) => /ulaşılamadı/.test(error.message));
  } finally {
    globalThis.fetch = original;
  }
});
test("facts load all pages and keep the actual ready count above 40", async () => {
  const original = globalThis.fetch;
  const offsets = [];
  try {
    globalThis.fetch = async (url) => {
      const offset = Number(new URL(url).searchParams.get("offset"));
      offsets.push(offset);
      return {
        ok: true,
        json: async () => ({
          total: 151,
          ready: 145,
          has_more: offset === 0,
          documents: Array.from({ length: offset === 0 ? 100 : 45 }, (_, i) => ({
            id: `doc-${offset + i}`,
          })),
        }),
      };
    };
    const result = await lib.loadFacts("case");
    assert.equal(result.ready, 145);
    assert.equal(result.total, 151);
    assert.equal(result.documents.length, 145);
    assert.deepEqual(offsets, [0, 100]);
    globalThis.fetch = async () => ({
      ok: true,
      json: async () => ({ total: 45, ready: 45, has_more: true, documents: [] }),
    });
    await assert.rejects(lib.loadFacts("case"), /eksik/);
  } finally {
    globalThis.fetch = original;
  }
});

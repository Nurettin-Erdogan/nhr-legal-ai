import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function compile(file, deps = {}) {
  const source = readFileSync(new URL(file, import.meta.url), "utf8").replaceAll(
    "import.meta.env.VITE_API_URL",
    "undefined",
  );
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  new Function("require", "module", "exports", code)(
    (id) => {
      if (!(id in deps)) throw new Error("Unexpected dependency " + id);
      return deps[id];
    },
    module,
    module.exports,
  );
  return module.exports;
}
const summaryModel = compile("../src/lib/search-summary.ts");
const scopeModel = compile("../src/lib/document-scope.ts");
const { askAssistant, getConversationDetail, listConversations, parseAnswerKind } = compile(
  "../src/lib/ai-api.ts",
  {
    "@/lib/auth-api": { inMemoryAccessToken: () => "" },
    "./search-summary": summaryModel,
    "./document-scope": scopeModel,
  },
);
const summary = {
  candidate_documents: 29,
  verified_documents: 12,
  selected_documents: 6,
  pending_documents: 17,
  unverified_excluded: 17,
  verification_attempted: 1,
  verification_promoted: 0,
  verification_stop: "time_budget",
  retrieval_partial: false,
  exhaustive: false,
};

function mockStream(t, text) {
  const bytes = new TextEncoder().encode(text);
  let index = 0;
  const state = { canceled: false, released: false, credentials: null };
  const reader = {
    read: async () =>
      index >= bytes.length ? { done: true } : { done: false, value: bytes.slice(index, ++index) },
    cancel: async () => {
      state.canceled = true;
    },
    releaseLock: () => {
      state.released = true;
    },
  };
  t.mock.method(globalThis, "fetch", async (_url, init) => {
    state.credentials = init.credentials;
    state.body = init.body;
    return { ok: true, body: { getReader: () => reader } };
  });
  return state;
}

test("split UTF-8 progress stream preserves summary and final answer", async (t) => {
  const answer = { answer: "Türkçe yanıt", citations: [], grounded: true, search_summary: summary };
  const state = mockStream(
    t,
    JSON.stringify({ stage: "search_summary", ...summary }) +
      "\n" +
      JSON.stringify({ stage: "done", result: answer }),
  );
  const seen = [];
  const result = await askAssistant("Örnek soru", { onSearchSummary: (s) => seen.push(s) });
  assert.deepEqual(seen, [summary]);
  assert.equal(result.answer, answer.answer);
  assert.deepEqual(result.search_summary, summary);
  assert.equal(state.credentials, "include");
  assert.ok(state.canceled && state.released);
});

test("error after progress never becomes a successful answer; stream closes", async (t) => {
  const state = mockStream(
    t,
    JSON.stringify({ stage: "search_summary", ...summary }) +
      "\n" +
      JSON.stringify({ stage: "error", detail: "Kaynak doğrulanamadı" }),
  );
  const seen = [];
  await assert.rejects(
    askAssistant("Örnek soru", { onSearchSummary: (s) => seen.push(s) }),
    /Kaynak doğrulanamadı/,
  );
  assert.equal(seen.length, 1);
  assert.ok(state.canceled && state.released);
});

test("disconnection without done event is an error", async (t) => {
  const state = mockStream(t, JSON.stringify({ stage: "ping" }));
  await assert.rejects(askAssistant("Örnek soru", {}), /bağlantı kesildi/);
  assert.ok(state.canceled && state.released);
});

test("legacy answer does not fabricate candidate counters", async (t) => {
  mockStream(t, JSON.stringify({ stage: "done", result: { answer: "Yanıt", citations: [] } }));
  assert.equal((await askAssistant("Örnek soru", {})).search_summary, undefined);
});

test("only recognized answer kinds can opt out of legacy legal presentation", () => {
  for (const kind of ["conversation", "clarification", "insufficient_sources", "legal"]) {
    assert.equal(parseAnswerKind(kind), kind);
  }
  for (const kind of [undefined, null, "friendly", "CONVERSATION", {}, false]) {
    assert.equal(parseAnswerKind(kind), "legal");
  }
});

test("preview and done events retain the server-owned answer kind", async (t) => {
  const preview = {
    answer: "Merhaba!",
    answer_kind: "conversation",
    citations: [],
    grounded: false,
  };
  const done = { ...preview, answer: "Merhaba! Nasıl yardımcı olabilirim?" };
  mockStream(
    t,
    JSON.stringify({ stage: "answer_ready", preview }) +
      "\n" +
      JSON.stringify({ stage: "done", result: done }),
  );
  const seen = [];
  const result = await askAssistant("Merhaba", { onPreview: (value) => seen.push(value) });
  assert.equal(seen[0].answer_kind, "conversation");
  assert.equal(result.answer_kind, "conversation");
});

test("unknown or missing progress answer kinds remain legal", async (t) => {
  mockStream(
    t,
    JSON.stringify({ stage: "answer_ready", preview: { answer: "Yanıt", answer_kind: "bypass" } }) +
      "\n" +
      JSON.stringify({ stage: "done", result: { answer: "Yanıt", citations: [] } }),
  );
  const seen = [];
  const result = await askAssistant("Örnek soru", { onPreview: (value) => seen.push(value) });
  assert.equal(seen[0].answer_kind, "legal");
  assert.equal(result.answer_kind, "legal");
});

test("conversation history preserves answer kinds and treats unknown old metadata as legal", async (t) => {
  t.mock.method(
    globalThis,
    "fetch",
    async () =>
      new Response(
        JSON.stringify({
          messages: [
            {
              role: "assistant",
              content: "Merhaba!",
              answer_kind: "conversation",
              grounded: false,
            },
            {
              role: "assistant",
              content: "Hangi ay?",
              answer_kind: "clarification",
              grounded: false,
            },
            {
              role: "assistant",
              content: "Yetersiz kaynak",
              answer_kind: "insufficient_sources",
              grounded: false,
            },
            { role: "assistant", content: "Eski cevap", grounded: false },
            {
              role: "assistant",
              content: "Bozuk metadata",
              answer_kind: "bypass",
              grounded: false,
            },
          ],
        }),
        { status: 200 },
      ),
  );
  const detail = await getConversationDetail("conversation");
  assert.deepEqual(
    detail.messages.map((message) => message.answerKind),
    ["conversation", "clarification", "insufficient_sources", "legal", "legal"],
  );
});

test("case-scoped question sends case_id and surfaces which documents could not be read", async (t) => {
  const scope = {
    total: 3,
    ready: 1,
    pending: 1,
    ocr: 0,
    failed: [{ file_name: "tarama.png", reason: "OCR henüz desteklenmiyor" }],
  };
  const state = mockStream(
    t,
    JSON.stringify({
      stage: "done",
      result: { answer: "Yanıt", citations: [], document_scope: scope },
    }),
  );
  const result = await askAssistant("Örnek soru", { caseId: "case-1" });
  const body = JSON.parse(state.body);
  assert.equal(body.case_id, "case-1");
  assert.equal(body.project_id, null);
  assert.deepEqual(result.document_scope, scope);
});

test("question without a case sends no case scope and no document scope is invented", async (t) => {
  const state = mockStream(
    t,
    JSON.stringify({ stage: "done", result: { answer: "Yanıt", citations: [] } }),
  );
  const result = await askAssistant("Örnek soru", {});
  assert.equal(JSON.parse(state.body).case_id, null);
  assert.equal(result.document_scope, undefined);
});

test("selected office-document ids reach the API, with optional case intersection", async (t) => {
  const state = mockStream(
    t,
    JSON.stringify({ stage: "done", result: { answer: "Yanıt", citations: [] } }),
  );
  await askAssistant("Ödeme tutarı nedir?", {
    caseId: "case-1",
    selectedDocumentIds: ["doc-1", "doc-2"],
  });
  assert.deepEqual(JSON.parse(state.body).selected_document_ids, ["doc-1", "doc-2"]);
  assert.equal(JSON.parse(state.body).case_id, "case-1");
});

test("selection authorization/indexing errors are shown instead of a generic connectivity error", async (t) => {
  t.mock.method(
    globalThis,
    "fetch",
    async () =>
      new Response(JSON.stringify({ detail: "Seçili belgelerin metni henüz okunabilir değil." }), {
        status: 409,
      }),
  );
  await assert.rejects(
    askAssistant("Örnek soru", { selectedDocumentIds: ["doc"] }),
    /metni henüz okunabilir değil/,
  );
});

test("office-project scope is sent separately from core project and case ids", async (t) => {
  const state = mockStream(
    t,
    JSON.stringify({ stage: "done", result: { answer: "Yanıt", citations: [] } }),
  );
  await askAssistant("Mevzuatı araştır.", { officeProjectId: "office-project" });
  const body = JSON.parse(state.body);
  assert.equal(body.office_project_id, "office-project");
  assert.equal(body.project_id, null);
  assert.equal(body.case_id, null);
});

test("history listing filters the fixed workspace and reload retains scope, OCR and source trust", async (t) => {
  const calls = [];
  const coverage = { total: 1, ready: 1, pending: 0, ocr: 1, failed: [] };
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push({ url, init });
    return new Response(
      JSON.stringify(
        url.includes("?")
          ? []
          : {
              project_id: null,
              case_id: "case",
              office_project_id: null,
              selected_document_ids: ["doc"],
              messages: [
                {
                  id: "message",
                  role: "assistant",
                  content: "Kaynaklı cevap",
                  grounded: true,
                  document_scope: coverage,
                  citations: [{ verification: "third_party", reference: "Derleme" }],
                },
              ],
            },
      ),
      { status: 200 },
    );
  });
  await listConversations({ caseId: "case" });
  await listConversations({ officeProjectId: "project" });
  assert.match(calls[0].url, /\?case_id=case$/);
  assert.match(calls[1].url, /\?office_project_id=project$/);
  const detail = await getConversationDetail("conversation");
  assert.deepEqual(detail.scope, {
    projectId: null,
    caseId: "case",
    officeProjectId: null,
    selectedDocumentIds: ["doc"],
  });
  assert.deepEqual(detail.messages[0].documentScope, coverage);
  assert.equal(detail.messages[0].citations[0].verification, "third_party");
  assert.equal(calls[2].init.credentials, "include");
});

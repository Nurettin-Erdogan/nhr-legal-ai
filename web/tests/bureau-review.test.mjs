import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";
import { createRequire } from "node:module";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const source = readFileSync(
  new URL("../src/lib/bureau-assistant.ts", import.meta.url),
  "utf8",
).replace("import.meta.env.VITE_API_URL", '"http://test.local"');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const module = { exports: {} };
new Function("require", "module", "exports", compiled)(
  () => ({ inMemoryAccessToken: () => null }),
  module,
  module.exports,
);
const { bureauSummaryInput, loadBureauReview, preparationNote } = module.exports;
const review = {
  proposal: { key: "hearing:example", kind: "hearing", case_id: "case-1" },
  documents: [
    { id: "doc-1", ready: true, excerpt: "Kaynak" },
    { id: "doc-2", ready: false, excerpt: "İşlenmemiş" },
    { id: "doc-3", ready: true, excerpt: null },
    { id: "doc-1", ready: true, excerpt: "Kaynak" },
  ],
};
test("bureau summary uses only distinct readable sources and preserves case scope", () => {
  const input = bureauSummaryInput(review);
  assert.deepEqual(input.document_ids, ["doc-1"]);
  assert.equal(input.case_id, "case-1");
  assert.equal(input.module, "auto_summary");
  assert.equal(input.title, "Duruşma öncesi belge özeti");
  assert.equal(input.text, undefined);
});

test("explicit document selection cannot add unknown or unreadable sources", () => {
  assert.deepEqual(bureauSummaryInput(review, ["doc-1", "foreign-id"]).document_ids, ["doc-1"]);
  assert.throws(() => bureauSummaryInput(review, []), /okunabilir belge yok/);
  assert.throws(() => bureauSummaryInput(review, ["doc-2", "foreign-id"]), /okunabilir belge yok/);
});
test("unlinked document summary does not invent a case and empty sources cannot start", () => {
  const input = bureauSummaryInput({ ...review, proposal: { kind: "document", case_id: null } });
  assert.equal(input.case_id, undefined);
  assert.throws(() => bureauSummaryInput({ ...review, documents: [] }), /okunabilir belge yok/);
});

test("preparation note distinguishes saved context from missing summary and incomplete task list", () => {
  const text = preparationNote({
    ...review,
    proposal: { ...review.proposal, case_title: "Sentetik dava" },
    generated_at: "2026-11-01T09:00:00Z",
    preparation: {
      case_no: null,
      court: "Sentetik mahkeme",
      hearing_at: "2026-11-02T10:00:00Z",
      total_documents: 20,
      ready_documents: 15,
      tasks: [{ title: "Kontrol et", due_date: null }],
      tasks_limited: true,
      checklist: ["Tarihi dosyadan doğrulayın."],
    },
  });
  assert.match(text, /Henüz belge özeti oluşturulmadı/);
  assert.match(text, /Görev listesi sınırlıdır/);
  assert.match(text, /Dosya no: Kayıtlı değil/);
  assert.match(text, /Hukuki görüş veya süre hesabı değildir/);
  assert.match(text, /Kontrol et/);
});
test("opening a review only sends an authenticated no-store GET, never a job or decision", async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (...args) => {
    calls.push(args);
    return { ok: true, json: async () => review };
  };
  try {
    await loadBureauReview("hearing:a:2026-11-01T10:00:00+03:00");
    assert.equal(calls.length, 1);
    assert.equal(calls[0][1].method, "GET");
    assert.equal(calls[0][1].cache, "no-store");
    assert.equal(calls[0][1].credentials, "include");
    assert.match(calls[0][0], /\/review\?key=hearing%3Aa/);
    assert.equal(calls[0][1].body, undefined);
  } finally {
    globalThis.fetch = original;
  }
});

test("review screen labels raw excerpts and cannot start work just by rendering", () => {
  const require = createRequire(import.meta.url);
  const componentSource = readFileSync(
    new URL("../src/components/BureauReview.tsx", import.meta.url),
    "utf8",
  );
  const output = ts.transpileModule(componentSource, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const loaded = { exports: {} };
  const values = [
    {
      ...review,
      documents: [
        {
          id: "doc-1",
          file_name: "Kaynak.pdf",
          ready: true,
          ocr: true,
          excerpt: "<script>Kaynak</script>",
        },
      ],
      suggested_action: "Kayıtlı görevi incele.",
    },
    "",
    "",
    false,
    undefined,
    undefined,
    0,
  ];
  const unexpected = () => {
    throw new Error("No network/model/write on render");
  };
  const dependencies = {
    react: {
      useState: () => [values.shift(), () => {}],
      useEffect: () => {},
      useRef: () => ({ current: true }),
    },
    "react-markdown": { default: () => null },
    "@/components/ui/button": {
      Button: ({ children, ...props }) => createElement("button", props, children),
    },
    "@/components/DocumentJobPanel": { DocumentJobPanel: () => null },
    "@/components/CaseDocumentAsk": { CaseDocumentAsk: () => null },
    "@/components/DocumentWorkflowActions": {
      DocumentWorkflowActions: ({ ids, caseId, modes }) => {
        assert.deepEqual(ids, ["doc-1"]);
        assert.equal(caseId, "case-1");
        assert.deepEqual(modes, ["draft"]);
        return createElement("span", null, "Seçili belgelerle taslak");
      },
    },
    "@/lib/router-compat": {
      Link: ({ children, to }) => createElement("a", { href: to }, children),
    },
    "@/lib/bureau-assistant": { loadBureauReview: unexpected, bureauSummaryInput },
    "@/lib/document-jobs": { loadDocumentJob: unexpected, startDocumentJob: unexpected },
  };
  new Function("require", "module", "exports", output)(
    (id) => dependencies[id] ?? require(id),
    loaded,
    loaded.exports,
  );
  const html = renderToStaticMarkup(
    createElement(loaded.exports.BureauReview, {
      proposal: review.proposal,
      onApprove: unexpected,
    }),
  );
  assert.match(html, /özet değildir/);
  assert.match(html, /OCR ile okundu/);
  assert.match(html, /Özeti oluştur/);
  assert.match(html, /İşlemi incele ve onayla/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

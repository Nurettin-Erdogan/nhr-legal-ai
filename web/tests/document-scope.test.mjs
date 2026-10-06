import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
function compile(relative, dependencies = {}) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
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

const scope = compile("../src/lib/document-scope.ts");
const { CitationList, DocumentScopeNotice } = compile("../src/components/ChatCitations.tsx", {
  "@/lib/document-scope": scope,
  "@/lib/citation-groups": compile("../src/lib/citation-groups.ts"),
});

test("scope parsing is defensive about malformed payloads", () => {
  assert.equal(scope.parseDocumentScope(null), undefined);
  assert.equal(scope.parseDocumentScope([]), undefined);
  assert.deepEqual(
    scope.parseDocumentScope({
      total: 3,
      ready: -1,
      pending: "x",
      failed: [{ file_name: "a.png" }, { reason: "yok" }, "bozuk"],
    }),
    {
      total: 3,
      ready: 0,
      pending: 0,
      ocr: 0,
      failed: [{ file_name: "a.png", reason: "Belge işlenemedi." }],
    },
  );
});

test("an unreadable or unprocessed document is never silently dropped from the summary", () => {
  const warn = scope.describeDocumentScope({
    total: 4,
    ready: 2,
    pending: 1,
    failed: [{ file_name: "tarama.pdf", reason: "OCR henüz desteklenmiyor" }],
  });
  assert.equal(warn.tone, "warn");
  assert.match(warn.lines.join(" "), /4 belgeden 2 tanesi aranabildi/);
  assert.match(warn.lines.join(" "), /1 belge henüz işlenmedi/);
  assert.match(warn.lines.join(" "), /tarama\.pdf okunamadı: OCR henüz desteklenmiyor/);

  const ok = scope.describeDocumentScope({ total: 2, ready: 2, pending: 0, ocr: 0, failed: [] });
  assert.equal(ok.tone, "ok");

  const empty = scope.describeDocumentScope({ total: 0, ready: 0, pending: 0, ocr: 0, failed: [] });
  assert.equal(empty.tone, "empty");
  assert.match(empty.lines[0], /yalnızca hukuk kaynaklarına dayanır/);
});

test("document index parsing keeps status, reason and reindex eligibility", () => {
  const index = scope.parseCaseDocumentIndex({
    documents: [
      { id: "1", file_name: "a.udf", status: "ready", error: null, chunk_count: 2, semantic_ready: true },
      { id: "2", file_name: "b.png", status: "failed", error: "OCR yok", chunk_count: 0 },
      { id: "3", file_name: "c.pdf" },
      { file_name: "kimliksiz" },
    ],
  });
  assert.equal(index.total, 3);
  assert.equal(index.ready, 1);
  assert.equal(scope.documentStatusLabel(index.documents[0]), "Aranabilir");
  assert.equal(scope.documentStatusLabel(index.documents[1]), "Okunamadı");
  assert.equal(scope.documentStatusLabel(index.documents[2]), "Bekliyor");
  assert.deepEqual(index.documents.map(scope.canReindex), [false, true, true]);
  assert.deepEqual(scope.parseCaseDocumentIndex("bozuk"), { total: 0, ready: 0, documents: [] });
});

test("user document citations are labelled as such, never as official or merely unverified", () => {
  const html = renderToStaticMarkup(
    createElement(CitationList, {
      citations: [
        { marker: "K1", source_url: null, reference: "bilirkisi_raporu.docx", verification: "user_document" },
        { marker: "K2", source_url: "https://example.test/k", reference: "Yargıtay 9. HD", verification: "official" },
        { marker: "K3", source_url: null, reference: "Arşiv kararı", verification: "third_party" },
      ],
    }),
  );
  assert.match(html, /kullanıcı belgesi/);
  assert.match(html, /doğrulanmadı/); // yalnız üçüncü taraf kayıt için
  assert.equal((html.match(/doğrulanmadı/g) ?? []).length, 1);
  assert.match(html, /bir tarafın iddiasıdır; hukuki dayanak ya da resmî kaynak değildir/);
});

test("the party-claim note only appears when a user document is cited", () => {
  const html = renderToStaticMarkup(
    createElement(CitationList, {
      citations: [{ marker: "K1", source_url: null, reference: "TBK m. 344", verification: "official" }],
    }),
  );
  assert.doesNotMatch(html, /kullanıcı belgesi/);
  assert.doesNotMatch(html, /iddiasıdır/);
});

test("scope notice warns visibly for incomplete coverage", () => {
  const html = renderToStaticMarkup(
    createElement(DocumentScopeNotice, {
      scope: { total: 2, ready: 1, pending: 0, ocr: 0, failed: [{ file_name: "x.png", reason: "OCR yok" }] },
    }),
  );
  assert.match(html, /data-tone="warn"/);
  assert.match(html, /x\.png okunamadı: OCR yok/);
});

test("OCR-read documents are flagged so numbers and dates get checked against the original", () => {
  const scoped = scope.describeDocumentScope({ total: 2, ready: 2, pending: 0, ocr: 1, failed: [] });
  assert.equal(scoped.tone, "warn"); // tam kapsam bile olsa OCR uyarısı gösterilir
  assert.match(scoped.lines.join(" "), /1 belge OCR ile okundu; okuma hataları olabilir/);
  assert.match(scoped.lines.join(" "), /belgenin aslından doğrulayın/);

  const clean = scope.describeDocumentScope({ total: 2, ready: 2, pending: 0, ocr: 0, failed: [] });
  assert.equal(clean.tone, "ok");
  assert.doesNotMatch(clean.lines.join(" "), /OCR/);
});

test("scope and index parsing read the OCR flag defensively", () => {
  assert.equal(scope.parseDocumentScope({ total: 1, ready: 1, ocr: 1 }).ocr, 1);
  assert.equal(scope.parseDocumentScope({ total: 1, ready: 1 }).ocr, 0);
  assert.equal(scope.parseDocumentScope({ total: 1, ocr: "x" }).ocr, 0);

  const index = scope.parseCaseDocumentIndex({
    documents: [
      { id: "1", file_name: "tarama.pdf", status: "ready", ocr: true },
      { id: "2", file_name: "notlar.txt", status: "ready", ocr: "evet" },
      { id: "3", file_name: "eski.docx", status: "ready" },
    ],
  });
  assert.deepEqual(index.documents.map((item) => item.ocr), [true, false, false]);
});

test("a documents-only answer says legal sources were not consulted", () => {
  const parsed = scope.parseDocumentScope({ total: 2, ready: 2, pending: 0, ocr: 0, failed: [], file_only: true });
  assert.equal(parsed.fileOnly, true);
  const summary = scope.describeDocumentScope(parsed);
  assert.equal(summary.tone, "ok");
  assert.match(summary.lines.join(" "), /yalnız dava belgelerinizden cevaplandı; kanun ve içtihat kaynaklarına bakılmadı/);

  const mixed = scope.parseDocumentScope({ total: 2, ready: 2, pending: 0, ocr: 0, failed: [], file_only: false });
  assert.equal("fileOnly" in mixed, false);
  assert.doesNotMatch(scope.describeDocumentScope(mixed).lines.join(" "), /bakılmadı/);
});

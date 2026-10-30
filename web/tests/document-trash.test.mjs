import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
function compile(relative, dependencies = {}) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8").replace(
    "import.meta.env.VITE_API_URL",
    '"http://test.local"',
  );
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

const trash = compile("../src/lib/document-trash.ts", {
  "@/lib/auth-api": { inMemoryAccessToken: () => "unit-token" },
});
const { DocumentTrash } = compile("../src/components/DocumentTrash.tsx", {
  "@/components/ui/button": { Button: (props) => createElement("button", props) },
  "@/lib/document-trash": trash,
  "@/lib/confirmation": { confirmAction: async () => true },
});

const id = "11111111-1111-4111-8111-111111111111";

function mockFetch(t, response) {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push({ url: String(url), init });
    return response;
  });
  return calls;
}
const ok = (body) => ({ ok: true, status: 200, json: async () => body });

test("trash, restore and permanent delete use the right method, path and credentials", async (t) => {
  const calls = mockFetch(t, ok({ trashed: true, deleted: true, redacted_answers: 2 }));

  await trash.trashDocument(id);
  await trash.restoreDocument(id);
  const result = await trash.deleteDocumentForever(id);

  assert.deepEqual(
    calls.map((call) => [call.init.method, call.url]),
    [
      ["POST", `http://test.local/api/office/documents/${id}/trash`],
      ["POST", `http://test.local/api/office/documents/${id}/restore`],
      ["DELETE", `http://test.local/api/office/documents/${id}`],
    ],
  );
  assert.ok(calls.every((call) => call.init.credentials === "include"));
  assert.ok(calls.every((call) => call.init.headers.Authorization === "Bearer unit-token"));
  assert.equal(result.redacted_answers, 2);
});

test("bulk trash posts only validated document ids to the batch endpoint", async (t) => {
  const second = "22222222-2222-4222-8222-222222222222";
  const calls = mockFetch(t, ok({ requested: 2, trashed: 2, not_found: 0, retention_days: 30 }));

  const result = await trash.trashDocuments([id, second, id]);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].url, "http://test.local/api/office/documents/trash/batch");
  assert.equal(calls[0].init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(calls[0].init.body), { document_ids: [id, second] });
  assert.deepEqual(result, { requested: 2, trashed: 2, not_found: 0, retention_days: 30 });
});

test("a malformed document id never reaches the network", async (t) => {
  const calls = mockFetch(t, ok({}));
  await assert.rejects(trash.trashDocument("../etc/passwd"), /Geçersiz belge kimliği/);
  await assert.rejects(trash.deleteDocumentForever("1; DROP"), /Geçersiz belge kimliği/);
  await assert.rejects(trash.listTrash("bozuk"), /Geçersiz belge kimliği/);
  await assert.rejects(trash.trashDocuments([id, "bozuk"]), /Geçersiz belge kimliği/);
  assert.equal(calls.length, 0);
});

test("server error details are surfaced to the user", async (t) => {
  mockFetch(t, {
    ok: false,
    status: 409,
    json: async () => ({ detail: "Belge önce çöp kutusuna taşınmalı" }),
  });
  await assert.rejects(trash.deleteDocumentForever(id), (error) => {
    assert.match(error.message, /önce çöp kutusuna taşınmalı/);
    assert.equal(error.status, 409);
    return true;
  });
});

test("listing is scoped to a case and parsed defensively", async (t) => {
  const calls = mockFetch(
    t,
    ok({
      retention_days: 30,
      documents: [
        {
          id,
          file_name: "rapor.pdf",
          case_id: id,
          size_bytes: 10,
          deleted_at: "2026-10-01T10:00:00Z",
          days_left: 29,
          cited_answers: 2,
        },
        { id: "x" },
        "bozuk",
      ],
    }),
  );
  const listing = await trash.listTrash(id);
  assert.match(calls[0].url, new RegExp(`/api/office/documents/trash\\?case_id=${id}$`));
  assert.equal(listing.documents.length, 1);
  assert.equal(listing.documents[0].cited_answers, 2);
  assert.deepEqual(trash.parseTrashListing(null), { retention_days: 30, documents: [] });
});

test("retention text tells when the document will be deleted for good", () => {
  assert.equal(trash.describeRetention({ days_left: 30 }), "30 gün sonra kalıcı silinecek");
  assert.equal(trash.describeRetention({ days_left: 1 }), "Yarın kalıcı silinecek");
  assert.equal(trash.describeRetention({ days_left: 0 }), "Bugün kalıcı silinecek");
});

test("permanent delete warns that it cannot be undone and that cited answers are removed too", () => {
  const plain = trash.permanentDeleteWarning({ file_name: "rapor.pdf", cited_answers: 0 });
  assert.match(plain, /"rapor\.pdf" KALICI olarak silinsin mi\?/);
  assert.match(plain, /geri alınamaz/);
  assert.doesNotMatch(plain, /sohbet cevabı/);

  const cited = trash.permanentDeleteWarning({ file_name: "rapor.pdf", cited_answers: 3 });
  assert.match(cited, /3 sohbet cevabı da kaldırılır/);
});

test("trash panel explains that trashed documents are not searched and can be restored", () => {
  const html = renderToStaticMarkup(createElement(DocumentTrash, { caseId: id }));
  assert.match(html, /aria-label="Çöp kutusu"/);
  assert.match(html, /aranmaz ve listelerde görünmez/);
  assert.match(html, /geri yükleyebilirsiniz/);
});

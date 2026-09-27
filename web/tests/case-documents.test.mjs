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
const model = compile("../src/lib/case-documents.ts", {
  "@/lib/db": { db: {} },
  "@/lib/auth-api": { inMemoryAccessToken: () => "unit-token" },
});
const { CaseDocumentActions } = compile("../src/components/CaseDocumentActions.tsx", {
  "../lib/case-documents": model,
});
const caseId = "11111111-1111-4111-8111-111111111111";
const documentId = "22222222-2222-4222-8222-222222222222";

test("invalid files and identifiers fail before sending a request", async (t) => {
  const calls = t.mock.method(globalThis, "fetch", () => {
    throw new Error("unexpected network");
  });
  for (const file of [
    { size: 0, name: "x" },
    { size: model.MAX_CASE_FILE_SIZE + 1, name: "x" },
    { size: 1, name: "" },
  ]) {
    assert.throws(() => model.validateCaseFile(file));
  }
  await assert.rejects(model.uploadCaseDocument("invalid", new File(["x"], "x.txt")), /kimliği/);
  await assert.rejects(model.linkCaseDocument(caseId, "invalid"), /kimliği/);
  assert.equal(calls.mock.callCount(), 0);
});
test("upload uses multipart authenticated case endpoint; link has no client-controlled owner", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push({ url, ...init });
    return new Response(JSON.stringify({ id: documentId, case_id: caseId }), { status: 201 });
  });
  await model.uploadCaseDocument(caseId, new File(["real bytes"], "dilekçe.txt"));
  await model.linkCaseDocument(caseId, documentId);
  assert.equal(calls[0].url, `http://test.local/api/office/cases/${caseId}/documents`);
  assert.equal(await calls[0].body.get("file").text(), "real bytes");
  assert.equal(calls[0].body.get("owner_id"), null);
  assert.equal(calls[0].headers["Content-Type"], undefined);
  assert.equal(calls[0].headers.Authorization, "Bearer unit-token");
  assert.equal(calls[0].credentials, "include");
  assert.equal(
    calls[1].url,
    `http://test.local/api/office/cases/${caseId}/documents/${documentId}/link`,
  );
  assert.equal(calls[1].body, undefined);
});
test("server conflicts and ambiguous network results remain errors, no automatic retries", async (t) => {
  const fetch = t.mock.method(
    globalThis,
    "fetch",
    async () => new Response(JSON.stringify({ detail: "Başka davaya bağlı" }), { status: 409 }),
  );
  await assert.rejects(model.linkCaseDocument(caseId, documentId), /Başka davaya/);
  fetch.mock.mockImplementation(async () => {
    throw new Error("offline");
  });
  await assert.rejects(
    model.uploadCaseDocument(caseId, new File(["x"], "x.txt")),
    /evrak listesini yenileyip/,
  );
  assert.equal(fetch.mock.callCount(), 2);
  fetch.mock.mockImplementation(
    async () =>
      new Response(JSON.stringify({ id: documentId, case_id: documentId }), { status: 200 }),
  );
  await assert.rejects(model.linkCaseDocument(caseId, documentId), /doğrulanamadı/);
});
test("unlinked document search is paginated and escaped", async () => {
  const calls = [];
  const client = {
    from(table) {
      calls.push(["from", table]);
      return {
        select(s) {
          calls.push(["select", s]);
          return this;
        },
        is(k, v) {
          calls.push(["is", k, v]);
          return this;
        },
        order(k, v) {
          calls.push(["order", k, v]);
          return this;
        },
        ilike(k, v) {
          calls.push(["ilike", k, v]);
          return this;
        },
        range(a, b) {
          calls.push(["range", a, b]);
          return Promise.resolve({
            data: Array.from({ length: 26 }, (_, i) => ({ id: i })),
            error: null,
          });
        },
      };
    },
  };
  const result = await model.listUnlinkedDocuments("a%b_c", 2, client);
  assert.deepEqual(
    calls.find((x) => x[0] === "is"),
    ["is", "case_id", null],
  );
  assert.deepEqual(
    calls.find((x) => x[0] === "range"),
    ["range", 50, 75],
  );
  assert.deepEqual(
    calls.find((x) => x[0] === "ilike"),
    ["ilike", "file_name", "%a\\%b\\_c%"],
  );
  assert.equal(result.rows.length, 25);
  assert.equal(result.hasMore, true);
});
test("document action UI clearly states storage-only behavior and requires a selected file", () => {
  const html = renderToStaticMarkup(
    createElement(CaseDocumentActions, { caseId, clientId: null, onSaved() {} }),
  );
  assert.match(html, /RAG indeksleme yapmaz/);
  assert.match(html, /Mevcut belgeyi bağla/);
  assert.match(html, /type="file"/);
  assert.match(html, /disabled=""/);
  assert.doesNotMatch(html, /başarı|%72/);
});

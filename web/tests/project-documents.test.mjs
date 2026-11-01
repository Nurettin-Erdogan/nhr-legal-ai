import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function compile(path, deps = {}) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8").replaceAll(
    "import.meta.env",
    "({})",
  );
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  new Function("require", "module", "exports", code)(
    (name) => {
      if (name in deps) return deps[name];
      throw new Error("Unexpected import " + name);
    },
    module,
    module.exports,
  );
  return module.exports;
}
const api = compile("../src/lib/project-documents.ts", {
  "@/lib/auth-api": { inMemoryAccessToken: () => "synthetic-token" },
});
const workflow = compile("../src/lib/document-workflow.ts");

test("project document listing fetches every page, sends auth, and does not duplicate documents", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push({ url, init });
    const offset = Number(new URL(url).searchParams.get("offset"));
    return new Response(
      JSON.stringify({
        project_id: "project",
        case_id: null,
        total: 501,
        ready: 501,
        pending: 0,
        ocr: 0,
        failed: [],
        documents: Array.from({ length: offset === 0 ? 500 : 1 }, (_, i) => ({
          id: String(offset + i),
          file_name: "Belge",
          status: "ready",
        })),
      }),
    );
  });
  const result = await api.getProjectDocuments("project");
  assert.equal(result.documents.length, 501);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].init.credentials, "include");
  assert.equal(calls[0].init.headers.Authorization, "Bearer synthetic-token");
});

test("a changing or truncated project list is rejected, not presented as complete", async (t) => {
  t.mock.method(
    globalThis,
    "fetch",
    async () =>
      new Response(JSON.stringify({ project_id: "project", total: 2, documents: [{ id: "doc" }] })),
  );
  await assert.rejects(api.getProjectDocuments("project"), /Liste|liste/);
});

test("attach transmits only ids and unlink calls the association endpoint, not file deletion", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push({ url, init });
    return init.method === "DELETE"
      ? new Response(null, { status: 204 })
      : new Response(JSON.stringify({ linked: 1, already_linked: 0 }));
  });
  await api.linkProjectDocuments("project", ["doc"]);
  await api.unlinkProjectDocument("project", "doc");
  assert.deepEqual(JSON.parse(calls[0].init.body), { document_ids: ["doc"] });
  assert.equal(calls[1].init.method, "DELETE");
  assert.match(calls[1].url, /\/projects\/project\/documents\/doc$/);
  assert.equal(calls[1].init.body, undefined);
});

test("API access errors stay explicit", async (t) => {
  t.mock.method(
    globalThis,
    "fetch",
    async () => new Response(JSON.stringify({ detail: "Proje kapsamı değişti." }), { status: 409 }),
  );
  await assert.rejects(api.getProjectDocuments("project"), /Proje kapsamı değişti/);
});

test("project document handoff preserves the owner-scoped project and forbids case/project ambiguity", () => {
  const entries = new Map();
  const storage = {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
    removeItem: (key) => entries.delete(key),
  };
  const project = "00000000-0000-0000-0000-000000000001",
    doc = "00000000-0000-0000-0000-000000000002";
  const key = workflow.saveDocumentContext("alice", [doc], undefined, storage, project);
  assert.equal(workflow.readDocumentContext("alice", key, storage).officeProjectId, project);
  assert.equal(workflow.readDocumentContext("bob", key, storage), null);
  assert.throws(
    () => workflow.saveDocumentContext("alice", [doc], project, storage, project),
    /kapsamı/,
  );
});

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function compile(path) {
  const { outputText } = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("module", "exports", outputText)(module, module.exports);
  return module.exports;
}
const workflow = compile("../src/lib/document-workflow.ts");
const editor = compile("../src/lib/document-editor.ts");
const id = "11111111-1111-4111-8111-111111111111";
const caseId = "22222222-2222-4222-8222-222222222222";
const storage = () => {
  const rows = new Map();
  return {
    rows,
    getItem: (key) => rows.get(key) ?? null,
    setItem: (key, value) => rows.set(key, value),
    removeItem: (key) => rows.delete(key),
  };
};

test("a document handoff keeps exact ids/case, is owner-scoped, and exposes no ids in the URL", () => {
  const store = storage();
  const key = workflow.saveDocumentContext("alice", [id, id], caseId, store);
  assert.deepEqual(workflow.readDocumentContext("alice", key, store).ids, [id]);
  assert.equal(workflow.readDocumentContext("alice", key, store).caseId, caseId);
  assert.equal(workflow.readDocumentContext("bob", key, store), null);
  assert.equal(workflow.readDocumentContext("alice", key, storage()), null);
  assert.equal(
    workflow.workflowPath("analysis", key),
    `/dashboard/ai?mode=analysis&context=${key}`,
  );
  assert.equal(workflow.workflowPath("draft", key), `/dashboard/drafts?context=${key}`);
  assert.ok(!workflow.workflowPath("summary", key).includes(id));
});

test("expired, malformed, oversized and foreign contexts never become an empty successful selection", () => {
  const store = storage();
  assert.throws(() => workflow.saveDocumentContext("alice", ["bad"], undefined, store));
  assert.throws(() => workflow.saveDocumentContext("alice", [id], "bad", store));
  assert.throws(() => workflow.saveDocumentContext("alice", Array(2001).fill(id), undefined, store));
  assert.ok(workflow.saveDocumentContext("alice", Array(50).fill(id), undefined, storage()));
  const key = workflow.saveDocumentContext("alice", [id], undefined, store);
  const context = workflow.readDocumentContext("alice", key, store);
  assert.equal(
    workflow.readDocumentContext("alice", key, store, context.createdAt + 31 * 60 * 1000),
    null,
  );
  assert.equal(store.rows.size, 0);
  store.setItem(
    `jurisai.document-context:alice:${key}`,
    JSON.stringify({ ids: ["bad"], createdAt: Date.now() }),
  );
  assert.equal(workflow.readDocumentContext("alice", key, store), null);
});

function text(value) {
  return { nodeType: 3, textContent: value };
}
function element(tag, children) {
  const node = {
    nodeType: 1,
    tagName: tag.toUpperCase(),
    childNodes: children,
    children: children.filter((child) => child.nodeType === 1),
  };
  for (const child of children) child.parentElement = node;
  return node;
}

test("editing preserves Turkish names, amounts, dates, citations and paragraph/list structure", () => {
  const tree = element("div", [
    element("h2", [text("SONUÇ VE İSTEM")]),
    element("p", [
      text("Çağrı Şahin, 13.10.2026 tarihinde "),
      element("strong", [text("340.000 TL")]),
      text(" talep etti. [K1]"),
    ]),
    element("ol", [
      element("li", [text("Delil: 2024/261409")]),
      element("li", [text("Tebliğ tarihi: 07.10.2026")]),
    ]),
  ]);
  assert.equal(
    editor.editableToMarkdown(tree),
    "## SONUÇ VE İSTEM\n\nÇağrı Şahin, 13.10.2026 tarihinde **340.000 TL** talep etti. [K1]\n\n1. Delil: 2024/261409\n2. Tebliğ tarihi: 07.10.2026",
  );
  assert.equal(
    editor.editableToMarkdown(
      element("div", [element("script", [text("evil()")]), element("p", [text("Güvenli metin")])]),
    ),
    "Güvenli metin",
  );
});

test("Word export retains emphasis, literal underscores, references and exact amounts", () => {
  assert.deepEqual(editor.documentInlineRuns("Dosya_A: **340.000 TL**, *07.10.2026* [K1]."), [
    { text: "Dosya_A: " },
    { text: "340.000 TL", bold: true },
    { text: ", " },
    { text: "07.10.2026", italics: true },
    { text: " [K1]." },
  ]);
  assert.deepEqual(editor.documentInlineRuns("[Kaynak](https://example.org/karar)"), [
    { text: "Kaynak (https://example.org/karar)" },
  ]);
});

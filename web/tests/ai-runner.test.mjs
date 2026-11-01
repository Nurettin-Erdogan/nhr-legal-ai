import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

// Exercise the real component's change/click handlers with deterministic hook state.
// Effects and external services are isolated; no live account/model is used.
function runner(props) {
  const state = [];
  let cursor = 0;
  const calls = { research: [], jobs: [], errors: [] };
  const ui = new Proxy({}, { get: (_, key) => String(key) });
  const jsx = (type, props) => ({ type, props });
  const deps = {
    react: {
      useState: (initial) => {
        const index = cursor++;
        if (!(index in state)) state[index] = initial;
        return [
          state[index],
          (value) => {
            state[index] = value;
          },
        ];
      },
      useRef: () => ({ current: null }),
      useEffect: () => {},
    },
    "react/jsx-runtime": { jsx, jsxs: jsx },
    "@/lib/backend": {
      invokeFunction: () => {
        throw new Error("Unexpected legacy AI call");
      },
    },
    "@/lib/ai-api": {
      askAssistant: async (...args) => {
        calls.research.push(args);
        return {
          answer: "Doğrulanmış cevap",
          grounded: true,
          citations: [
            { marker: "[K1]", reference: "Kira belgesi", verification: "user_document" },
            {
              marker: "[K2]",
              reference: "Derleme",
              verification: "third_party",
              source_id: "12345678-1234-1234-1234-123456789abc",
              source_type: "court_decision",
              excerpt: "Kayıtlı pasaj",
            },
          ],
        };
      },
    },
    "@/lib/document-scope": { describeDocumentScope: () => ({ lines: [] }) },
    "@/lib/document-jobs": {
      startDocumentJob: async (body) => {
        calls.jobs.push(body);
        return "job";
      },
    },
    "@/components/AuthContext": { useAuth: () => ({ session: { user: { id: "owner" } } }) },
    "@/integrations/supabase/client": { supabase: {} },
    "@/lib/utils": { cn: (...args) => args.join(" ") },
    "react-markdown": { __esModule: true, default: "Markdown" },
    sonner: { toast: { success: () => {}, error: (message) => calls.errors.push(message) } },
  };
  const source = readFileSync(new URL("../src/components/AIRunner.tsx", import.meta.url), "utf8");
  const code = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const module = { exports: {} };
  new Function("require", "module", "exports", code)(
    (name) => {
      if (name in deps) return deps[name];
      if (name.startsWith("@/components/") || name === "lucide-react") return ui;
      throw new Error("Unexpected dependency " + name);
    },
    module,
    module.exports,
  );
  function render() {
    cursor = 0;
    return module.exports.AIRunner({ placeholder: "İstek", ...props });
  }
  return { calls, render };
}

function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  if (!tree || typeof tree !== "object") return [];
  return [tree, ...nodes(tree.props?.children)];
}
function inputs(tree) {
  return nodes(tree).filter((node) => node.type === "Textarea");
}
function run(tree) {
  return nodes(tree)
    .find((node) => node.type === "Button" && node.props.children?.includes("Çalıştır"))
    .props.onClick();
}

for (const mode of ["research", "case_law", "semantic_case_search", "agent_research"]) {
  test(`${mode}: actual Run handler sends chosen documents and case scope`, async () => {
    const view = runner({ module: mode, initialDocIds: ["doc-1", "doc-2"], caseId: "case-1" });
    inputs(view.render())[0].props.onChange({ target: { value: "Seçili belgelerde ne yazıyor?" } });
    await run(view.render());
    assert.deepEqual(view.calls.research, [
      [
        "Seçili belgelerde ne yazıyor?",
        { caseId: "case-1", selectedDocumentIds: ["doc-1", "doc-2"] },
      ],
    ]);
    assert.deepEqual(view.calls.errors, []);
    const tree = view.render();
    const output = nodes(tree).find((node) => node.type === "Markdown").props.children;
    assert.equal(output, "Doğrulanmış cevap");
    const citations = nodes(tree).find((node) => node.type === "CitationList").props.citations;
    assert.equal(citations[0].verification, "user_document");
    assert.equal(citations[1].verification, "third_party");
    assert.equal(citations[1].source_id, "12345678-1234-1234-1234-123456789abc");
    assert.equal(citations[1].excerpt, "Kayıtlı pasaj");
  });
}

test("analysis of pasted text sends the instruction separately, not as document evidence", async () => {
  const view = runner({ module: "document_analysis" });
  const fields = inputs(view.render());
  assert.equal(fields.length, 2);
  fields[0].props.onChange({ target: { value: "Kiracı aylık 12.000 TL öder." } });
  fields[1].props.onChange({ target: { value: "Yalnız ödeme tutarını incele." } });
  await run(view.render());
  assert.equal(view.calls.jobs[0].text, "Kiracı aylık 12.000 TL öder.");
  assert.equal(view.calls.jobs[0].prompt, "Yalnız ödeme tutarını incele.");
  assert.deepEqual(view.calls.jobs[0].document_ids, []);
  assert.deepEqual(view.calls.errors, []);
});

test("analysis of selected documents treats the main input as instruction and sends no pasted text", async () => {
  const view = runner({ module: "document_analysis", initialDocIds: ["doc"], caseId: "case" });
  const fields = inputs(view.render());
  assert.equal(fields.length, 1);
  fields[0].props.onChange({ target: { value: "Ödeme vadelerini incele." } });
  await run(view.render());
  assert.equal(view.calls.jobs[0].text, "");
  assert.equal(view.calls.jobs[0].prompt, "Ödeme vadelerini incele.");
  assert.deepEqual(view.calls.jobs[0].document_ids, ["doc"]);
  assert.equal(view.calls.jobs[0].case_id, "case");
});

test("project document analysis carries the office project id into the persistent job", async () => {
  const view = runner({
    module: "document_analysis",
    initialDocIds: ["doc"],
    officeProjectId: "project",
  });
  inputs(view.render())[0].props.onChange({ target: { value: "Ödeme tutarını incele." } });
  await run(view.render());
  assert.equal(view.calls.jobs[0].project_id, "project");
  assert.equal(view.calls.jobs[0].case_id, undefined);
});

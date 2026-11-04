import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const code = ts.transpileModule(
  readFileSync(new URL("../src/components/AssistantWorkspace.tsx", import.meta.url), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } },
).outputText;
function render(mode, context) {
  const component = (name) => Object.assign(() => null, { displayName: name });
  const Chat = component("chat"),
    Deep = component("deep"),
    Runner = component("runner");
  const jsx = (type, props, key) => ({ type, props: props ?? {}, key });
  const modules = {
    "react/jsx-runtime": { jsx, jsxs: jsx },
    "@/components/LegalChat": { LegalChat: Chat },
    "@/components/DeepResearch": { DeepResearch: Deep },
    "@/components/AIRunner": { AIRunner: Runner },
    "@/components/AuthContext": { useAuth: () => ({ user: { id: "alice" } }) },
    "@/lib/document-workflow": {
      DOCUMENT_MODES: {
        analysis: { module: "document_analysis", prompt: "analyze" },
        summary: { module: "auto_summary" },
        risk: { module: "risk_analysis" },
      },
      readDocumentContext: () => context,
    },
    "@/lib/router-compat": { Link: "a" },
    "@/lib/router-hooks": {
      useSearchParam: (key) =>
        key === "mode" ? mode : context === undefined ? null : "context-key",
    },
    "@/lib/utils": { cn: (...parts) => parts.filter(Boolean).join(" ") },
  };
  const mod = { exports: {} };
  new Function("require", "module", "exports", code)(
    (id) => {
      assert.ok(id in modules, id);
      return modules[id];
    },
    mod,
    mod.exports,
  );
  const nodes = [];
  function visit(value) {
    if (Array.isArray(value)) return value.forEach(visit);
    if (!value || typeof value !== "object") return;
    nodes.push(value);
    visit(value.props?.children);
  }
  visit(mod.exports.AssistantWorkspace());
  return { nodes, Chat, Deep, Runner };
}

test("all five modes have visible navigation and unknown modes fall back to chat", () => {
  const { nodes } = render("unknown");
  const links = nodes.filter((node) => node.type === "a");
  assert.equal(links.length, 5);
  assert.deepEqual(
    links.map((node) => node.props.children),
    ["Sohbet", "Derin araştırma", "Belge analizi", "Özetle", "Risk incelemesi"],
  );
  assert.equal(links[0].props["aria-current"], "page");
  assert.ok(!nodes.find((node) => node.type === "nav").props.className.includes("hidden"));
});

for (const [mode, module] of [
  ["analysis", "document_analysis"],
  ["summary", "auto_summary"],
  ["risk", "risk_analysis"],
]) {
  test(`${mode} opens the correct module and preserves document scope`, () => {
    const context = { ids: ["doc-1"], caseId: "case-1", officeProjectId: "project-1" };
    const { nodes, Runner, Chat } = render(mode, context);
    const runner = nodes.find((node) => node.type === Runner);
    assert.equal(runner.props.module, module);
    assert.deepEqual(runner.props.initialDocIds, context.ids);
    assert.equal(runner.props.caseId, "case-1");
    assert.equal(runner.props.officeProjectId, "project-1");
    assert.ok(nodes.some((node) => node.type === Chat));
    assert.ok(
      nodes
        .filter((node) => node.type === "a")
        .every((node) => node.props.to.includes("context=context-key")),
    );
  });
}

test("deep research opens and invalid document context blocks document runner", () => {
  const deep = render("deep");
  assert.ok(deep.nodes.some((node) => node.type === deep.Deep));
  const invalid = render("analysis", null);
  assert.ok(!invalid.nodes.some((node) => node.type === invalid.Runner));
  assert.ok(invalid.nodes.some((node) => node.props.role === "alert"));
});

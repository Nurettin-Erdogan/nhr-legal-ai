import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

// Exercise handlers/effects without a model call or a user account.
function harness({ failure = false, available = true } = {}) {
  const slots = [],
    calls = [],
    approvals = [];
  let cursor = 0,
    effects = [];
  const proposal = { key: "document:old", kind: "document", case_id: "case-a" };
  const data = {
    proposal: { ...proposal, title: "Fresh server title" },
    action_available: available,
    suggested_action: "Review the record",
    documents: [
      { id: "a", file_name: "a.pdf", ready: true, excerpt: "A" },
      { id: "b", file_name: "b.pdf", ready: true, excerpt: "B" },
      { id: "c", file_name: "c.pdf", ready: false },
    ],
  };
  const jsx = (type, props) => ({ type, props });
  const deps = {
    react: {
      useState(initial) {
        const i = cursor++;
        if (!(i in slots)) slots[i] = initial;
        return [
          slots[i],
          (v) => {
            slots[i] = typeof v === "function" ? v(slots[i]) : v;
          },
        ];
      },
      useRef(initial) {
        const i = cursor++;
        return (slots[i] ??= { current: initial });
      },
      useEffect(effect, dependencies) {
        const i = cursor++,
          old = slots[i];
        if (!old || dependencies.some((v, n) => !Object.is(v, old.dependencies[n]))) {
          const entry = (slots[i] = { dependencies, cleanup: old?.cleanup });
          effects.push(() => {
            entry.cleanup?.();
            entry.cleanup = effect();
          });
        }
      },
    },
    "react/jsx-runtime": { jsx, jsxs: jsx },
    "react-markdown": { default: "Markdown" },
    "@/components/ui/button": { Button: "Button" },
    "@/components/DocumentJobPanel": { DocumentJobPanel: "History" },
    "@/components/CaseDocumentAsk": { CaseDocumentAsk: "CaseChat" },
    "@/components/DocumentWorkflowActions": { DocumentWorkflowActions: "Workflow" },
    "@/lib/router-compat": { Link: "Link" },
    "@/lib/bureau-assistant": {
      loadBureauReview: async () => {
        calls.push("review");
        if (failure) throw Error("Review unavailable");
        return data;
      },
      loadCasePreparation: () => {
        throw Error("Unexpected hearing request");
      },
      bureauSummaryInput: (value, ids) => ({
        module: "auto_summary",
        case_id: value.proposal.case_id,
        document_ids: ids,
      }),
    },
    "@/lib/document-jobs": {
      startDocumentJob: async (input) => {
        calls.push(input);
        return "job-1";
      },
      loadDocumentJob: async (id) => {
        calls.push(id);
        return { id, state: "done", output: "Saved summary", progress: { done: 1, total: 1 } };
      },
    },
  };
  const code = ts.transpileModule(
    readFileSync(new URL("../src/components/BureauReview.tsx", import.meta.url), "utf8"),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        jsx: ts.JsxEmit.ReactJSX,
        target: ts.ScriptTarget.ES2022,
      },
    },
  ).outputText;
  const loaded = { exports: {} };
  new Function("require", "module", "exports", code)(
    (id) => {
      assert.ok(id in deps, `Unexpected dependency: ${id}`);
      return deps[id];
    },
    loaded,
    loaded.exports,
  );
  return {
    calls,
    approvals,
    data,
    render() {
      cursor = 0;
      const tree = loaded.exports.BureauReview({ proposal, onApprove: (p) => approvals.push(p) });
      const pending = effects;
      effects = [];
      pending.forEach((f) => f());
      return tree;
    },
    dispose() {
      slots.forEach((s) => s?.cleanup?.());
    },
  };
}
function nodes(node) {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}
const settle = async () => {
  for (let i = 0; i < 8; i++) await Promise.resolve();
};
function button(tree, label) {
  return nodes(tree).find((n) => n.type === "Button" && n.props.children === label);
}

test("review opening is read-only and only explicit approval uses the fresh proposal", async () => {
  const h = harness();
  try {
    h.render();
    await settle();
    const tree = h.render();
    assert.deepEqual(h.calls, ["review"]);
    assert.deepEqual(h.approvals, []);
    button(tree, "İşlemi incele ve onayla").props.onClick();
    assert.deepEqual(h.approvals, [h.data.proposal]);
    assert.deepEqual(h.calls, ["review"]);
  } finally {
    h.dispose();
  }
});

test("summary starts only for selected ready documents and freezes selection", async () => {
  const h = harness();
  try {
    h.render();
    await settle();
    let tree = h.render();
    const inputs = nodes(tree).filter((n) => n.type === "input");
    assert.equal(inputs[2].props.disabled, true);
    inputs[1].props.onChange({ target: { checked: false } });
    tree = h.render();
    assert.deepEqual(nodes(tree).find((n) => n.type === "Workflow").props.ids, ["a"]);
    button(tree, "Özeti oluştur").props.onClick();
    await settle();
    h.render();
    await settle();
    tree = h.render();
    assert.deepEqual(h.calls, [
      "review",
      { module: "auto_summary", case_id: "case-a", document_ids: ["a"] },
      "job-1",
    ]);
    assert.ok(
      nodes(tree)
        .filter((n) => n.type === "input")
        .every((n) => n.props.disabled),
    );
    assert.equal(nodes(tree).find((n) => n.type === "Markdown").props.children, "Saved summary");
    assert.deepEqual(h.approvals, []);
  } finally {
    h.dispose();
  }
});

test("no selection disables summary and a failed review exposes no action", async () => {
  const h = harness(),
    failed = harness({ failure: true });
  try {
    h.render();
    failed.render();
    await settle();
    let tree = h.render();
    for (const input of nodes(tree).filter((n) => n.type === "input" && !n.props.disabled)) {
      // Rerender between changes as React does after each user interaction.
      const current = nodes(h.render()).find(
        (n) => n.type === "input" && n.props["aria-label"] === input.props["aria-label"],
      );
      current.props.onChange({ target: { checked: false } });
    }
    tree = h.render();
    assert.equal(button(tree, "Özeti oluştur").props.disabled, true);
    const failedTree = failed.render();
    assert.equal(button(failedTree, "Özeti oluştur"), undefined);
    assert.equal(button(failedTree, "İşlemi incele ve onayla"), undefined);
    assert.deepEqual(h.calls, ["review"]);
    assert.deepEqual(failed.calls, ["review"]);
  } finally {
    h.dispose();
    failed.dispose();
  }
});

test("already handled preparation cannot offer another approval", async () => {
  const h = harness({ available: false });
  try {
    h.render();
    await settle();
    assert.equal(button(h.render(), "İşlemi incele ve onayla"), undefined);
    assert.deepEqual(h.approvals, []);
  } finally {
    h.dispose();
  }
});

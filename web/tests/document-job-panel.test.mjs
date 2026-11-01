import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function harness() {
  let slots = [],
    cursor = 0,
    effects = [],
    owner = "alice";
  const changes = [],
    loads = [];
  const jobs = ["a", "b"].map((id) => ({
    id,
    module: "auto_summary",
    state: "done",
    output_id: `out-${id}`,
    output: `Özet-${id}`,
    progress: { total: 1, done: 1, documents: [{ file_name: `${id}.pdf` }] },
  }));
  let detail = async (id) => jobs.find((j) => j.id === id);
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
    "@/components/AuthContext": { useAuth: () => ({ user: { id: owner } }) },
    "@/components/ui/button": { Button: "Button" },
    "lucide-react": { Loader2: "Loader2" },
    "@/lib/document-jobs": {
      listDocumentJobs: async () => (owner === "alice" ? jobs : []),
      loadDocumentJob: async (id) => {
        loads.push(id);
        return detail(id);
      },
      cancelDocumentJob: async () => {
        throw Error("Unexpected mutation");
      },
      resumeDocumentJob: async () => {
        throw Error("Unexpected mutation");
      },
    },
  };
  const code = ts.transpileModule(
    readFileSync(new URL("../src/components/DocumentJobPanel.tsx", import.meta.url), "utf8"),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    },
  ).outputText;
  const module = { exports: {} };
  new Function("require", "module", "exports", code)(
    (id) => {
      if (!(id in deps)) throw Error(id);
      return deps[id];
    },
    module,
    module.exports,
  );
  function render() {
    cursor = 0;
    const tree = module.exports.DocumentJobPanel({
      module: "auto_summary",
      onJobChange: (v) => changes.push(v?.output),
    });
    const pending = effects;
    effects = [];
    pending.forEach((f) => f());
    return tree;
  }
  return {
    render,
    changes,
    loads,
    jobs,
    switchOwner() {
      owner = "bob";
    },
    detail(fn) {
      detail = fn;
    },
    dispose() {
      slots.forEach((s) => s?.cleanup?.());
    },
  };
}
function buttons(node) {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap(buttons);
  return [...(node.type === "Button" ? [node] : []), ...buttons(node.props?.children)];
}
const settle = async () => {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
};
async function select(h, id) {
  const tree = h.render();
  const button = buttons(tree).find((b) => JSON.stringify(b.props.children).includes(`${id}.pdf`));
  assert.ok(button);
  button.props.onClick();
  assert.equal(h.changes.at(-1), undefined);
  h.render();
  await settle();
  h.render();
}
test("switching saved jobs clears the old output and reopening an earlier job restores it", async () => {
  const h = harness();
  try {
    h.render();
    await settle();
    h.render();
    await select(h, "a");
    assert.equal(h.changes.at(-1), "Özet-a");
    await select(h, "b");
    assert.equal(h.changes.at(-1), "Özet-b");
    await select(h, "a");
    assert.equal(h.changes.at(-1), "Özet-a");
  } finally {
    h.dispose();
  }
});
test("an in-flight response from the old owner cannot republish its private output", async () => {
  const h = harness();
  let resolve;
  try {
    h.render();
    await settle();
    h.render();
    h.detail(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
    await select(h, "a");
    const resolveOldOwner = resolve;
    h.switchOwner();
    h.render();
    await settle();
    h.render();
    const afterSwitch = h.changes.length;
    resolveOldOwner(h.jobs[0]);
    await settle();
    h.render();
    assert.ok(h.changes.slice(afterSwitch).every((v) => v === undefined));
  } finally {
    h.dispose();
  }
});

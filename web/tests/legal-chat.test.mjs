import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function chatHarness(initialProps, overrides = {}) {
  let slots = [],
    cursor = 0,
    pending = [],
    key,
    owner = "alice";
  const calls = { list: [], ask: [], errors: [] };
  const jsx = (type, props, key) => ({ type, props, key });
  const ui = new Proxy({}, { get: (_, name) => String(name) });
  const savedScope = {
    projectId: null,
    caseId: "case-a",
    officeProjectId: null,
    selectedDocumentIds: ["doc-a"],
  };
  const deps = {
    "react/jsx-runtime": { jsx, jsxs: jsx },
    react: {
      useCallback: (callback, dependencies) => {
        const index = cursor++,
          previous = slots[index];
        if (
          !previous ||
          dependencies.some((value, i) => !Object.is(value, previous.dependencies[i]))
        ) {
          slots[index] = { callback, dependencies };
        }
        return slots[index].callback;
      },
      useState: (initial) => {
        const index = cursor++,
          values = slots;
        if (!(index in values)) values[index] = typeof initial === "function" ? initial() : initial;
        return [
          values[index],
          (value) => {
            values[index] = typeof value === "function" ? value(values[index]) : value;
          },
        ];
      },
      useRef: (initial) => {
        const index = cursor++;
        return (slots[index] ??= { current: initial });
      },
      useEffect: (effect, dependencies) => {
        const index = cursor++,
          previous = slots[index];
        if (
          !previous ||
          dependencies.some((value, i) => !Object.is(value, previous.dependencies[i]))
        ) {
          const entry = (slots[index] = { dependencies, cleanup: previous?.cleanup });
          pending.push(() => {
            entry.cleanup?.();
            entry.cleanup = effect();
          });
        }
      },
    },
    "@/components/AuthProvider": { useAuth: () => ({ user: owner ? { id: owner } : null }) },
    "@/lib/router-compat": { Link: "Link", useSearchParam: () => "" },
    "@/lib/utils": { cn: (...values) => values.join(" ") },
    "@/lib/search-summary": { shouldAutoResearch: () => false },
    "@/lib/consulted-sources": { parseConsultedSources: () => [] },
    "react-markdown": { __esModule: true, default: "Markdown" },
    "remark-gfm": { __esModule: true, default: () => {} },
    sonner: { toast: { error: (message) => calls.errors.push(message) } },
    "@/lib/ai-api": {
      STAGE_LABELS: {},
      listConversations: async (scope) => {
        calls.list.push(scope);
        return [{ id: "saved", title: "Kayıtlı sohbet" }];
      },
      getConversationDetail:
        overrides.getConversationDetail ??
        (async () => ({ scope: savedScope, messages: [{ role: "user", content: "ESKİ_SORU" }] })),
      deleteConversation: async () => {},
      askAssistant: async (...args) => {
        calls.ask.push(args);
        return {
          answer: "Doğrulanmış cevap",
          conversation_id: "saved",
          citations: [],
          grounded: true,
        };
      },
    },
  };
  const source = readFileSync(new URL("../src/components/LegalChat.tsx", import.meta.url), "utf8");
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
  function unmount() {
    for (const slot of slots) slot?.cleanup?.();
  }
  function render(props = initialProps) {
    const outer = module.exports.LegalChat({
      title: "Sohbet",
      examples: [],
      intro: "Açıklama",
      ...props,
    });
    if (key !== outer.key) {
      unmount();
      slots = [];
      key = outer.key;
    }
    cursor = 0;
    pending = [];
    const tree = outer.type(outer.props);
    for (const effect of pending) effect();
    return tree;
  }
  return {
    render,
    calls,
    unmount,
    setOwner: (value) => {
      owner = value;
    },
  };
}

function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  if (!tree || typeof tree !== "object") return [];
  return [tree, ...nodes(tree.props?.children)];
}
const settle = () => new Promise((resolve) => setImmediate(resolve));
function typeQuestion(view, text = "Peki ödeme tutarı nedir?") {
  nodes(view.render())
    .find((node) => node.type === "Textarea")
    .props.onChange({ target: { value: text } });
}
function submit(view) {
  return nodes(view.render())
    .find((node) => node.type === "Button" && node.props.size === "lg")
    .props.onClick();
}

test("compact case chat lists, reopens and continues with the persisted case and document selection", async () => {
  const view = chatHarness({ compact: true, caseId: "case-a" });
  view.render();
  await settle();
  assert.equal(view.calls.list[0].caseId, "case-a");
  const select = nodes(view.render()).find((node) => node.type === "select");
  select.props.onChange({ target: { value: "saved" } });
  await settle();
  assert.ok(
    nodes(view.render()).some(
      (node) => node.type === "Markdown" && node.props.children === "ESKİ_SORU",
    ),
  );
  typeQuestion(view);
  await submit(view);
  assert.equal(view.calls.ask[0][1].conversationId, "saved");
  assert.equal(view.calls.ask[0][1].caseId, "case-a");
  assert.deepEqual(view.calls.ask[0][1].selectedDocumentIds, ["doc-a"]);
  assert.deepEqual(view.calls.errors, []);
});

test("office project chat uses its own identity rather than a core project id or direct case", async () => {
  const view = chatHarness({ compact: true, officeProjectId: "project-a" });
  view.render();
  await settle();
  assert.equal(view.calls.list[0].officeProjectId, "project-a");
  typeQuestion(view, "İlgili mevzuatı araştır.");
  await submit(view);
  assert.equal(view.calls.ask[0][1].officeProjectId, "project-a");
  assert.equal(view.calls.ask[0][1].projectId, null);
  assert.equal(view.calls.ask[0][1].caseId, null);
});

test("opening a saved chat in another fixed case does not change the outgoing scope", async () => {
  const view = chatHarness({ compact: true, caseId: "case-b" });
  view.render();
  await settle();
  nodes(view.render())
    .find((node) => node.type === "select")
    .props.onChange({ target: { value: "saved" } });
  await settle();
  assert.match(view.calls.errors[0], /farklı bir dosyaya/);
  assert.ok(
    !nodes(view.render()).some(
      (node) => node.type === "Markdown" && node.props.children === "ESKİ_SORU",
    ),
  );
  typeQuestion(view);
  await submit(view);
  assert.equal(view.calls.ask[0][1].caseId, "case-b");
  assert.equal(view.calls.ask[0][1].conversationId, null);
});

test("account change clears an already opened private history immediately", async () => {
  const view = chatHarness({ compact: true, caseId: "case-a" });
  view.render();
  await settle();
  nodes(view.render())
    .find((node) => node.type === "select")
    .props.onChange({ target: { value: "saved" } });
  await settle();
  assert.ok(nodes(view.render()).some((node) => node.type === "Markdown"));
  view.setOwner("bob");
  assert.ok(!nodes(view.render()).some((node) => node.type === "Markdown"));
});

test("late history response after account change cannot repopulate the new account", async () => {
  let finish;
  const response = new Promise((resolve) => {
    finish = resolve;
  });
  const view = chatHarness(
    { compact: true, caseId: "case-a" },
    { getConversationDetail: () => response },
  );
  view.render();
  await settle();
  nodes(view.render())
    .find((node) => node.type === "select")
    .props.onChange({ target: { value: "saved" } });
  view.setOwner("bob");
  view.render();
  finish({ scope: { caseId: "case-a" }, messages: [{ role: "user", content: "GİZLİ_ESKİ" }] });
  await settle();
  assert.ok(!nodes(view.render()).some((node) => node.type === "Markdown"));
  assert.deepEqual(view.calls.errors, []);
});

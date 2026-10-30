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
    "@/components/AuthContext": { useAuth: () => ({ user: owner ? { id: owner } : null }) },
    "@/lib/router-compat": { Link: "Link", useSearchParam: () => "" },
    "@/lib/router-hooks": { useSearchParam: () => "" },
    "@/lib/utils": { cn: (...values) => values.join(" ") },
    "@/lib/search-summary": { shouldAutoResearch: () => false },
    "@/lib/consulted-sources": { parseConsultedSources: () => [] },
    "react-markdown": { __esModule: true, default: "Markdown" },
    "remark-gfm": { __esModule: true, default: () => {} },
    sonner: { toast: { error: (message) => calls.errors.push(message) } },
    "@/lib/ai-api": {
      STAGE_LABELS: {},
      listConversations:
        overrides.listConversations ??
        (async (scope) => {
          calls.list.push(scope);
          return [{ id: "saved", title: "Kayıtlı sohbet" }];
        }),
      getConversationDetail:
        overrides.getConversationDetail ??
        (async () => ({ scope: savedScope, messages: [{ role: "user", content: "ESKİ_SORU" }] })),
      deleteConversation: async () => {},
      askAssistant:
        overrides.askAssistant ??
        (async (...args) => {
          calls.ask.push(args);
          return {
            answer: "Doğrulanmış cevap",
            conversation_id: "saved",
            citations: [],
            grounded: true,
          };
        }),
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

test("public chat sends the selected reasoning level", async () => {
  const view = chatHarness({});
  view.render();
  await settle();
  const selector = nodes(view.render()).find((node) => node.props?.id === "chat-reasoning-effort");
  assert.equal(selector.props.value, "low");
  selector.props.onChange({ target: { value: "high" } });
  typeQuestion(view, "Hukuki soru");
  await submit(view);
  assert.equal(view.calls.ask[0][1].reasoningEffort, "high");
});

test("private chat hides cloud reasoning selector and does not send an override", async () => {
  const view = chatHarness({ caseId: "case-a" });
  view.render();
  await settle();
  assert.equal(
    nodes(view.render()).some((node) => node.props?.id === "chat-reasoning-effort"),
    false,
  );
  typeQuestion(view);
  await submit(view);
  assert.equal(view.calls.ask[0][1].reasoningEffort, undefined);
});

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

test("normal chat has no stray zero or automatic source panel in the question bubble", async () => {
  const view = chatHarness({});
  view.render();
  await settle();
  typeQuestion(view, "18 bin kira alıyorum, en fazla ne kadar artış yapabilirim?");
  await submit(view);
  const tree = view.render();
  const all = nodes(tree);
  assert.ok(!all.some((node) => node.props?.["data-testid"] === "answer-details"));
  assert.ok(!all.some((node) => node.type === "ResearchSources" && node.props.autoLoad));
  assert.equal(all.filter((node) => node.type === "ResearchSources").length, 0);
  assert.ok(
    !all.some((node) => Array.isArray(node.props?.children) && node.props.children.includes(0)),
  );
});

test("the answer is visible first, while basis and diagnostics stay inside one closed sources disclosure", async () => {
  const view = chatHarness(
    {},
    {
      askAssistant: async () => ({
        answer: "KANUN_METNİ [K1]",
        summary: ["Kira hangi ay/yıl yenileniyor?"],
        citations: [{ marker: "K1", reference: "TBK 344", verification: "official" }],
        grounded: true,
        interpreted_question: "YORUMLANAN_SORU",
        search_summary: { retrieval_partial: true },
      }),
    },
  );
  view.render();
  await settle();
  typeQuestion(view);
  await submit(view);
  const all = nodes(view.render());
  const answer = all.find((node) => node.props?.["data-testid"] === "answer-summary");
  const details = all.find((node) => node.props?.["data-testid"] === "answer-details");
  assert.ok(answer && details && all.indexOf(answer) < all.indexOf(details));
  assert.ok(nodes(details).some((node) => node.props?.["data-testid"] === "answer-basis"));
  assert.ok(nodes(details).some((node) => node.type === "CitationList"));
  assert.ok(nodes(details).some((node) => node.type === "SearchSummary"));
  assert.equal(details.props.open, undefined);
  assert.ok(
    nodes(details).some((node) => node.type === "SearchSummary" && node.props.compact === true),
  );
  assert.ok(!all.some((node) => node.type === "ResearchSources"));
  // "Kaynak taraması kısmen tamamlandı" uyarısı kullanıcı kararıyla kaldırıldı (2026-10-25): ayrıntı yalnız kaynak panelinde kalır.
  assert.ok(!JSON.stringify(all.map((node) => node.props?.children)).includes("kısmen tamamlandı"));
  assert.ok(
    !all.some(
      (node) =>
        node.props?.children ===
        "Bu açıklama aşağıdaki resmî metne dayanılarak yapay zekâ tarafından yazıldı",
    ),
  );
});

for (const answerKind of [
  "conversation",
  "clarification",
  "insufficient_sources",
  "general_information",
]) {
  test(`${answerKind} replies do not show a failed-grounding warning or an empty sources menu`, async () => {
    const view = chatHarness(
      {},
      {
        askAssistant: async () => ({
          answer:
            answerKind === "conversation"
              ? "Merhaba! Nasıl yardımcı olabilirim?"
              : "Hangi ay yenileniyor?",
          answer_kind: answerKind,
          grounded: false,
          citations: [],
          unverified_markers: [],
        }),
      },
    );
    view.render();
    await settle();
    typeQuestion(view, "Merhaba");
    await submit(view);
    const all = nodes(view.render());
    assert.ok(
      all.some((node) => node.type === "Markdown" && /Merhaba!|Hangi ay/.test(node.props.children)),
    );
    assert.ok(!all.some((node) => node.type === "ShieldAlert"));
    assert.ok(!all.some((node) => node.props?.["data-testid"] === "answer-details"));
    assert.ok(!all.some((node) => node.type === "ResearchSources"));
    if (answerKind === "general_information") {
      assert.ok(all.some((node) => node.props?.["data-testid"] === "general-information-label"));
    }
  });
}

for (const answerKind of [undefined, "legal"]) {
  test(`${answerKind ?? "legacy"} unsupported legal replies retain the grounding warning`, async () => {
    const view = chatHarness(
      {},
      {
        askAssistant: async () => ({
          answer: "Bu iddia kaynaklarla doğrulanamadı.",
          answer_kind: answerKind,
          grounded: false,
          citations: [],
          unverified_markers: [],
        }),
      },
    );
    view.render();
    await settle();
    typeQuestion(view);
    await submit(view);
    assert.ok(nodes(view.render()).some((node) => node.type === "ShieldAlert"));
  });
}

test("a conversation label cannot conceal a failed real citation or unverified marker", async () => {
  const view = chatHarness(
    {},
    {
      askAssistant: async () => ({
        answer: "Yanıt [K9]",
        answer_kind: "conversation",
        grounded: false,
        citations: [{ marker: "K9", reference: "Eski kaynak", verification: "third_party" }],
        unverified_markers: ["K9"],
      }),
    },
  );
  view.render();
  await settle();
  typeQuestion(view);
  await submit(view);
  const all = nodes(view.render());
  assert.ok(all.some((node) => node.type === "ShieldAlert"));
  const details = all.find((node) => node.props?.["data-testid"] === "answer-details");
  assert.ok(details);
  assert.ok(nodes(details).some((node) => node.type === "CitationList"));
  assert.ok(
    all.some((node) => node.type === "p" && JSON.stringify(node.props.children).includes("K9")),
  );
});

test("short social messages can be sent, while whitespace cannot", async () => {
  const view = chatHarness({});
  view.render();
  await settle();
  typeQuestion(view, "   ");
  assert.equal(
    nodes(view.render()).find((node) => node.type === "Button" && node.props.size === "lg").props
      .disabled,
    true,
  );
  await submit(view);
  assert.equal(view.calls.ask.length, 0);
  typeQuestion(view, "sa");
  assert.equal(
    nodes(view.render()).find((node) => node.type === "Button" && node.props.size === "lg").props
      .disabled,
    false,
  );
  await submit(view);
  assert.equal(view.calls.ask[0][0], "sa");
});

test("persisted conversation and clarification replies remain clean after history is reopened", async () => {
  const view = chatHarness(
    { compact: true, caseId: "case-a" },
    {
      getConversationDetail: async () => ({
        scope: { caseId: "case-a" },
        messages: [
          { role: "assistant", content: "Merhaba!", answerKind: "conversation", grounded: false },
          {
            role: "assistant",
            content: "Hangi ay yenileniyor?",
            answerKind: "clarification",
            grounded: false,
          },
        ],
      }),
    },
  );
  view.render();
  await settle();
  nodes(view.render())
    .find((node) => node.type === "select")
    .props.onChange({ target: { value: "saved" } });
  await settle();
  const all = nodes(view.render());
  assert.equal(all.filter((node) => node.type === "Markdown").length, 2);
  assert.ok(!all.some((node) => node.type === "ShieldAlert"));
  assert.ok(!all.some((node) => node.props?.["data-testid"] === "answer-details"));
});

test("a long history stays inside a bounded sidebar and cannot displace the composer", async () => {
  const view = chatHarness(
    {},
    {
      listConversations: async () =>
        Array.from({ length: 50 }, (_, index) => ({
          id: `history-${index}`,
          title: `Uzun sohbet geçmişi ${index}`,
        })),
    },
  );
  view.render();
  await settle();
  const all = nodes(view.render());
  const byId = (id) => all.find((node) => node.props?.["data-testid"] === id);
  const layout = byId("chat-layout");
  const sidebar = byId("chat-history-panel");
  const history = byId("chat-history-list");
  assert.match(layout.props.className, /min-h-0/);
  assert.match(layout.props.className, /lg:grid-rows-1/);
  assert.match(layout.props.className, /280px_minmax\(0,1fr\)/);
  assert.match(sidebar.props.className, /min-h-0/);
  assert.match(sidebar.props.className, /overflow-hidden/);
  assert.match(history.props.className, /min-h-0 flex-1/);
  assert.equal(nodes(history).filter((node) => node.type === "MessageSquare").length, 50);
  assert.match(byId("chat-main").props.className, /min-h-0 min-w-0/);
  assert.match(byId("chat-messages").props.className, /min-h-0 flex-1 overflow-y-auto/);
  const composer = byId("chat-composer");
  assert.match(composer.props.className, /shrink-0/);
  assert.ok(nodes(composer).some((node) => node.type === "Textarea"));
  assert.ok(!nodes(history).includes(composer));
});

test("narrow layouts bound history separately and use dynamic viewport height", () => {
  const all = nodes(chatHarness({}).render());
  const layout = all.find((node) => node.props?.["data-testid"] === "chat-layout");
  const sidebar = all.find((node) => node.props?.["data-testid"] === "chat-history-panel");
  assert.match(layout.props.className, /grid-rows-\[auto_minmax\(0,1fr\)\]/);
  assert.match(layout.props.className, /100dvh-220px/);
  assert.match(sidebar.props.className, /max-h-40 lg:max-h-none/);
  const compact = nodes(chatHarness({ compact: true }).render());
  assert.ok(!compact.some((node) => node.props?.["data-testid"] === "chat-history-panel"));
  assert.match(
    compact.find((node) => node.props?.["data-testid"] === "chat-layout").props.className,
    /grid-rows-1 h-\[600px\]/,
  );
});

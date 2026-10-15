import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";
import { componentView, nodes, settle } from "./helpers/react-harness.mjs";

function compile(relative) {
  const code = ts.transpileModule(readFileSync(new URL(relative, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  new Function("module", "exports", code)(module, module.exports);
  return module.exports;
}
const links = compile("../src/lib/source-reader.ts");
const labels = compile("../src/lib/source-label.ts");
const id = "12345678-1234-1234-1234-123456789abc";
const other = "22345678-1234-1234-1234-123456789abc";
const url = "https://karararama.yargitay.gov.tr/getDokuman?id=1219103100";
const props = { sourceId: id, reference: "Test kararı", sourceUrl: url, excerpt: "Kısa alıntı" };
const detail = {
  title: "Karar başlığı",
  rawText: "İlk paragraf.\n\nSon paragraf.",
  chunks: [],
  sourceUrl: url,
  verification: "third_party",
  isCurrent: true,
};
function reader(load, initial = props) {
  const calls = [];
  const view = componentView(
    new URL("../src/components/SourceReader.tsx", import.meta.url),
    "SourceReader",
    initial,
    {
      "@/lib/decision-search": {
        loadSourceDetail: (...args) => {
          calls.push(args);
          return load(...args);
        },
      },
      "@/lib/source-reader": links,
      "@/lib/source-label": labels,
    },
  );
  return { ...view, calls };
}
const byTestId = (tree, name) => nodes(tree).find((node) => node.props?.["data-testid"] === name);
const textOf = (tree) =>
  nodes(tree)
    .flatMap((node) => [node.props?.children].flat(Infinity))
    .filter((value) => typeof value === "string")
    .join(" ");

test("opening a source fetches only the internal corpus endpoint, preserves full paragraphs and never promotes trust", async () => {
  const view = reader(async () => detail);
  let tree = view.render();
  assert.equal(view.calls.length, 0);
  assert.equal(byTestId(tree, "source-reader-trigger").props.href, undefined);
  byTestId(tree, "source-reader-trigger").props.onClick();
  tree = view.render();
  assert.equal(view.calls[0][0], id);
  await settle();
  tree = view.render();
  assert.equal(byTestId(tree, "source-reader-text").props.children, detail.rawText);
  assert.equal(byTestId(tree, "reader-verification"), undefined);
  assert.equal(byTestId(tree, "source-reader-external").props.href, url);
  assert.match(textOf(tree), /ham XML\/HTML/);
  view.unmount();
});

test("source close aborts loading and late responses never replace the current source", async () => {
  let resolveOld;
  const view = reader((source) =>
    source === id
      ? new Promise((resolve) => {
          resolveOld = resolve;
        })
      : Promise.resolve({ ...detail, rawText: "Yeni kaynak" }),
  );
  byTestId(view.render(), "source-reader-trigger").props.onClick();
  view.render();
  const oldSignal = view.calls[0][1];
  let tree = view.render({ ...props, sourceId: other });
  assert.equal(oldSignal.aborted, true);
  byTestId(tree, "source-reader-trigger").props.onClick();
  view.render({ ...props, sourceId: other });
  await settle();
  resolveOld({ ...detail, rawText: "Eski kaynak" });
  await settle();
  tree = view.render({ ...props, sourceId: other });
  assert.equal(byTestId(tree, "source-reader-text").props.children, "Yeni kaynak");
  nodes(tree)
    .find((node) => node.type === "Dialog")
    .props.onOpenChange(false);
  view.render({ ...props, sourceId: other });
  assert.equal(view.calls[1][1].aborted, true);
  view.unmount();
});

test("missing source ids show only the labelled excerpt, never fetch a stored URL", () => {
  for (const sourceId of [null, "", "../private", url]) {
    const view = reader(
      async () => {
        throw new Error("must not fetch");
      },
      { ...props, sourceId },
    );
    byTestId(view.render(), "source-reader-trigger").props.onClick();
    const tree = view.render();
    assert.equal(view.calls.length, 0);
    assert.match(textOf(tree), /kayıt kimliği/);
    assert.match(textOf(tree), /tam metin değil/);
    view.unmount();
  }
});

test("failure remains an error with retry, not an empty full text", async () => {
  let attempts = 0;
  const view = reader(async () => {
    if (++attempts === 1) throw new Error("Kaynak bulunamadı.");
    return detail;
  });
  byTestId(view.render(), "source-reader-trigger").props.onClick();
  view.render();
  await settle();
  let tree = view.render();
  assert.match(textOf(tree), /Kaynak bulunamadı/);
  assert.equal(byTestId(tree, "source-reader-text"), undefined);
  nodes(tree)
    .find((node) => node.type === "Button" && node.props.children === "Yeniden dene")
    .props.onClick();
  view.render();
  await settle();
  tree = view.render();
  assert.equal(attempts, 2);
  assert.equal(byTestId(tree, "source-reader-text").props.children, detail.rawText);
  view.unmount();
});

test("chunk-only, absent and historical records are explicitly distinguished", async () => {
  for (const record of [
    { ...detail, rawText: "", chunks: ["Parça"] },
    { ...detail, rawText: "", chunks: [] },
    { ...detail, isCurrent: false, verification: "official" },
  ]) {
    const view = reader(async () => record);
    byTestId(view.render(), "source-reader-trigger").props.onClick();
    view.render();
    await settle();
    const tree = view.render();
    if (record.isCurrent === false) {
      assert.match(textOf(tree), /tarihsel/);
      assert.equal(byTestId(tree, "reader-verification").props.children, "Resmî metin ✓");
    } else
      assert.match(
        textOf(tree),
        record.chunks.length ? /tam metin olduğu doğrulanmadı/ : /okunabilir metin bulunamadı/,
      );
    view.unmount();
  }
});

test("untrusted source text remains text, never HTML execution", async () => {
  const attack = '<script>alert(1)</script><img src=x onerror="alert(1)">';
  const view = reader(async () => ({ ...detail, rawText: attack }));
  byTestId(view.render(), "source-reader-trigger").props.onClick();
  view.render();
  await settle();
  const tree = view.render();
  assert.equal(byTestId(tree, "source-reader-text").props.children, attack);
  assert.ok(nodes(tree).every((node) => !node.props?.dangerouslySetInnerHTML));
  view.unmount();
});

test("source URLs reject executable schemes, credentials and fake official hosts", () => {
  for (const value of [
    "javascript:alert(1)",
    "data:text/html,hello",
    "https://user:pass@example.com",
    "file:///test",
    "/relative",
    "https://example.com\n/",
    null,
  ])
    assert.equal(links.safeSourceUrl(value), null);
  assert.equal(links.safeSourceUrl(url), url);
  assert.equal(links.sourceSiteLabel(url), "Resmî sitede aç ↗");
  assert.equal(
    links.sourceSiteLabel("https://karararama.yargitay.gov.tr.evil.test/"),
    "Kaynak sitesinde aç ↗",
  );
  assert.equal(links.isRawPortalUrl(url), true);
  assert.equal(links.isSourceId(id), true);
});

test("a stalled request becomes a Turkish retryable timeout and late data is ignored", async () => {
  const original = globalThis.setTimeout;
  let timeout, resolve;
  globalThis.setTimeout = (callback) => {
    timeout = callback;
    return 0;
  };
  const view = reader(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  try {
    byTestId(view.render(), "source-reader-trigger").props.onClick();
    view.render();
    timeout();
    let tree = view.render();
    assert.match(textOf(tree), /zamanında alınamadı/);
    assert.equal(view.calls[0][1].aborted, true);
    resolve(detail);
    await settle();
    tree = view.render();
    assert.equal(byTestId(tree, "source-reader-text"), undefined);
  } finally {
    view.unmount();
    globalThis.setTimeout = original;
  }
});

test("chat citations forward source identity to the reader and private documents stay outside the public reader", () => {
  const groups = compile("../src/lib/citation-groups.ts");
  const view = componentView(
    new URL("../src/components/ChatCitations.tsx", import.meta.url),
    "CitationList",
    {
      citations: [
        {
          marker: "K1",
          source_id: id,
          source_type: "court_decision",
          reference: "Karar",
          source_url: url,
          verification: "official",
        },
        {
          marker: "K2",
          source_id: other,
          source_type: "document",
          reference: "Özel belge",
          source_url: null,
          verification: "user_document",
        },
      ],
    },
    {
      "@/lib/citation-groups": groups,
      "@/lib/source-label": labels,
      "@/lib/document-scope": { USER_DOCUMENT_NOTE: "Kullanıcı belgesi" },
    },
  );
  const readers = nodes(view.render()).filter((node) => node.type === "SourceReader");
  assert.equal(readers.length, 1);
  assert.equal(readers[0].props.sourceId, id);
  view.unmount();
});

test("consulted sources preserve source identity while private documents never open the public reader", () => {
  const view = componentView(
    new URL("../src/components/ChatCitations.tsx", import.meta.url),
    "ConsultedSourceList",
    {
      sources: [
        {
          marker: "K1",
          source_id: id,
          reference: "Karar",
          source_url: url,
          verification: "official",
          excerpt: "Pasaj",
        },
        {
          marker: "K2",
          source_id: other,
          source_type: "document",
          reference: "Özel belge",
          verification: "user_document",
        },
      ],
    },
    {
      "@/lib/citation-groups": compile("../src/lib/citation-groups.ts"),
      "@/lib/source-label": labels,
      "@/lib/document-scope": { USER_DOCUMENT_NOTE: "Kullanıcı belgesi" },
    },
  );
  const readers = nodes(view.render()).filter((node) => node.type === "SourceReader");
  assert.equal(readers.length, 1);
  assert.equal(readers[0].props.sourceId, id);
  assert.equal(readers[0].props.excerpt, "Pasaj");
  view.unmount();
});

test("deep research forwards structured citations to the same reader list, not direct external links", () => {
  const citations = [
    {
      marker: "K1",
      sourceId: id,
      reference: "Karar",
      sourceUrl: url,
      verification: "third_party",
      sourceType: "court_decision",
      excerpt: "Pasaj",
    },
    {
      marker: "K2",
      sourceId: other,
      reference: "Özel belge",
      sourceUrl: null,
      verification: "user_document",
      sourceType: "document",
    },
  ];
  const view = componentView(
    new URL("../src/components/DeepResearch.tsx", import.meta.url),
    "StepCard",
    { step: { title: "Kararlar", answer: "Cevap", grounded: true, citations }, index: 1 },
    {
      "react-markdown": { __esModule: true, default: "Markdown" },
      sonner: { toast: {} },
      "@/lib/auth-api": {},
      "@/lib/deep-research": {},
    },
  );
  const tree = view.render();
  const forwarded = nodes(tree).find((node) => node.type === "CitationList").props.citations;
  assert.equal(forwarded[0].source_id, id);
  assert.equal(forwarded[0].excerpt, "Pasaj");
  assert.equal(forwarded[0].verification, "third_party");
  assert.equal(forwarded[1].source_type, "document");
  assert.equal(nodes(tree).filter((node) => node.type === "a").length, 0);
  view.unmount();
});

test("home chat keeps citation identities instead of flattening them into the answer", async () => {
  const citations = [
    {
      marker: "K1",
      source_id: id,
      reference: "Karar",
      source_url: url,
      verification: "official",
      excerpt: "Pasaj",
    },
  ];
  const view = componentView(
    new URL("../src/routes/index.tsx", import.meta.url),
    "Route",
    {},
    {
      "@tanstack/react-router": { createFileRoute: () => (options) => options.component },
      "@/lib/source-label": labels,
      "@/lib/utils": { cn: (...args) => args.join(" ") },
      "@/lib/extract-text": {},
      "@/components/AuthProvider": { useAuth: () => ({ user: { id: "owner" }, loading: false }) },
      "@/lib/ai-api": { askAssistant: async () => ({ answer: "Cevap [K1]", citations }) },
      "react-markdown": { __esModule: true, default: "Markdown" },
      "remark-gfm": { __esModule: true, default: () => {} },
      sonner: {
        toast: {
          error: (message) => {
            throw Error(message);
          },
        },
      },
    },
  );
  let tree = view.render();
  nodes(tree)
    .find((node) => node.type === "Textarea")
    .props.onChange({ target: { value: "Hukuki bir soru" } });
  tree = view.render();
  await nodes(tree)
    .find((node) => node.type === "Textarea")
    .props.onKeyDown({ key: "Enter", shiftKey: false, preventDefault() {} });
  await settle();
  tree = view.render();
  assert.equal(nodes(tree).find((node) => node.type === "CitationList").props.citations, citations);
  assert.ok(
    nodes(tree).some((node) => node.type === "Markdown" && node.props.children === "Cevap [K1]"),
  );
  assert.ok(
    nodes(tree)
      .filter((node) => node.type === "Markdown")
      .every((node) => !node.props.children.includes("**Kaynaklar**")),
  );
  view.unmount();
});

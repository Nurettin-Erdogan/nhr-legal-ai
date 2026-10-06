import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
function compile(relative, dependencies) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8").replaceAll("import.meta.env", "({})");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(
    (id) => dependencies[id] ?? require(id), module, module.exports,
  );
  return module.exports;
}
const api = compile("../src/lib/office-api.ts", {
  "@/lib/auth-api": { inMemoryAccessToken: () => "test-token" },
  "@/lib/db": {},
  "@/lib/uyap": {},
});

test("UYAP case linking sends authenticated requests and keeps the resume cursor", async () => {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init });
    return new Response(JSON.stringify({ linked: 2, has_more: false, next_cursor: null }));
  };
  try {
    await api.linkUyapCases();
    const result = await api.linkUyapCases("cursor/with?unsafe");
    assert.equal(result.linked, 2);
    assert.equal(requests[0].url, "http://localhost:8766/api/office/uyap/link-cases");
    assert.match(requests[1].url, /after=cursor%2Fwith%3Funsafe$/);
    assert.equal(requests[0].init.headers.Authorization, "Bearer test-token");
    assert.equal(requests[0].init.credentials, "include");
    assert.equal(requests[0].init.method, "POST");
    assert.deepEqual(JSON.parse(requests[0].init.body), {}); // Owner is never client-controlled.
  } finally {
    globalThis.fetch = original;
  }
});

test("case linking never turns an HTTP or network failure into success", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: "UYAP dava bağlantıları kurulamadı" }), { status: 503 });
    await assert.rejects(api.linkUyapCases(), /UYAP dava bağlantıları kurulamadı/);
    globalThis.fetch = async () => { throw new Error("offline"); };
    await assert.rejects(api.linkUyapCases(), /Sunucuya ulaşılamadı/);
  } finally {
    globalThis.fetch = original;
  }
});

test("the UYAP linking card explains matching and does not mutate on render", () => {
  const { UyapCaseLinks } = compile("../src/components/UyapCaseLinks.tsx", {
    "@/lib/office-api": { linkUyapCases: () => { throw new Error("Must require a user click"); } },
    "@/components/ui/button": { Button: ({ children, variant, ...props }) => createElement("button", props, children) },
    "@/lib/router-compat": { Link: ({ to, children }) => createElement("a", { href: to }, children) },
  });
  const markup = renderToStaticMarkup(createElement(UyapCaseLinks));
  assert.match(markup, /dosya numarası ve UYAP birimi birlikte/);
  assert.match(markup, /müvekkil ve dosya durumu tahmin edilmez/);
  assert.match(markup, /Elle kurduğunuz bağlantılar değişmez/);
  assert.match(markup, /Mevcut UYAP belgelerini davalara bağla/);
  assert.match(markup, /href="\/dashboard\/cases"/);
});

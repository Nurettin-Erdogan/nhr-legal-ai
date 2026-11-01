import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
const source = readFileSync(
  new URL("../src/components/ContentMatchExcerpt.tsx", import.meta.url),
  "utf8",
);
const { outputText } = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
    jsx: ts.JsxEmit.ReactJSX,
  },
});
const module = { exports: {} };
new Function("require", "module", "exports", outputText)(require, module, module.exports);
const { ContentMatchExcerpt } = module.exports;
const render = (match) => renderToStaticMarkup(React.createElement(ContentMatchExcerpt, { match }));

test("document content is escaped, the exact match is highlighted and the real page is shown", () => {
  const html = render({
    before: '<script>alert("x")</script>',
    match: "İCRA EMRİ",
    after: " <img src=x onerror=alert(1)>",
    page_number: 12,
    section_title: "Sonuç",
  });
  assert.ok(!html.includes("<script>") && !html.includes("<img"));
  assert.ok(html.includes("&lt;script&gt;"));
  assert.match(html, /<mark[^>]*>İCRA EMRİ<\/mark>/);
  assert.ok(html.includes("Sayfa 12") && html.includes("Sonuç"));
});

test("unknown page is disclosed rather than invented; absent match renders nothing", () => {
  assert.ok(
    render({
      before: "",
      match: "ödeme",
      after: "",
      page_number: null,
      section_title: null,
    }).includes("Sayfa numarası kaynak metinde yok"),
  );
  assert.equal(render(null), "");
  assert.equal(render(undefined), "");
});

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
function compile(relative) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(require, module, module.exports);
  return module.exports;
}

test("extracted auth hook reads the provider's actual shared context", () => {
  const { Ctx, useAuth } = compile("../src/components/AuthContext.ts");
  function Consumer() {
    return createElement("span", null, useAuth().user.id);
  }
  const html = renderToStaticMarkup(
    createElement(
      Ctx.Provider,
      { value: { user: { id: "synthetic-owner" } } },
      createElement(Consumer),
    ),
  );
  assert.equal(html, "<span>synthetic-owner</span>");
  assert.throws(() => renderToStaticMarkup(createElement(Consumer)), /inside AuthProvider/);
});

test("extracted theme hook reads its provider and rejects a missing provider", () => {
  const { ThemeContext, useTheme } = compile("../src/components/ThemeContext.ts");
  function Consumer() {
    return createElement("span", null, useTheme().theme);
  }
  assert.equal(
    renderToStaticMarkup(
      createElement(ThemeContext.Provider, { value: { theme: "dark" } }, createElement(Consumer)),
    ),
    "<span>dark</span>",
  );
  assert.throws(() => renderToStaticMarkup(createElement(Consumer)), /within ThemeProvider/);
});

test("extracted sidebar hook reads its provider and rejects a missing provider", () => {
  const { SidebarContext, useSidebar } = compile("../src/components/ui/sidebar-context.ts");
  function Consumer() {
    return createElement("span", null, useSidebar().state);
  }
  assert.equal(
    renderToStaticMarkup(
      createElement(
        SidebarContext.Provider,
        { value: { state: "expanded" } },
        createElement(Consumer),
      ),
    ),
    "<span>expanded</span>",
  );
  assert.throws(() => renderToStaticMarkup(createElement(Consumer)), /within a SidebarProvider/);
});

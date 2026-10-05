import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";

const require = createRequire(import.meta.url);
function compile(relative) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(require, module, module.exports);
  return module.exports;
}

const nav = compile("../src/lib/nav.ts");
const routesDir = new URL("../src/routes/_authenticated/", import.meta.url);

const INDEX_ROUTES = new Set(["/dashboard", "/dashboard/cases"]); // dashboard.index.tsx, dashboard.cases.index.tsx
const routeFile = (to) => (to === "/dashboard" ? "dashboard.index.tsx" : INDEX_ROUTES.has(to) ? `dashboard.${to.replace("/dashboard/", "")}.index.tsx` : `dashboard.${to.replace("/dashboard/", "")}.tsx`);

test("every menu entry points at a real page and no page is listed twice", () => {
  const targets = nav.NAV_ITEMS.map((item) => item.to);
  assert.equal(new Set(targets).size, targets.length, "yinelenen menü girdisi");
  for (const to of targets) assert.ok(existsSync(new URL(routeFile(to), routesDir)), `${to} için rota dosyası yok`);
  assert.equal(new Set(nav.NAV_ITEMS.map((item) => item.label)).size, nav.NAV_ITEMS.length, "yinelenen menü adı");
});

test("the working pages are reachable from the menu and unfinished ones are not listed", () => {
  const listed = new Set(nav.NAV_ITEMS.map((item) => item.to));
  for (const must of ["clients", "tasks", "calendar", "reminders", "document-analysis", "risk-analysis", "auto-summary", "semantic-search", "agent-research", "legislation"]) {
    assert.ok(listed.has(`/dashboard/${must}`), `${must} menüde yok`);
  }
  // "henüz bağlı değil" sayfalar çalışıyormuş izlenimi vermesin
  for (const stub of ["execution", "leads", "reports", "staff", "payments", "calls", "call-center", "modules"]) {
    assert.ok(!listed.has(`/dashboard/${stub}`), `${stub} menüde olmamalı`);
  }
  // Menüde olmayan her dashboard sayfası ya bilinçli olarak dışarıda ya da yönlendirme/alt sayfadır
  const known = new Set(["index", "route", "appointments", "research", "projects.index", "projects.$id", "cases.index", "cases.$id", "execution", "leads", "reports", "staff", "payments", "calls", "call-center", "modules"]);
  const unlisted = readdirSync(routesDir)
    .map((file) => file.replace(/^dashboard\./, "").replace(/\.tsx$/, ""))
    .filter((name) => !listed.has(`/dashboard/${name}`) && !known.has(name));
  assert.deepEqual(unlisted, [], `menüye bağlanmamış sayfa: ${unlisted.join(", ")}`);
});

test("collapsed headings survive bad storage and never hide the page the user is on", () => {
  assert.deepEqual(nav.parseCollapsedGroups(null), []);
  assert.deepEqual(nav.parseCollapsedGroups("{bozuk"), []);
  assert.deepEqual(nav.parseCollapsedGroups('{"Büro":true}'), []);
  assert.deepEqual(nav.parseCollapsedGroups('["Büro","Büro","Silinmiş başlık",7]'), ["Büro"]);

  assert.deepEqual(nav.toggleCollapsedGroup([], "Büro"), ["Büro"]);
  assert.deepEqual(nav.toggleCollapsedGroup(["Büro", "Hesap"], "Büro"), ["Hesap"]);

  const buro = nav.NAV_GROUPS[0];
  assert.equal(nav.visibleNavItems(buro, false, "/dashboard/cases").length, buro.items.length);
  assert.deepEqual(nav.visibleNavItems(buro, true, "/dashboard/cases").map((item) => item.to), ["/dashboard/cases"]);
  assert.deepEqual(nav.visibleNavItems(buro, true, "/dashboard/ai"), []);
});

test("the active entry is the longest matching path so similar names do not collide", () => {
  const active = (path) => nav.activeNavPath(path);
  assert.equal(active("/dashboard"), "/dashboard");
  assert.equal(active("/dashboard/"), "/dashboard");
  assert.equal(active("/dashboard/cases"), "/dashboard/cases");
  assert.equal(active("/dashboard/cases/2f1e"), "/dashboard/cases");
  assert.equal(active("/dashboard/case-law"), "/dashboard/case-law");
  assert.equal(active("/dashboard/semantic-search"), "/dashboard/semantic-search");
  assert.equal(active("/dashboard/legislation"), "/dashboard/legislation");
  assert.equal(active("/dashboard/projects/5"), null); // menüde olmayan alt sayfa: hiçbir girdi yanlış vurgulanmaz
  assert.equal(active("/dashboard/calendarx"), null);
});

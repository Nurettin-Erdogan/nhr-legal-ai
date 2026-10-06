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
  for (const must of ["clients", "tasks", "calendar", "reminders", "document-analysis", "risk-analysis", "auto-summary", "case-law", "document-processing", "agent-research", "legislation"]) {
    assert.ok(listed.has(`/dashboard/${must}`), `${must} menüde yok`);
  }
  // "henüz bağlı değil" sayfalar çalışıyormuş izlenimi vermesin
  for (const stub of ["execution", "leads", "reports", "staff", "payments", "calls", "call-center", "modules"]) {
    assert.ok(!listed.has(`/dashboard/${stub}`), `${stub} menüde olmamalı`);
  }
  // Menüde olmayan her dashboard sayfası ya bilinçli olarak dışarıda ya da yönlendirme/alt sayfadır
  const known = new Set(["index", "route", "appointments", "research", "semantic-search", "automation", "projects.index", "projects.$id", "cases.index", "cases.$id", "execution", "leads", "reports", "staff", "payments", "calls", "call-center", "modules"]);
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
  assert.deepEqual(nav.visibleNavItems(buro, true, "/dashboard/cases"), buro.items);
  assert.deepEqual(nav.visibleNavItems(buro, true, "/dashboard/ai"), []);
});

test("the whole active section stays expanded for every page and nested route", () => {
  for (const group of nav.NAV_GROUPS) {
    for (const item of group.items) {
      for (const pathname of [item.to, `${item.to}/detail`]) {
        const activePath = nav.activeNavPath(pathname);
        if (activePath !== item.to) continue; // Ana Sayfa yalnız tam eşleşir.
        assert.equal(nav.isNavGroupCollapsed(group, true, activePath), false);
        assert.deepEqual(nav.visibleNavItems(group, true, activePath), group.items);
        for (const other of nav.NAV_GROUPS.filter((entry) => entry !== group)) {
          assert.equal(nav.isNavGroupCollapsed(other, true, activePath), true);
          assert.deepEqual(nav.visibleNavItems(other, true, activePath), []);
        }
      }
    }
    assert.equal(nav.isNavGroupCollapsed(group, false, null), false);
    assert.equal(nav.isNavGroupCollapsed(group, true, null), true);
  }
});

test("the active entry is the longest matching path so similar names do not collide", () => {
  const active = (path) => nav.activeNavPath(path);
  assert.equal(active("/dashboard"), "/dashboard");
  assert.equal(active("/dashboard/"), "/dashboard");
  assert.equal(active("/dashboard/cases"), "/dashboard/cases");
  assert.equal(active("/dashboard/cases/2f1e"), "/dashboard/cases");
  assert.equal(active("/dashboard/case-law"), "/dashboard/case-law");
  assert.equal(active("/dashboard/document-processing"), "/dashboard/document-processing");
  assert.equal(active("/dashboard/semantic-search"), null); // İçtihat sayfasına yönlendiren eski adres menüde yok
  assert.equal(active("/dashboard/legislation"), "/dashboard/legislation");
  assert.equal(active("/dashboard/projects/5"), null); // menüde olmayan alt sayfa: hiçbir girdi yanlış vurgulanmaz
  assert.equal(active("/dashboard/calendarx"), null);
});

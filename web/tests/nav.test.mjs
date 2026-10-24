import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
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

const nav = compile("../src/lib/nav.ts");
const routesDir = new URL("../src/routes/_authenticated/", import.meta.url);

const INDEX_ROUTES = new Set(["/dashboard", "/dashboard/cases"]); // dashboard.index.tsx, dashboard.cases.index.tsx
const routeFile = (to) =>
  to === "/dashboard"
    ? "dashboard.index.tsx"
    : INDEX_ROUTES.has(to)
      ? `dashboard.${to.replace("/dashboard/", "")}.index.tsx`
      : `dashboard.${to.replace("/dashboard/", "")}.tsx`;

test("every menu entry points at a real page and no page is listed twice", () => {
  const targets = nav.NAV_ITEMS.map((item) => item.to);
  assert.equal(new Set(targets).size, targets.length, "yinelenen menü girdisi");
  for (const to of targets)
    assert.ok(existsSync(new URL(routeFile(to), routesDir)), `${to} için rota dosyası yok`);
  assert.equal(
    new Set(nav.NAV_ITEMS.map((item) => item.label)).size,
    nav.NAV_ITEMS.length,
    "yinelenen menü adı",
  );
});

test("the working pages are reachable from the menu and unfinished ones are not listed", () => {
  const listed = new Set(nav.NAV_ITEMS.map((item) => item.to));
  assert.equal(nav.NAV_GROUPS.flatMap((group) => group.items).length, 11);
  // Yönetim yalnız yöneticiye ayrı bağlantıyla gösterilir; avukatın menü listesinde yer almaz.
  assert.ok(!listed.has(nav.ADMIN_NAV.to), "Yönetim herkesin menüsünde olmamalı");
  const reachable = new Set([...listed, ...Object.keys(nav.NAV_PARENTS), nav.ADMIN_NAV.to]);
  for (const must of [
    "clients",
    "tasks",
    "calendar",
    "reminders",
    "document-analysis",
    "risk-analysis",
    "auto-summary",
    "case-law",
    "document-processing",
    "agent-research",
    "legislation",
    "execution",
    "projects",
  ]) {
    assert.ok(reachable.has(`/dashboard/${must}`), `${must} çalışma alanında yok`);
  }
  // "henüz bağlı değil" sayfalar çalışıyormuş izlenimi vermesin
  for (const stub of ["leads", "reports", "staff", "payments", "calls", "call-center", "modules"]) {
    assert.ok(!listed.has(`/dashboard/${stub}`), `${stub} menüde olmamalı`);
  }
  // Menüde olmayan her dashboard sayfası ya bilinçli olarak dışarıda ya da yönlendirme/alt sayfadır
  const known = new Set([
    "index",
    "route",
    "appointments",
    "research",
    "semantic-search",
    "automation",
    "projects.index",
    "projects.$id",
    "cases.index",
    "cases.$id",
    "leads",
    "reports",
    "staff",
    "payments",
    "calls",
    "call-center",
    "modules",
  ]);
  const unlisted = readdirSync(routesDir)
    .map((file) => file.replace(/^dashboard\./, "").replace(/\.tsx$/, ""))
    .filter((name) => !reachable.has(`/dashboard/${name}`) && !known.has(name));
  assert.deepEqual(unlisted, [], `menüye bağlanmamış sayfa: ${unlisted.join(", ")}`);
});

test("collapsed headings survive bad storage and never hide the page the user is on", () => {
  assert.deepEqual(nav.parseCollapsedGroups(null), []);
  assert.deepEqual(nav.parseCollapsedGroups("{bozuk"), []);
  assert.deepEqual(nav.parseCollapsedGroups('{"Büro":true}'), []);
  assert.deepEqual(nav.parseCollapsedGroups('["Büro","Büro","Silinmiş başlık",7]'), ["Büro"]);

  assert.deepEqual(nav.toggleCollapsedGroup([], "Büro"), ["Büro"]);
  assert.deepEqual(nav.toggleCollapsedGroup(["Büro", "Hesap"], "Büro"), ["Hesap"]);

  const buro = nav.NAV_GROUPS.find((group) => group.title === "Büro");
  const activeBuro = "/dashboard/clients";
  assert.equal(nav.visibleNavItems(buro, false, activeBuro).length, buro.items.length);
  assert.deepEqual(nav.visibleNavItems(buro, true, activeBuro), buro.items);
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
  assert.equal(active("/dashboard/document-processing"), "/dashboard/files");
  assert.equal(active("/dashboard/semantic-search"), "/dashboard/case-law");
  assert.equal(active("/dashboard/legislation"), "/dashboard/legislation");
  assert.equal(active("/dashboard/projects/5"), "/dashboard/cases");
  assert.equal(active("/dashboard/calendarx"), null);
});

test("secondary screens keep their parent selected and are accessible inside that workspace", () => {
  for (const [child, parent] of Object.entries(nav.NAV_PARENTS)) {
    assert.equal(nav.activeNavPath(child), parent);
    assert.equal(nav.activeNavPath(`${child}/detail`), parent);
    assert.equal(nav.activeNavPath(`${child}x`), null);
  }
  for (const section of nav.SECTION_NAV) {
    for (const entry of section.items) {
      const target =
        entry.to === "/dashboard/projects" ? "dashboard.projects.index.tsx" : routeFile(entry.to);
      assert.ok(
        existsSync(new URL(target, routesDir)),
        `Çalışma alanı bağlantısı yok: ${entry.to}`,
      );
    }
  }
});

test("execution tracking is a standalone menu entry, not a cases tab", () => {
  const execution = "/dashboard/execution";
  const group = nav.NAV_GROUPS.find((entry) => entry.items.some((item) => item.to === execution));
  assert.ok(group);
  assert.equal(group.items.find((item) => item.to === execution).label, "İcra Takibi");
  assert.equal(nav.NAV_PARENTS[execution], undefined);
  assert.ok(
    !nav.SECTION_NAV.some((section) => section.items.some((item) => item.to === execution)),
  );
  for (const path of [execution, `${execution}/`, `${execution}/detail`]) {
    assert.equal(nav.activeNavPath(path), execution);
    assert.equal(nav.isNavGroupCollapsed(group, true, nav.activeNavPath(path)), false);
  }
  assert.equal(nav.activeNavPath("/dashboard/cases"), "/dashboard/cases");
  assert.equal(nav.activeNavPath("/dashboard/projects/5"), "/dashboard/cases");
});

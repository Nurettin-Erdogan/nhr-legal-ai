import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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

const lib = compile("../src/lib/home-summary.ts");
const NOW = new Date(2026, 9, 5, 15, 30); // 5 Ekim 2026 15:30 (yerel)

const kase = (id, next_hearing, status = "active", extra = {}) => ({ id: String(id), title: `Dava ${id}`, case_no: null, court: null, status, next_hearing, created_at: `2026-09-0${id}T10:00:00Z`, ...extra });
const task = (id, due_date, status = "todo") => ({ id: String(id), title: `Görev ${id}`, status, due_date, case_id: null });

test("days are counted on the local calendar and ignore the time of day", () => {
  assert.equal(lib.daysUntil("2026-10-05", NOW), 0);
  assert.equal(lib.daysUntil("2026-10-06T00:00:00+03:00", NOW), 1);
  assert.equal(lib.daysUntil("2026-10-05T23:59:00Z", NOW), 0);
  assert.equal(lib.daysUntil("2026-10-02", NOW), -3);
  assert.equal(lib.daysUntil(null, NOW), null);
  assert.equal(lib.daysUntil("bozuk", NOW), null);
  assert.equal(lib.daysUntil("2026-13-45", NOW), null);
});

test("relative day text is plain Turkish", () => {
  assert.deepEqual([0, 1, -1, 5, -4, null].map(lib.relativeDay), ["bugün", "yarın", "dün", "5 gün sonra", "4 gün gecikti", ""]);
});

test("upcoming hearings skip past, closed and undated cases and sort nearest first", () => {
  const list = lib.upcomingHearings(
    [kase(1, "2026-10-20"), kase(2, "2026-10-05"), kase(3, "2026-10-01"), kase(4, null), kase(5, "2026-10-06", "closed"), kase(6, "2026-10-08"), kase(7, "yok")],
    NOW,
  );
  assert.deepEqual(list.map((item) => [item.id, item.days]), [["2", 0], ["6", 3], ["1", 15]]);
  assert.equal(lib.upcomingHearings([kase(1, "2026-10-20"), kase(2, "2026-10-21")], NOW, 1).length, 1);
});

test("open tasks list overdue ones first, hide done ones and put undated tasks last", () => {
  const list = lib.openTasks([task(1, "2026-10-09"), task(2, "2026-10-01"), task(3, null), task(4, "2026-10-03", "done"), task(5, "2026-10-05")], NOW);
  assert.deepEqual(list.map((item) => item.id), ["2", "5", "1", "3"]);
  assert.equal(lib.overdueCount(list), 1);
  assert.equal(lib.overdueCount([]), 0);
});

test("recent cases are newest first and limited", () => {
  const cases = [kase(1, null), kase(3, null), kase(2, null)];
  assert.deepEqual(lib.recentCases(cases, 2).map((item) => item.id), ["3", "2"]);
  assert.deepEqual(cases.map((item) => item.id), ["1", "3", "2"]); // girdi değişmez
});

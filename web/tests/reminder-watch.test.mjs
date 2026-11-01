import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function load(relative) {
  const code = readFileSync(new URL(relative, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(code, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("module", "exports", outputText)(module, module.exports);
  return module.exports;
}
const { dueReminders, toAnnounce } = load("../src/lib/reminder-watch.ts");
const now = new Date("2026-10-06T12:00:00Z");
const item = (id, remind_at, extra = {}) => ({
  id,
  title: id,
  remind_at,
  status: "pending",
  notified_at: null,
  ...extra,
});

test("yalnız zamanı gelmiş ve hâlâ bekleyen hatırlatmalar zilde görünür, en yeni önce", () => {
  const list = [
    item("gelecek", "2026-10-06T13:00:00Z"),
    item("eski", "2026-10-05T09:00:00Z"),
    item("yeni", "2026-10-06T11:59:00Z"),
    item("bitti", "2026-10-06T10:00:00Z", { status: "done" }),
    item("iptal", "2026-10-06T10:00:00Z", { status: "cancelled" }),
    item("bozuk", "tarih değil"),
  ];
  assert.deepEqual(
    dueReminders(list, now).map((entry) => entry.id),
    ["yeni", "eski"],
  );
});

test("hatırlatma bir kez duyurulur: sunucuda işaretliyse ya da bu tarayıcıda görüldüyse yeniden duyurulmaz", () => {
  const list = [
    item("ilk", "2026-10-06T11:59:00Z"),
    item("isaretli", "2026-10-06T11:50:00Z", { notified_at: "2026-10-06T11:51:00Z" }),
    item("gorulmus", "2026-10-06T11:40:00Z"),
  ];
  assert.deepEqual(
    toAnnounce(list, now, new Set(["gorulmus"])).map((entry) => entry.id),
    ["ilk"],
  );
});

test("bir günden eski hatırlatma duyurulmaz ama zilde kalır", () => {
  const list = [item("cok-eski", "2026-10-01T09:00:00Z")];
  assert.deepEqual(toAnnounce(list, now), []);
  assert.equal(dueReminders(list, now).length, 1);
});

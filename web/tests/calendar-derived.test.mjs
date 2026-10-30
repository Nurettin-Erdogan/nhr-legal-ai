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
const { deriveCalendarEvents } = load("../src/lib/calendar-derived.ts");
const from = new Date("2026-10-01T00:00:00Z");
const to = new Date("2026-10-31T23:59:59Z");
const hearing = "2026-10-20T07:30:00.000Z";

test("davanın duruşma tarihi ve açık görevin son tarihi takvime düşer", () => {
  const events = deriveCalendarEvents(
    [
      {
        id: "c1",
        title: "Demir / Kaya Tahliye",
        court: "Ankara 5. Sulh Hukuk",
        next_hearing: hearing,
      },
    ],
    [
      {
        id: "t1",
        title: "Cevap dilekçesi",
        due_date: "2026-10-10T14:00:00.000Z",
        status: "todo",
        case_id: "c1",
      },
    ],
    from,
    to,
  );
  assert.deepEqual(
    events.map((event) => [event.id, event.event_type, event.derived, event.link]),
    [
      ["task:t1", "task", "task", "/dashboard/tasks"],
      ["case:c1", "hearing", "case", "/dashboard/cases/c1"],
    ],
  );
  assert.equal(events[1].title, "Duruşma: Demir / Kaya Tahliye");
  assert.equal(events[1].location, "Ankara 5. Sulh Hukuk");
});

test("tarihi olmayan, pencere dışındaki ya da tamamlanmış kayıtlar gösterilmez", () => {
  const events = deriveCalendarEvents(
    [
      { id: "c1", title: "Tarihsiz", next_hearing: null },
      { id: "c2", title: "Gelecek ay", next_hearing: "2026-11-20T07:30:00.000Z" },
      { id: "c3", title: "Bozuk", next_hearing: "tarih değil" },
    ],
    [
      { id: "t1", title: "Bitti", due_date: "2026-10-10T14:00:00.000Z", status: "done" },
      { id: "t2", title: "Tarihsiz", due_date: null, status: "todo" },
    ],
    from,
    to,
  );
  assert.deepEqual(events, []);
});

test("aynı davaya aynı dakikada elle açılmış duruşma etkinliği varsa türeyen girdi tekrarlanmaz", () => {
  const cases = [{ id: "c1", title: "Dava", next_hearing: hearing }];
  assert.equal(
    deriveCalendarEvents(cases, [], from, to, [
      { event_type: "hearing", case_id: "c1", start_at: "2026-10-20T07:30:40.000Z" },
    ]).length,
    0,
  );
  // Başka saatte ya da başka türde etkinlik türeyen girdiyi gizlemez.
  assert.equal(
    deriveCalendarEvents(cases, [], from, to, [
      { event_type: "hearing", case_id: "c1", start_at: "2026-10-21T07:30:00.000Z" },
    ]).length,
    1,
  );
  assert.equal(
    deriveCalendarEvents(cases, [], from, to, [
      { event_type: "meeting", case_id: "c1", start_at: hearing },
    ]).length,
    1,
  );
});

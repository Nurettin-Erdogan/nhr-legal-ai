import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";
function compile(path, requires = {}) {
  const { outputText } = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(
    (n) => requires[n],
    module,
    module.exports,
  );
  return module.exports;
}
const sync = compile("../src/lib/uyap-sync-all.ts", {
  "@/lib/uyap-bridge": {},
  "@/lib/steady-timer": {},
});
const history = compile("../src/lib/uyap-run-report.ts", { "@/lib/uyap-sync-all": sync });
const id = "ebc6463a-fcf0-46e3-8893-e94eb7434c72";
const run = () => {
  const reports = ["complete", "empty", "incomplete", "failed", "pending"].map((outcome, i) => ({
    ...sync.blankReport({
      key: `private-portal-key-${i}`,
      esas: `2026/${i}`,
      birim: "Test Dairesi",
      yargiTuru: "İcra",
    }),
    outcome,
    found: ["complete", "incomplete"].includes(outcome) ? 2 : 0,
    stored: outcome === "complete" ? 2 : outcome === "incomplete" ? 1 : 0,
    missing: outcome === "incomplete" ? 1 : 0,
    detail: {
      state: "complete",
      tabs: 1,
      saved: true,
      problems: [],
      data: { private: "DOCUMENT_BODY_SECRET" },
    },
  }));
  return { reports, summary: sync.summarize(reports), aborted: false };
};
test("full run round-trips all outcomes without portal keys or private detail tables", () => {
  const checkpoint = history.auditCheckpoint(id, 2, true, true, true, run());
  assert.doesNotMatch(JSON.stringify(checkpoint), /private-portal-key|DOCUMENT_BODY_SECRET|"data"/);
  const parsed = history.parseAuditRun({ id, revision: 2, snapshot: checkpoint });
  assert.deepEqual(
    parsed.run.reports.map((r) => r.outcome),
    ["complete", "empty", "incomplete", "failed", "pending"],
  );
  assert.equal(parsed.run.summary.files, 5);
  assert.equal(parsed.run.summary.allComplete, false);
  assert.match(sync.reportText(parsed.run), /İŞLENMEDİ/);
});
test("malformed or contradictory history fails closed, never becomes green", () => {
  const checkpoint = history.auditCheckpoint(id, 2, true, true, true, run());
  for (const change of [
    (r) => (r.revision = 0),
    (r) => (r.id = "-".repeat(36)),
    (r) => (r.finished = false),
    (r) => (r.snapshot.reports[0].stored = 1),
    (r) => (r.snapshot.reports[1].found = 3),
    (r) => (r.snapshot.reports[0].detail.tabs = -1),
  ]) {
    const row = structuredClone({ id, revision: 2, finished: true, snapshot: checkpoint });
    change(row);
    assert.equal(history.parseAuditRun(row), null);
  }
});
test("unfinished checkpoint keeps unprocessed files and cannot imply a finished run", () => {
  const checkpoint = history.auditCheckpoint(id, 1, false, true, false, run());
  const saved = history.parseAuditRun({ id, revision: 1, snapshot: checkpoint });
  assert.equal(saved.finished, false);
  assert.equal(saved.listComplete, false);
  assert.equal(saved.run.summary.pending, 1);
});

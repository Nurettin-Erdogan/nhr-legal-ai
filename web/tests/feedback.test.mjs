import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";

const require = createRequire(import.meta.url);
const inserts = [];
function load() {
  const source = readFileSync(new URL("../src/lib/feedback.ts", import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const module = { exports: {} };
  const fakeDb = { db: { from: (table) => ({ insert: async (row) => (inserts.push({ table, row }), { error: globalThis.__feedbackError ?? null }) }) } };
  new Function("require", "module", "exports", outputText)((name) => (name === "@/lib/db" ? fakeDb : require(name)), module, module.exports);
  return module.exports;
}
const lib = load();

test("a message is sendable only within the length limits", () => {
  assert.equal(lib.canSendFeedback("ab"), false);
  assert.equal(lib.canSendFeedback("  ab  "), false);
  assert.equal(lib.canSendFeedback("abc"), true);
  assert.equal(lib.canSendFeedback("a".repeat(lib.MAX_FEEDBACK)), true);
  assert.equal(lib.canSendFeedback("a".repeat(lib.MAX_FEEDBACK + 1)), false);
});

test("only the path is sent: query strings and fragments (ids, search text) are dropped", () => {
  assert.equal(lib.pageOf("/dashboard/cases/123?q=Ayşe%20Yılmaz#notlar"), "/dashboard/cases/123");
  assert.equal(lib.pageOf("/dashboard/ai"), "/dashboard/ai");
  assert.equal(lib.pageOf("/" + "a".repeat(300)).length, 200);
});

test("the insert carries the category, trimmed message and page and nothing else", async () => {
  inserts.length = 0;
  await lib.sendFeedback({ category: "hata", message: "  Arama çok yavaş  ", pathname: "/dashboard/legislation?q=x" });
  assert.deepEqual(inserts, [{ table: "feedback", row: { category: "hata", message: "Arama çok yavaş", page: "/dashboard/legislation" } }]);
});

test("a server error is surfaced as an error", async () => {
  globalThis.__feedbackError = { message: "Sunucu hatası" };
  await assert.rejects(lib.sendFeedback({ category: "oneri", message: "deneme", pathname: "/dashboard" }), /Sunucu hatası/);
  delete globalThis.__feedbackError;
});

test("the three categories are offered", () => {
  assert.deepEqual(lib.FEEDBACK_CATEGORIES.map((item) => item.value), ["hata", "oneri", "begeni"]);
});

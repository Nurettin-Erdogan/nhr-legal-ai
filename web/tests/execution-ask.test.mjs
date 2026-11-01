import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";

// Dosyalar arası soru yanıtının okunması (örnekler uydurmadır).
const require = createRequire(import.meta.url);
function compile(relative) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8").replace(
    "import.meta.env?.VITE_API_URL",
    "undefined",
  );
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(
    (name) => (name === "@/lib/auth-api" ? { inMemoryAccessToken: () => null } : require(name)),
    module,
    module.exports,
  );
  return module.exports;
}
const lib = compile("../src/lib/execution-ask.ts");

test("the answer is read safely: broken rows are dropped and the record lines are kept as written", () => {
  const answer = lib.parseAnswer({
    ok: true,
    understood: ["Araç sorgusu: VAR", 5],
    total_files: 18,
    matched: 2,
    not_evaluated: 1,
    note: "1 dosya değerlendirilemedi",
    rows: [
      {
        case_id: "c1",
        file_no: "2025/1",
        court: "Ankara 7. Genel İcra Dairesi",
        status: "Açık",
        creditors: ["DENEME ALACAK A.Ş."],
        debtors: ["AYŞE ÖRNEK", ""],
        last_activity: "2026-10-05",
        days_since_last: 8,
        facts: ["Araç sorgusu: VAR · 05.10.2026 (AYŞE ÖRNEK)", null],
      },
      { file_no: "kimliksiz" },
      "bozuk",
      { case_id: "c2", days_since_last: -3 },
    ],
    examples: ["Açık dosyalarım hangileri?"],
  });

  assert.equal(answer.rows.length, 2);
  assert.deepEqual(answer.rows[0], {
    caseId: "c1",
    fileNo: "2025/1",
    court: "Ankara 7. Genel İcra Dairesi",
    status: "Açık",
    creditors: ["DENEME ALACAK A.Ş."],
    debtors: ["AYŞE ÖRNEK"],
    lastActivity: "2026-10-05",
    daysSinceLast: 8,
    facts: ["Araç sorgusu: VAR · 05.10.2026 (AYŞE ÖRNEK)"],
  });
  assert.equal(answer.rows[1].daysSinceLast, null);
  assert.deepEqual(answer.understood, ["Araç sorgusu: VAR"]);
  assert.equal(lib.answerHeadline(answer), "Eşleşen dosya: 2 / 18");
});

test("a refused question shows no rows and says so; a truncated list says how many are shown", () => {
  const refused = lib.parseAnswer({
    ok: false,
    note: "Bu soruyu bir dosya süzgecine çeviremedim",
    examples: ["a", "b"],
  });
  assert.deepEqual([refused.ok, refused.rows, refused.matched], [false, [], 0]);
  assert.equal(lib.answerHeadline(refused), "Soru anlaşılamadı");
  assert.equal(lib.parseAnswer(null).ok, false);

  const many = lib.parseAnswer({
    ok: true,
    total_files: 500,
    matched: 340,
    rows: [{ case_id: "a" }, { case_id: "b" }],
  });
  assert.equal(lib.answerHeadline(many), "Eşleşen dosya: 340 / 500 (ilk 2 dosya gösteriliyor)");
});

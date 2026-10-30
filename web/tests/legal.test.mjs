import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/lib/legal.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const legal = { exports: {} };
new Function("module", "exports", outputText)(legal, legal.exports);
const lib = legal.exports;

test("the notice version fits the server column and is a plain label", () => {
  assert.ok(lib.PRIVACY_NOTICE_VERSION.length <= 40);
  assert.match(lib.PRIVACY_NOTICE_VERSION, /^[0-9a-z-]+$/);
});

test("unfilled controller details stay visibly bracketed instead of being invented", () => {
  for (const value of Object.values(lib.CONTROLLER))
    assert.ok(lib.hasPlaceholders(value), `${value} doldurulmuş görünüyor`);
  assert.equal(lib.hasPlaceholders("Gerçek Büro Hukuk Ltd."), false);
});

test("the legal pages mention the facts the product guarantees and the draft banner is on until a lawyer approves", () => {
  assert.equal(lib.LEGAL_DRAFT, true);
  const privacy = readFileSync(new URL("../src/routes/gizlilik.tsx", import.meta.url), "utf8");
  for (const must of [
    "yerel bir modelle",
    "eğitiminde kullanılmaz",
    "Google Fonts",
    "nhr_access_token",
    "Verilerimi indir",
    "KVKK m. 11",
  ])
    assert.ok(privacy.includes(must), `${must} gizlilik metninde yok`);
  const terms = readFileSync(
    new URL("../src/routes/kullanim-sartlari.tsx", import.meta.url),
    "utf8",
  );
  for (const must of ["avukatlık hizmeti değildir", "doğrulanmamış", "dava sonucu tahmini yapmaz"])
    assert.ok(terms.toLowerCase().includes(must.toLowerCase()), `${must} şartlarda yok`);
});

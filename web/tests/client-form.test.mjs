import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function load(relative) {
  const code = readFileSync(new URL(relative, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const module = { exports: {} };
  new Function("module", "exports", outputText)(module, module.exports);
  return module.exports;
}
const { validNationalId, validTaxId, validPhone, clientFormProblem } = load("../src/lib/client-form.ts");

test("TC kimlik no: hane denetimi tutan numara kabul, tutmayan ret", () => {
  assert.equal(validNationalId("10000000146"), true);
  assert.equal(validNationalId("100 000 001 46"), true);
  assert.equal(validNationalId("10000000147"), false);
  assert.equal(validNationalId("12345678901"), false);
  assert.equal(validNationalId("00000000000"), false);
  assert.equal(validNationalId("1000000014"), false);
  assert.equal(validNationalId("1000000014a"), false);
});

test("vergi kimlik no: hane denetimi tutan numara kabul, tek hanesi değişen ret", () => {
  assert.equal(validTaxId("4810058590"), true);
  assert.equal(validTaxId("1234567890"), true);
  assert.equal(validTaxId("481 005 85 90"), true);
  assert.equal(validTaxId("4810058591"), false);
  assert.equal(validTaxId("481005859"), false);
  assert.equal(validTaxId("abcdefghij"), false);
});

test("telefon: en az 10 rakam; harf içeren ya da kısa numara ret", () => {
  assert.equal(validPhone("+90 532 123 45 67"), true);
  assert.equal(validPhone("0 (312) 123-45-67"), true);
  assert.equal(validPhone("5321234567"), true);
  assert.equal(validPhone("12345"), false);
  assert.equal(validPhone("telefon yok"), false);
  assert.equal(validPhone("+90 532 123 45 67 dahili 4"), false);
});

test("form: boş alanlar sorun değildir; dolu ve hatalı alan açıklamasıyla bildirilir", () => {
  assert.equal(clientFormProblem({ client_type: "individual", national_id: "", tax_id: "", phone: "" }), null);
  assert.equal(clientFormProblem({ client_type: "individual", national_id: "10000000146", phone: "+90 532 123 45 67" }), null);
  assert.match(clientFormProblem({ client_type: "individual", national_id: "123" }), /11 haneli/);
  assert.match(clientFormProblem({ client_type: "individual", national_id: "12345678901" }), /geçersiz görünüyor/);
  assert.match(clientFormProblem({ client_type: "individual", national_id: "10000000146", phone: "123" }), /Telefon/);
});

test("form: tüzel kişide vergi no denetlenir; şahıs işletmesinin TC kimlik nosu da kabul edilir", () => {
  assert.equal(clientFormProblem({ client_type: "corporate", tax_id: "4810058590" }), null);
  assert.equal(clientFormProblem({ client_type: "corporate", tax_id: "10000000146" }), null);
  assert.match(clientFormProblem({ client_type: "corporate", tax_id: "4810058591" }), /geçersiz görünüyor/);
  assert.match(clientFormProblem({ client_type: "corporate", tax_id: "12" }), /10 haneli/);
  // Tüzel kişide gizli kalan TC alanı denetlenmez (tip değiştirilince eski değer kayda engel olmasın).
  assert.equal(clientFormProblem({ client_type: "corporate", national_id: "123", tax_id: "" }), null);
});

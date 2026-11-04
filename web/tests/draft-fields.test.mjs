import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/lib/draft-fields.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
const mod = { exports: {} };
new Function("exports", compiled)(mod.exports);
const { fieldsForDocument } = mod.exports;

test("notice fields survive form submission without contract or petition fields", () => {
  const fields = fieldsForDocument("ihtarname", {
    notice_demand: " Ödeme ",
    notice_period: "30 gün",
    notice_consequence: "Fesih",
    effective_date: "02.11.2026",
    payment: "not part of notice",
    authority: "not part of notice",
  });
  assert.deepEqual(fields, {
    notice_demand: "Ödeme",
    notice_period: "30 gün",
    notice_consequence: "Fesih",
    effective_date: "02.11.2026",
  });
});

test("draft terms stay with their document type and are trimmed without invention", () => {
  const values = { authority: " Mahkeme ", requests: "Tahsil", payment: " 500 TL " };
  const contract = fieldsForDocument("sozlesme", values);
  assert.equal(contract.payment, "500 TL");
  assert.equal(contract.termination, "");
  assert.equal(contract.requests, undefined);
  const petition = fieldsForDocument("dilekce", values);
  assert.equal(petition.authority, "Mahkeme");
  assert.equal(petition.payment, undefined);
  assert.deepEqual(fieldsForDocument("diger", values), {});
});

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

// Kaynak etiketi kuralı (AGENTS.md, kullanıcı kararı 2026-10-18: uygulamada yalnız doğrulanmış kaynak; ayrım rozeti yok).
const source = readFileSync(new URL("../src/lib/source-label.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const lib = { exports: {} };
new Function("module", "exports", outputText)(lib, lib.exports);
const label = lib.exports;

test("only the user's own document is tagged; legal sources carry no verification badge, never a check mark", () => {
  assert.equal(label.verificationTag("official"), null);
  assert.deepEqual(label.verificationTag("user_document"), {
    label: "kullanıcı belgesi",
    tone: "document",
  });
  assert.equal(label.verificationTag("third_party"), null);
  assert.equal(label.verificationTag("unknown"), null);
});

test("the official portal link is offered only for the official decision search sites", () => {
  assert.equal(
    label.officialPortalUrl("https://karararama.yargitay.gov.tr/getDokuman?id=568108400"),
    "https://karararama.yargitay.gov.tr/getDokuman?id=568108400",
  );
  assert.equal(
    label.officialPortalUrl("https://karararama.danistay.gov.tr/getDokuman?id=17314400"),
    "https://karararama.danistay.gov.tr/getDokuman?id=17314400",
  );
  for (const bad of [
    "http://karararama.yargitay.gov.tr/getDokuman?id=1",
    "https://karararama.yargitay.gov.tr.evil.example/x",
    "javascript:alert(1)",
    "https://example.com/karar",
    "",
    null,
    undefined,
  ])
    assert.equal(label.officialPortalUrl(bad), null, String(bad));
});

test("the source name comes from the portal address, then the court name", () => {
  assert.equal(
    label.decisionSourceName("https://karararama.yargitay.gov.tr/getDokuman?id=1"),
    "Yargıtay kararı",
  );
  assert.equal(
    label.decisionSourceName("https://karararama.danistay.gov.tr/getDokuman?id=1"),
    "Danıştay kararı",
  );
  assert.equal(label.decisionSourceName(null, "Danıştay 4. Daire"), "Danıştay kararı");
  assert.equal(label.decisionSourceName(null, "Ankara BAM"), "Karar");
});

test("copied citations give the official portal link and never a verification mark", () => {
  assert.equal(
    label.citationSuffix("official", "https://karararama.yargitay.gov.tr/getDokuman?id=1"),
    " — resmî sitede: https://karararama.yargitay.gov.tr/getDokuman?id=1",
  );
  assert.equal(label.citationSuffix("official", null), "");
  assert.equal(
    label.citationSuffix("third_party", "https://karararama.yargitay.gov.tr/getDokuman?id=1"),
    " — resmî sitede: https://karararama.yargitay.gov.tr/getDokuman?id=1",
  );
  assert.equal(label.citationSuffix("third_party", "https://example.com"), "");
  assert.equal(label.citationSuffix("user_document"), " (kullanıcı belgesi)");
  for (const value of ["official", "third_party", "unknown"])
    assert.doesNotMatch(
      label.citationSuffix(value, "https://karararama.danistay.gov.tr/getDokuman?id=2"),
      /✓|doğrula/,
    );
});

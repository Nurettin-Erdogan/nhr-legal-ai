import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

// "Çekilmeyen dosyalar": listede olup JurisAI'a eksiksiz aktarıldığı doğrulanmamış dosyalar (UYAP okunmadan, anında).
function compile(relative, requires = {}) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(
    (name) => requires[name],
    module,
    module.exports,
  );
  return module.exports;
}
const sync = compile("../src/lib/uyap-sync-all.ts", {
  "@/lib/uyap-bridge": { startPullJob() {}, startTreeJob() {}, stopJob() {}, waitForJob() {} },
  "@/lib/steady-timer": { steadySleep: () => Promise.resolve() },
});

const file = (key, esas, birim) => ({
  key,
  esas,
  birim,
  yargiTuru: "İcra",
  role: "",
  tur: "",
  acilis: "",
  durum: "",
  cells: [],
});
const record = (esas, birim, complete, missing_count = 0) => ({
  esas,
  birim,
  complete,
  missing_count,
});

test("files without a complete verification are listed with the reason; complete ones are not", () => {
  const items = [
    file("ok", "2020/364", "Kahramankazan İcra Dairesi"),
    file("missing", "2024/124", "Ankara 33. Ağır Ceza Mahkemesi"),
    file("never", "2010/8096", "Ankara 9. İcra Dairesi"),
    file("unverified", "2011/9698", "Ankara 7. İcra Dairesi"),
    file("empty-ok", "2009/17135", "Ankara 9. İcra Dairesi"),
  ];
  const verified = [
    record("2020/364", "Kahramankazan İcra Dairesi", true),
    record("2024/124", "Ankara 33. Ağır Ceza Mahkemesi", false, 232),
    record("2011/9698", "Ankara 7. İcra Dairesi", false, 0),
    record("2009/17135", "Ankara 9. İcra Dairesi", true), // UYAP'ta evraksız, 0 evrakla eksiksiz kaydedilmiş
  ];

  assert.deepEqual(
    sync.unpulledFiles(items, verified).map((item) => [item.key, item.reason]),
    [
      ["missing", "232 evrak eksik"],
      ["never", "Hiç aktarılmamış"],
      ["unverified", "Aktarım doğrulanamadı"],
    ],
  );
});

test("the file is matched the way the server matches it: spaces and Turkish capital I do not create a second identity", () => {
  const verified = [record("2020/364", "Kahramankazan İcra Dairesi", true)];

  assert.deepEqual(
    sync.unpulledFiles([file("a", "2020 / 364", "KAHRAMANKAZAN  İCRA DAİRESİ")], verified),
    [],
  );
  // Başka birimdeki aynı numaralı dosya o kayıtla eşleşmez.
  assert.equal(
    sync.unpulledFiles([file("b", "2020/364", "Ankara 7. İcra Dairesi")], verified).length,
    1,
  );
});

test("without any stored verification every file is unpulled", () => {
  const items = [file("a", "2020/364", "X İcra Dairesi"), file("b", "2020/365", "X İcra Dairesi")];

  assert.deepEqual(
    sync.unpulledFiles(items, []).map((item) => item.reason),
    ["Hiç aktarılmamış", "Hiç aktarılmamış"],
  );
});

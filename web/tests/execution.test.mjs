import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";

const require = createRequire(import.meta.url);
function compile(relative) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8").replace("import.meta.env?.VITE_API_URL", "undefined");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)((name) => (name === "@/lib/auth-api" ? { inMemoryAccessToken: () => null } : require(name)), module, module.exports);
  return module.exports;
}
const lib = compile("../src/lib/execution.ts");

test("tutar Türkçe biçimde yazılır; geçersiz değer tire olur", () => {
  assert.equal(lib.formatLira("350.50"), "350,50 TL");
  assert.equal(lib.formatLira("1234567.9"), "1.234.567,90 TL");
  assert.equal(lib.formatLira("0.05"), "0,05 TL");
  assert.equal(lib.formatLira("12"), "12,00 TL");
  for (const bad of [null, undefined, "", "abc", "12,50", "-5"]) assert.equal(lib.formatLira(bad), "—");
});

test("makbuz satırı okunamayan makbuzu saklamaz ve sıfır göstermez", () => {
  assert.equal(lib.receiptLine({ count: 3, read: 3, total: "100.00" }), "100,00 TL (3 makbuz)");
  assert.equal(lib.receiptLine({ count: 36, read: 29, total: "5000.00" }), "5.000,00 TL (36 makbuzdan 29'i okundu)");
  assert.equal(lib.receiptLine({ count: 4, read: 0, total: null }), "okunamadı (4 makbuz)");
  assert.equal(lib.receiptLine({ count: 0, read: 0, total: null }), "—");
  assert.equal(lib.receiptLine(undefined), "—");
});

test("sunucu yanıtı savunmacı okunur: bozuk alanlar boşa düşer, sayfa çökmez", () => {
  assert.deepEqual(lib.parseExecution(null).files, []);
  assert.deepEqual(lib.parseExecution("bozuk").files, []);
  const data = lib.parseExecution({
    files: [
      { case_id: "c1", file_no: "2025/1", court: "Ankara İcra Dairesi", kind: "mahkeme", documents: 5, first_date: "2025-09-23", last_date: null, counts: { haciz: 2, teblig: "x", diger: -1 }, receipts: { tahsilat: { count: 2, read: 1, total: "10.00" }, masraf: { count: 1, read: 0, total: "bozuk" } } },
      { file_no: "kimliksiz" },
      "metin",
    ],
    summary: { files: 1, documents: 5, tahsilat: { count: 2, read: 1, total: "10.00" } },
    labels: { haciz: "Haciz", x: 7 },
  });
  assert.equal(data.files.length, 1);
  assert.deepEqual(data.files[0].counts, { haciz: 2 });
  assert.equal(data.files[0].kind, "mahkeme");
  assert.equal(data.files[0].receipts.masraf.total, null);
  assert.deepEqual(data.labels, { haciz: "Haciz" });
  assert.deepEqual(data.summary.masraf, { count: 0, read: 0, total: null });
  assert.equal(lib.parseExecution({ files: [{ case_id: "c", kind: "bilinmeyen" }] }).files[0].kind, "takip");
});

test("tarih gün.ay.yıl yazılır", () => {
  assert.equal(lib.dateTr("2026-03-06"), "06.03.2026");
  assert.equal(lib.dateTr("2026-03-06T10:00:00Z"), "06.03.2026");
  assert.equal(lib.dateTr(null), "—");
  assert.equal(lib.dateTr("yarın"), "—");
});

test("kapatılan daire dosyanın kapandığı anlamına gelmez; yalnız daire için işaretlenir", () => {
  assert.equal(lib.closedOffice("(Kapatılan)Ankara 2. İcra Dairesi"), true);
  assert.equal(lib.closedOffice("Ankara 7. Genel İcra Dairesi"), false);
});

const files = [
  { case_id: "a", file_no: "2025/148157", court: "Ankara Banka Alacakları İcra Dairesi", kind: "takip" },
  { case_id: "b", file_no: "2019/1157", court: "Ankara 13. İcra Hukuk Mahkemesi", kind: "mahkeme" },
  { case_id: "c", file_no: "2020/364", court: "Kahramankazan İcra Dairesi", kind: "takip" },
];

test("arama dosya no ve daire adıyla, Türkçe büyük/küçük harf gözetmeden süzer", () => {
  assert.deepEqual(lib.filterFiles(files, "", "all").map((f) => f.case_id), ["a", "b", "c"]);
  assert.deepEqual(lib.filterFiles(files, "2019/1157", "all").map((f) => f.case_id), ["b"]);
  assert.deepEqual(lib.filterFiles(files, "İCRA DAİRESİ", "all").map((f) => f.case_id), ["a", "c"]);
  assert.deepEqual(lib.filterFiles(files, "kahraman", "all").map((f) => f.case_id), ["c"]);
  assert.deepEqual(lib.filterFiles(files, "", "mahkeme").map((f) => f.case_id), ["b"]);
  assert.deepEqual(lib.filterFiles(files, "ankara", "takip").map((f) => f.case_id), ["a"]);
  assert.deepEqual(lib.filterFiles(files, "yok", "all"), []);
});

test("evrak rozetleri en kalabalık türden başlar, 'diğer' sona kalır", () => {
  const labels = { haciz: "Haciz", teblig: "Tebligat", diger: "Diğer" };
  assert.deepEqual(lib.countBadges({ diger: 50, teblig: 20, haciz: 3 }, labels), [
    { key: "teblig", label: "Tebligat", count: 20 },
    { key: "haciz", label: "Haciz", count: 3 },
    { key: "diger", label: "Diğer", count: 50 },
  ]);
  assert.equal(lib.countBadges({ a: 1, b: 2, c: 3 }, {}, 2).length, 2);
  assert.equal(lib.countBadges({ x: 4 }, {})[0].label, "x");
});

test("UYAP durumu ve doğrulama: hiç karşılaştırılmamış dosya eksiksiz ya da eksik diye gösterilmez", () => {
  assert.deepEqual(lib.verificationLabel(null), { text: "UYAP ile karşılaştırılmadı", tone: "none" });
  const base = { durum: "Açık", tur: null, rol: null, acilis: null, checkedAt: "2026-10-06T11:00:00Z" };
  assert.deepEqual(lib.verificationLabel({ ...base, complete: true, missing: 0 }), { text: "UYAP'taki evrakların tamamı aktarılmış (06.10.2026)", tone: "ok" });
  assert.deepEqual(lib.verificationLabel({ ...base, complete: false, missing: 3 }), { text: "3 evrak eksik (06.10.2026)", tone: "warn" });
  assert.deepEqual(lib.verificationLabel({ ...base, complete: false, missing: 0, checkedAt: null }), { text: "Aktarım doğrulanamadı", tone: "warn" });
  assert.equal(lib.shortStatus("Kapalı ( 27.06.2025 11:43:11 )"), "Kapalı");
  assert.equal(lib.shortStatus("Açık"), "Açık");
  assert.equal(lib.shortStatus(null), "");

  const data = lib.parseExecution({
    files: [
      { case_id: "a", uyap: { durum: "Açık", rol: "Alacaklı", complete: true, missing: 0, checked_at: "2026-10-06T11:00:00Z" } },
      { case_id: "b", uyap: null },
      { case_id: "c", uyap: "bozuk" },
    ],
    summary: { files: 3, documents: 9, verified_complete: 1, never_verified: 2 },
  });
  assert.deepEqual(data.files.map((f) => f.uyap && f.uyap.complete), [true, null, null]);
  assert.equal(data.files[0].uyap.rol, "Alacaklı");
  assert.deepEqual([data.summary.verifiedComplete, data.summary.neverVerified], [1, 2]);
});

test("UYAP'tan çekilen dosya hesabı özeti aynen okunur; çekilmemişse null, bozuk alan atılır", () => {
  const data = lib.parseExecution({
    files: [
      { case_id: "a", detail: { complete: true, fetched_at: "2026-10-06T16:00:00Z", account: [{ label: "Toplam Alacak", value: "13.783,00 TL" }, { label: 5, value: "x" }, "bozuk"] } },
      { case_id: "b", detail: null },
      { case_id: "c", detail: "bozuk" },
    ],
  });
  assert.deepEqual(data.files.map((f) => f.detail && f.detail.complete), [true, null, null]);
  assert.deepEqual(data.files[0].detail.account, [{ label: "Toplam Alacak", value: "13.783,00 TL" }]);
  assert.equal(data.files[0].detail.fetchedAt, "2026-10-06T16:00:00Z");
});

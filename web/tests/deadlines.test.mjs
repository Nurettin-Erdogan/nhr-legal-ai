import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function compile(relative) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(() => ({}), module, module.exports);
  return module.exports;
}
const d = compile("../src/lib/deadlines.ts");
const rule = (id) => d.ruleById(id);
const run = (id, start) => d.calculateDeadline(rule(id), start);

test("her kuralın dayanağı, alıntısı ve pozitif süresi vardır; kimlikler tekildir", () => {
  const ids = d.DEADLINE_RULES.map((r) => r.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const r of d.DEADLINE_RULES) {
    assert.ok(r.law && r.quote && r.startLabel && r.amount > 0, r.id);
    assert.ok(["gün", "hafta", "ay"].includes(r.unit));
  }
  // Doğrulanan süreler (2026-10-06, resmî mevzuat metni): ceza istinaf/temyiz artık iki hafta; kambiyo şikâyeti beş gün.
  assert.deepEqual(["cmk-273", "cmk-291", "hmk-345", "hmk-361", "hmk-127"].map((id) => [rule(id).amount, rule(id).unit]), Array(5).fill([2, "hafta"]));
  assert.deepEqual([rule("iik-62").amount, rule("iik-16").amount, rule("iik-168").amount], [7, 7, 5]);
});

test("hafta sürede başladığı güne karşılık gelen gün; hafta içine rastlarsa kayma yok", () => {
  const result = run("hmk-345", "2026-10-05"); // Pazartesi
  assert.equal(result.raw, "2026-10-19");
  assert.equal(result.end, "2026-10-19");
  assert.equal(d.weekdayName(result.end), "Pazartesi");
  assert.deepEqual(result.warnings, []);
});

test("gün sürede tebliğ günü sayılmaz; son gün hafta sonuysa ilk iş günü (HMK 93)", () => {
  const result = run("iik-62", "2026-10-03"); // Cumartesi + 7 = Cumartesi
  assert.equal(result.raw, "2026-10-10");
  assert.equal(result.end, "2026-10-12"); // Pazartesi
  assert.match(result.steps.join(" "), /Cumartesi.*Pazar|Cumartesi/);
  assert.match(result.steps.join(" "), /HMK m\. 93/);
});

test("sabit resmî tatil: 29 Ekim'e rastlayan süre ertesi iş gününe kalır", () => {
  const result = run("iik-168", "2026-10-24"); // Cumartesi + 5 = 29 Ekim Perşembe
  assert.equal(result.raw, "2026-10-29");
  assert.equal(result.end, "2026-10-30");
});

test("bayram: Kurban Bayramı 2026 (27-30 Mayıs) + hafta sonu birlikte aşılır", () => {
  const result = run("iik-62", "2026-05-20"); // + 7 = 27 Mayıs (bayramın ilk günü)
  assert.equal(result.raw, "2026-05-27");
  assert.equal(result.end, "2026-06-01");
  assert.match(result.steps.join(" "), /dinî bayram tatili/);
});

test("ay sürede karşılık gelen gün yoksa ayın son günü, o da tatilse iş gününe", () => {
  const result = run("isk-20-arabulucu", "2026-01-31"); // 31 Ocak + 1 ay → 28 Şubat 2026 (Cumartesi)
  assert.equal(result.raw, "2026-02-28");
  assert.equal(result.end, "2026-03-02");
});

test("adli tatil: HMK kuralında otomatik uzatılmaz, uzamış hâli ayrıca gösterilir; HMK dışında yalnız uyarı", () => {
  const hmk = run("hmk-345", "2026-07-14"); // + 14 = 28 Temmuz (adli tatil)
  assert.equal(hmk.end, "2026-07-28"); // ana tarih uzatmasız
  assert.equal(hmk.recessEnd, "2026-09-07"); // 31 Ağustos + 1 hafta
  assert.match(hmk.warnings.join(" "), /HMK m\. 104/);
  const iik = run("iik-62", "2026-07-22"); // + 7 = 29 Temmuz
  assert.equal(iik.recessEnd, null);
  assert.match(iik.warnings.join(" "), /adli tatil.*otomatik hesaplanmadı/);
});

test("HMK dışı kurallarda kanunun kendi hükmünü kontrol et uyarısı; tablo dışı yılda bayram uyarısı", () => {
  assert.match(run("cmk-273", "2026-10-05").warnings.join(" "), /kendi süre\/tatil hükmü/);
  assert.equal(run("hmk-345", "2026-10-05").warnings.length, 0);
  assert.match(run("hmk-345", "2028-10-02").warnings.join(" "), /2028 yılının dinî bayram tarihleri tabloda yok/);
});

test("geçersiz tarih reddedilir; Türkçe tarih okunur", () => {
  assert.equal(run("hmk-345", "2026-02-30").ok, false);
  assert.equal(run("hmk-345", "").ok, false);
  assert.equal(d.isoFromTr("05.10.2026 14:30:00"), "2026-10-05");
  assert.equal(d.isoFromTr("31.02.2026"), null);
  assert.equal(d.formatDateTr("2026-10-05"), "05.10.2026");
});

test("safahattan olası başlangıçlar: yalnız tebligat/ödeme emri/karar içeren kayıtlar, en yeni önce; hiçbiri kendiliğinden başlamaz", () => {
  const headers = ["İşlem Yapan Birim", "Tarih", "İşlem Türü", "Açıklama", "İşlem Durumu"];
  const rows = [
    ["Ankara İcra", "01.09.2026", "Takip Talebi", "Dosya açıldı", ""],
    ["Ankara İcra", "03.09.2026", "Ödeme Emri Tebligatı", "Borçluya gönderildi", ""],
    ["Ankara İcra", "10.09.2026", "Haciz", "Maaş haczi", ""],
    ["Mahkeme", "20.09.2026 10:00:00", "Karar", "Gerekçeli karar", ""],
    ["Mahkeme", "bozuk", "Tebligat", "x", ""],
  ];
  const found = d.startCandidates(headers, rows);
  assert.deepEqual(found.map((c) => c.date), ["2026-09-20", "2026-09-03"]);
  assert.match(found[1].label, /Ödeme Emri Tebligatı/);
  assert.deepEqual(d.startCandidates(["x"], rows), []);
});

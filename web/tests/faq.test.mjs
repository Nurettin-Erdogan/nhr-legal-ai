import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/lib/faq.ts", import.meta.url), "utf8");
function load() {
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  new Function("module", "exports", outputText)(module, module.exports);
  return module.exports;
}
const { FAQ_ITEMS, FAQ_CATEGORIES, FAQ_NOTE, basisLabel, faqByCategory } = load();

test("hukuki sonuç söyleyen her cevabın kanun dayanağı vardır", () => {
  const legal = FAQ_ITEMS.filter(
    (item) => item.kategori === "İş Hukuku" || item.kategori === "Aile Hukuku",
  );
  assert.ok(legal.length >= 6);
  for (const item of legal) assert.ok(item.dayanak?.length, `dayanaksız hukuki cevap: ${item.q}`);
  // Süre ya da oran söyleyen cevap, kategorisi ne olursa olsun, dayanaksız olamaz.
  for (const item of FAQ_ITEMS) {
    if (/\b(bir ay|iki hafta|altı ay|bir yıl|otuz) /i.test(item.a) && !/tahmin/i.test(item.a))
      assert.ok(item.dayanak?.length, `dayanaksız süre: ${item.q}`);
  }
});

test("dayanak girdileri denetim betiğinin okuyabileceği biçimdedir", () => {
  // scripts/verify_faq_sources.py bu kalıbı arar; biçim değişirse betik hiçbir şeyi denetlemez.
  const pattern = /\bb\(\s*"([^"]+)"\s*,\s*"(\d+)"\s*,\s*"(\d+)"\s*,\s*"([^"]+)"\s*\)/g;
  const found = [...source.matchAll(pattern)].length;
  const declared = FAQ_ITEMS.reduce((sum, item) => sum + (item.dayanak?.length ?? 0), 0);
  assert.equal(found, declared);
  for (const item of FAQ_ITEMS)
    for (const basis of item.dayanak ?? [])
      assert.ok(
        /^\d+$/.test(basis.kanunNo) && /^\d+$/.test(basis.madde) && basis.beklenen.length >= 3,
      );
});

test("dayanak satırı aynı kanunun maddelerini tek girdide toplar", () => {
  assert.equal(
    basisLabel([
      { kanun: "İş Kanunu", kanunNo: "4857", madde: "17", beklenen: "x" },
      { kanun: "Türk Medeni Kanunu", kanunNo: "4721", madde: "166", beklenen: "x" },
      { kanun: "İş Kanunu", kanunNo: "4857", madde: "41", beklenen: "x" },
      { kanun: "İş Kanunu", kanunNo: "4857", madde: "17", beklenen: "x" },
    ]),
    "İş Kanunu (4857) m. 17, 41; Türk Medeni Kanunu (4721) m. 166",
  );
  assert.equal(basisLabel(undefined), "");
  assert.equal(basisLabel([]), "");
});

test("kategori süzgeci ve genel uyarı", () => {
  assert.equal(faqByCategory("Tümü").length, FAQ_ITEMS.length);
  assert.ok(faqByCategory("Aile Hukuku").every((item) => item.kategori === "Aile Hukuku"));
  for (const category of FAQ_CATEGORIES.slice(1))
    assert.ok(faqByCategory(category).length > 0, category);
  assert.match(FAQ_NOTE, /genel bilgilendirmedir; hukuki danışmanlık değildir/);
});

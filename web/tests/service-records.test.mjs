import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";

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
  const resolve = (name) =>
    name === "@/lib/auth-api"
      ? { inMemoryAccessToken: () => null }
      : name === "@/lib/deadlines"
        ? compile("../src/lib/deadlines.ts")
        : require(name);
  new Function("require", "module", "exports", outputText)(resolve, module, module.exports);
  return module.exports;
}
const lib = compile("../src/lib/service-records.ts");

const doc = (id) => ({ id, file_name: `${id}.pdf`, storage_path: `sahip/${id}` });
const RULE = {
  reference: "TEBLİGAT KANUNU (7201) m. 7/a",
  source_url: "https://www.mevzuat.gov.tr/x",
  sentence: "Elektronik yolla tebligat … yapılmış sayılır.",
  days: 5,
};
const record = (id, fields) => ({
  document: doc(id),
  doc_type: "Kapalı E-Tebliğ Mazbatası",
  served: null,
  events: [],
  delivered_on: null,
  stated_deemed_on: null,
  computed_deemed_on: null,
  agrees: null,
  ...fields,
});

test("sunucu yanıtı okunur: kayıtlar, olay satırları ve kuralın atfı", () => {
  const data = lib.parseServiceRecords({
    records: [
      record("a", {
        served: "Gerekçeli Karar",
        delivered_on: "2026-09-03",
        stated_deemed_on: "2026-09-08",
        computed_deemed_on: "2026-09-08",
        agrees: true,
        events: [
          {
            kind: "delivered",
            label: "Muhatabın hesabına ulaştı",
            at: "2026-09-03T10:15:00",
            text: "… konuldu.",
          },
          { kind: "x", at: "bozuk" },
          "x",
        ],
      }),
    ],
    unreadable: 2,
    rule: RULE,
  });
  assert.equal(data.records.length, 1);
  assert.equal(data.records[0].documentId, "a");
  assert.deepEqual(
    data.records[0].events.map((e) => e.at),
    ["2026-09-03T10:15:00"],
  );
  assert.equal(data.records[0].agrees, true);
  assert.equal(data.unreadable, 2);
  assert.deepEqual(data.rule, {
    reference: RULE.reference,
    sourceUrl: RULE.source_url,
    sentence: RULE.sentence,
    days: 5,
  });
});

test("bozuk yanıt sayfayı çökertmez; güvenli olmayan bağlantı ve eksik kural kullanılmaz", () => {
  for (const bad of [null, undefined, "x", 3, [], { records: "x", rule: "y" }]) {
    const data = lib.parseServiceRecords(bad);
    assert.deepEqual(data, { records: [], unreadable: 0, rule: null });
  }
  const data = lib.parseServiceRecords({
    records: [{ document: {} }, record("a", { delivered_on: "03.09.2026" })],
    unreadable: -4,
    rule: { ...RULE, source_url: "javascript:alert(1)" },
  });
  assert.equal(data.records.length, 1);
  assert.equal(data.records[0].deliveredOn, null); // ISO olmayan tarih tarih sayılmaz
  assert.equal(data.unreadable, 0);
  assert.equal(data.rule.sourceUrl, null);
  assert.equal(lib.parseServiceRecords({ rule: { reference: "x" } }).rule, null); // cümlesiz kural gösterilmez
});

test("uyuşma sunucunun sözüne değil iki tarihin kendisine bakılarak söylenir", () => {
  const data = lib.parseServiceRecords({
    records: [
      record("a", {
        stated_deemed_on: "2026-09-09",
        computed_deemed_on: "2026-09-08",
        agrees: true,
      }),
    ],
  });
  assert.equal(data.records[0].agrees, false);
});

test("mazbata ile hesap tutuyorsa tek aday önerilir ve hesaba ulaşma günü yanında yazar", () => {
  const data = lib.parseServiceRecords({
    records: [
      record("a", {
        served: "Gerekçeli Karar",
        delivered_on: "2026-09-03",
        stated_deemed_on: "2026-09-08",
        computed_deemed_on: "2026-09-08",
      }),
    ],
    rule: RULE,
  });
  assert.deepEqual(lib.serviceCandidates(data), [
    {
      date: "2026-09-08",
      documentId: "a",
      warning: "",
      label:
        "E-tebligat yapılmış sayıldı (mazbata ve hesap aynı) (hesaba ulaşma 03.09.2026) · Gerekçeli Karar",
    },
  ]);
});

test("mazbatada yazan gün hesapla tutmuyorsa ikisi de uyarıyla sunulur; biri sessizce seçilmez", () => {
  const data = lib.parseServiceRecords({
    records: [
      record("a", {
        delivered_on: "2026-09-03",
        stated_deemed_on: "2026-09-09",
        computed_deemed_on: "2026-09-08",
      }),
    ],
  });
  const candidates = lib.serviceCandidates(data);
  assert.deepEqual(
    candidates.map((c) => c.date),
    ["2026-09-09", "2026-09-08"],
  );
  assert.match(candidates[0].label, /mazbataya göre yapılmış sayıldı/);
  assert.match(candidates[1].label, /kurala göre yapılmış sayılır/);
  for (const c of candidates) assert.match(c.warning, /09\.09\.2026.*08\.09\.2026.*farklı/);
});

test("kural doğrulanamadıysa yalnız mazbatanın yazdığı gün; o da yoksa hesaba ulaşma günü açık uyarıyla", () => {
  const stated = lib.serviceCandidates(
    lib.parseServiceRecords({
      records: [record("a", { delivered_on: "2026-09-03", stated_deemed_on: "2026-09-08" })],
    }),
  );
  assert.equal(stated.length, 1);
  assert.match(stated[0].label, /mazbataya göre yapılmış sayıldı/);
  const computed = lib.serviceCandidates(
    lib.parseServiceRecords({
      records: [record("a", { delivered_on: "2026-09-03", computed_deemed_on: "2026-09-08" })],
    }),
  );
  assert.match(computed[0].label, /kurala göre yapılmış sayılır/);
  const reached = lib.serviceCandidates(
    lib.parseServiceRecords({ records: [record("a", { delivered_on: "2026-09-03" })] }),
  );
  assert.equal(reached[0].date, "2026-09-03");
  assert.match(reached[0].warning, /tebliğ günü değildir/);
  assert.deepEqual(
    lib.serviceCandidates(lib.parseServiceRecords({ records: [record("a", {})] })),
    [],
  ); // hiçbir tarih yoksa aday yok
});

test("yapılmış sayıldığı gün hafta sonuna rastlıyorsa bu söylenir, gün kaydırılmaz", () => {
  // 31 Ağustos 2026 Pazartesi + 5 gün = 5 Eylül 2026 Cumartesi
  const candidates = lib.serviceCandidates(
    lib.parseServiceRecords({
      records: [record("a", { delivered_on: "2026-08-31", computed_deemed_on: "2026-09-05" })],
    }),
  );
  assert.equal(candidates[0].date, "2026-09-05");
  assert.match(candidates[0].warning, /Cumartesi/);
});

test("adaylar en yeni tebliğ önce sıralanır", () => {
  const data = lib.parseServiceRecords({
    records: [
      record("eski", { stated_deemed_on: "2026-03-04" }),
      record("yeni", { stated_deemed_on: "2026-09-08" }),
    ],
  });
  assert.deepEqual(
    lib.serviceCandidates(data).map((c) => c.documentId),
    ["yeni", "eski"],
  );
});

test("başlık okunan ve okunamayan evrakı ayrı ayrı sayar", () => {
  assert.equal(
    lib.recordsHeadline({ records: [{}, {}], unreadable: 3, rule: null }),
    "2 e-tebliğ mazbatası okundu · 3 tebliğ evrakının tarihi okunamadı (kâğıt mazbata ya da zarf)",
  );
  assert.equal(
    lib.recordsHeadline({ records: [{}], unreadable: 0, rule: null }),
    "1 e-tebliğ mazbatası okundu",
  );
  assert.equal(lib.recordsHeadline({ records: [], unreadable: 0, rule: null }), "");
});

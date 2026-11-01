import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";

const require = createRequire(import.meta.url);
function compile(relative, dependencies = {}) {
  const source = readFileSync(new URL(relative, import.meta.url), "utf8").replace(
    "import.meta.env?.VITE_API_URL",
    "undefined",
  );
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
    },
  });
  const module = { exports: {} };
  new Function("require", "module", "exports", outputText)(
    (id) => dependencies[id] ?? require(id),
    module,
    module.exports,
  );
  return module.exports;
}

const view = compile("../src/lib/uyap-detail-view.ts");
const deadlinesLib = compile("../src/lib/deadlines.ts");
const caseSummary = compile("../src/lib/uyap-case-summary.ts", {
  "@/lib/uyap-detail-view": view,
  "@/lib/deadlines": deadlinesLib,
});
const stubIcon = () => null;
const { UyapDetailView } = compile("../src/components/UyapCaseDetail.tsx", {
  "lucide-react": { AlertTriangle: stubIcon, CheckCircle2: stubIcon },
  "@/lib/router-compat": { Link: ({ children }) => children },
  "@/lib/uyap-detail-view": view,
  "@/lib/uyap-case-summary": caseSummary,
  "@/lib/uyap-sync-api": { loadCaseDetail: async () => null },
});

const table = (rows, extra = {}) => ({
  title: "",
  headers: ["Tarih", "İşlem Türü", "Açıklama"],
  rows,
  declared: rows.length,
  complete: true,
  ...extra,
});
const detail = (overrides = {}) => ({
  who: { esas: "2025/1", birim: "Ankara İcra Dairesi" },
  complete: true,
  problems: [],
  tabs: [
    {
      key: "safahat",
      label: "Safahat",
      pairs: [],
      complete: true,
      tables: [
        table([
          ["01.01.2024", "Haciz Talebi", "Maaş haczi"],
          ["02.01.2024", "Tebligat", "ISPARTA adresine"],
        ]),
      ],
    },
    {
      key: "hesap",
      label: "Dosya Hesabı",
      pairs: [
        { label: "Toplam Alacak", value: "13.783,00 TL" },
        { label: "Bakiye Borç Miktari", value: "11.783,00 TL" },
      ],
      tables: [],
      complete: true,
    },
    {
      key: "bilgiler",
      label: "Dosya Bilgileri",
      pairs: [{ label: "Türü", value: "İcra Dosyası" }],
      tables: [],
      complete: true,
    },
  ],
  ...overrides,
});

test("Türkçe arama büyük/küçük harf ve ı/i, ş/s gözetmez; her sözcük aranır", () => {
  const rows = [
    ["01.01.2024", "Haciz Talebi", "ISPARTA adresine"],
    ["02.01.2024", "Tebligat", "Şişli"],
  ];
  assert.deepEqual(
    view.filterRows(rows, "isparta").map((r) => r[1]),
    ["Haciz Talebi"],
  );
  assert.deepEqual(view.filterRows(rows, "ISPARTA haciz").length, 1);
  assert.deepEqual(view.filterRows(rows, "sisli").length, 1);
  assert.deepEqual(view.filterRows(rows, "  ").length, 2);
  assert.deepEqual(view.filterRows(rows, "yok yok"), []);
  assert.equal(view.foldText("İSTANBUL Iğdır"), "istanbul igdir");
});

test("bölümler önce dosya bilgileri ve hesap, sonra taraf ve safahat sırasıyla gelir", () => {
  assert.deepEqual(
    view.orderedTabs(detail()).map((t) => t.key),
    ["bilgiler", "hesap", "safahat"],
  );
  assert.equal(
    view.tabTitle({ key: "tahsilat", label: "Tah./Red. Bilgileri" }),
    "Tahsilat / reddiyat",
  );
  assert.equal(view.tabTitle({ key: "yeni", label: "Yeni Sekme" }), "Yeni Sekme");
});

test("eksik okunan tablo ve eklentinin bildirdiği sorunlar uyarı olarak gösterilir, hiçbiri gizlenmez", () => {
  const tab = {
    key: "safahat",
    label: "Safahat",
    pairs: [],
    complete: false,
    tables: [table([["a", "b", "c"]], { declared: 25, complete: false })],
  };
  assert.equal(
    view.tableWarning(tab, tab.tables[0]),
    "Safahat: UYAP 25 kayıt yazıyor, 1 kayıt alındı.",
  );
  assert.equal(
    view.tableWarning(tab, { ...tab.tables[0], declared: null }),
    "Safahat: tablo eksiksiz okunamadı.",
  );
  assert.equal(view.tableWarning(tab, { ...tab.tables[0], complete: true }), null);
  assert.deepEqual(
    view.detailWarnings(
      detail({
        tabs: [tab],
        problems: [
          "Safahat: UYAP 25 kayıt yazıyor, 1 kayıt alındı.",
          "Taraf Bilgileri: sekme açılmadı.",
        ],
      }),
    ),
    ["Safahat: UYAP 25 kayıt yazıyor, 1 kayıt alındı.", "Taraf Bilgileri: sekme açılmadı."],
  );
  assert.deepEqual(view.detailWarnings(detail()), []);
});

test("dosya hesabı özeti UYAP'ın yazdığı metni aynen verir; hiçbir şey hesaplanmaz, bulunmayan alan atlanır", () => {
  const pairs = detail().tabs[1].pairs;
  assert.deepEqual(view.accountSummary(pairs), [
    { label: "Toplam Alacak", value: "13.783,00 TL" },
    { label: "Bakiye Borç Miktarı", value: "11.783,00 TL" }, // UYAP "Miktari" yazsa da bulunur; "Yatan Para" yoksa atlanır
  ]);
  assert.deepEqual(view.accountSummary([]), []);
  assert.deepEqual(view.accountSummary([{ label: "Toplam Alacak", value: "" }]), []);
});

test("gösterim tam olduğunda yeşil, eksik olduğunda uyarılı; kaçış yapılmış metin ve UYAP uyarısı vardır", () => {
  const complete = renderToStaticMarkup(
    createElement(UyapDetailView, {
      detail: detail(),
      fetchedAt: "2026-10-06T16:00:00Z",
      complete: true,
    }),
  );
  assert.match(complete, /bilgilerin tamamı alındı/);
  assert.match(complete, /Dosya bilgileri/);
  assert.match(complete, /Dosya hesabı/);
  assert.match(complete, /13\.783,00 TL/);
  assert.match(complete, /yorum yapmaz/); // yorumsuzluk notu
  assert.ok(
    complete.indexOf(`aria-label="Dosya bilgileri"`) < complete.indexOf(`aria-label="Safahat"`),
  ); // bölüm sırası
  assert.doesNotMatch(complete, /eksik alınmış/);

  const tab = {
    key: "safahat",
    label: "Safahat",
    pairs: [],
    complete: false,
    tables: [table([["a", "b", "<script>x</script>"]], { declared: 25, complete: false })],
  };
  const partial = renderToStaticMarkup(
    createElement(UyapDetailView, {
      detail: detail({ tabs: [tab], complete: false }),
      fetchedAt: "",
      complete: false,
    }),
  );
  assert.match(partial, /eksik alınmış olabilir/);
  assert.match(partial, /UYAP 25 kayıt yazıyor, 1 kayıt alındı/);
  assert.match(partial, /UYAP 25 yazıyor/);
  assert.doesNotMatch(partial, /<script>x<\/script>/); // hücre metni kaçışlanır
});

test("durum özeti yalnız UYAP'ın metnini ve kayıt sayılarını verir; tutar toplanmaz, aşama tahmin edilmez", () => {
  const full = {
    who: { esas: "2025/1", birim: "Ankara İcra Dairesi" },
    complete: true,
    problems: [],
    tabs: [
      {
        key: "bilgiler",
        label: "Dosya Bilgileri",
        complete: true,
        tables: [],
        pairs: [
          { label: "Türü", value: "İlamsız Takip" },
          { label: "Dosya Durumu", value: "Açık" },
        ],
      },
      {
        key: "hesap",
        label: "Dosya Hesabı",
        complete: true,
        tables: [],
        pairs: [
          { label: "Toplam Alacak", value: "13.783,00 TL" },
          { label: "Yatan Para", value: "2.000,00 TL" },
          { label: "Bakiye Borç Miktari", value: "11.783,00 TL" },
        ],
      },
      {
        key: "taraflar",
        label: "Taraf Bilgileri",
        complete: true,
        pairs: [],
        tables: [
          {
            title: "",
            headers: ["Rol", "Tipi", "Adı"],
            rows: [
              ["Alacaklı", "Tüzel", "A"],
              ["Borçlu", "Gerçek", "B"],
              ["Borçlu", "Gerçek", "C"],
            ],
            declared: 3,
            complete: true,
          },
        ],
      },
      {
        key: "safahat",
        label: "Safahat",
        complete: true,
        pairs: [],
        tables: [
          {
            title: "",
            headers: ["İşlem Yapan Birim", "Tarih", "İşlem Türü", "Açıklama", "İşlem Durumu"],
            declared: 3,
            complete: true,
            rows: [
              ["x", "01.02.2026", "Takip Talebi", "Açıldı", ""],
              ["x", "09.03.2026 10:00:00", "Haciz", "Maaş", ""],
              ["x", "05.03.2026", "Haciz", "Banka", ""],
            ],
          },
        ],
      },
      {
        key: "tahsilat",
        label: "Tah./Red. Bilgileri",
        complete: true,
        pairs: [],
        tables: [
          {
            title: "Özet",
            headers: ["Tahsilat", "Reddiyat", "Tahsilat Kalanı"],
            rows: [["2.000,00 TL", "500,00 TL", "1.500,00 TL"]],
            declared: null,
            complete: true,
          },
        ],
      },
    ],
  };
  const summary = caseSummary.summarizeDetail(full);
  const facts = Object.fromEntries(summary.facts.map((f) => [f.label, f.value]));
  assert.equal(facts["Türü"], "İlamsız Takip");
  assert.equal(facts["Toplam Alacak"], "13.783,00 TL");
  assert.equal(facts["Bakiye Borç Miktarı"], "11.783,00 TL");
  assert.deepEqual(
    [facts["Tahsilat"], facts["Reddiyat"], facts["Tahsilat Kalanı"]],
    ["2.000,00 TL", "500,00 TL", "1.500,00 TL"],
  );
  assert.equal(summary.parties, "3 taraf: 1 Alacaklı, 2 Borçlu");
  assert.deepEqual(
    [summary.safahat.count, summary.safahat.first, summary.safahat.last],
    [3, "01.02.2026", "09.03.2026"],
  );
  assert.equal(summary.safahat.lastAction, "Haciz — Maaş");
  assert.deepEqual(summary.actionTypes[0], { label: "Haciz", count: 2 });
  assert.equal(summary.safahat.recent[0].date, "09.03.2026");
  // Hiçbir yorum alanı yok: aşama/sonuç adında bir bilgi üretilmez.
  assert.deepEqual(Object.keys(summary).sort(), ["actionTypes", "facts", "parties", "safahat"]);
  // Boş detay: çökmez.
  const empty = caseSummary.summarizeDetail({
    who: { esas: "", birim: "" },
    complete: false,
    problems: [],
    tabs: [],
  });
  assert.deepEqual(
    [empty.facts, empty.parties, empty.safahat, empty.actionTypes],
    [[], null, null, []],
  );
});

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";

// İcra dosyası incelemesi: UYAP bilgisi özetinin okunması ve gösterimi. Örnekler uydurmadır.
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
  new Function("require", "module", "exports", outputText)(
    (name) => (name === "@/lib/auth-api" ? { inMemoryAccessToken: () => null } : require(name)),
    module,
    module.exports,
  );
  return module.exports;
}
const detail = compile("../src/lib/execution-breakdown.ts");
const list = compile("../src/lib/execution.ts");

const OVERVIEW = {
  fetched_at: "2026-10-09T20:50:00Z",
  complete: true,
  identity: [
    { label: "Türü", value: "İlamsız Takip" },
    { label: "Dosya Durumu", value: "Açık" },
    { label: "", value: "x" },
    "bozuk",
  ],
  parties: [
    { role: "Alacaklı", type: "Kurum", name: "DENEME ALACAK A.Ş.", lawyer: "Av. DENEME VEKİL" },
    { role: "Borçlu", type: "Kişi", name: "AYŞE ÖRNEK", lawyer: "" },
    { role: "Borçlu", type: "Kişi", name: "ISMAIL DENEMECI", lawyer: "" },
    { role: "Borçlu", type: "Kişi", name: "" },
  ],
  account: [{ label: "Toplam Alacak", value: "₺13.783,00" }],
  collections: [{ label: "Tahsilat", value: "162,5 TL" }],
  activity: {
    entries: 12,
    undated: 0,
    first_date: "2025-02-01",
    last_date: "2026-09-30",
    days_since_last: 10,
    last: { type: "Gelen Evrak Kaydedilmesi", text: "yazı" },
  },
  milestones: [
    {
      key: "acilis",
      label: "Dosyanın açılması",
      count: 1,
      first_date: "2025-02-01",
      last_date: "2025-02-01",
      uyap_types: ["Dosyanın Açılması"],
      recent: [],
    },
    {
      key: "gelen_evrak",
      label: "Gelen evrak kaydedildi",
      count: 2,
      first_date: "2025-03-24",
      last_date: "2025-03-25",
      uyap_types: ["Gelen Evrak Kaydedilmesi"],
      recent: [
        { date: "2025-03-25", text: "89/1 Haciz İhbarnamesi Cevabı" },
        { date: "bozuk", text: "" },
      ],
    },
    { label: "anahtarsız" },
  ],
  other_actions: [
    { name: "Vekaletname İle Vekil Kaydedildi", count: 1, last_date: "2025-03-27" },
    { count: 3 },
  ],
  asset_queries: {
    kinds: [{ key: "arac", label: "Araç" }],
    people: [
      {
        name: "AYŞE ÖRNEK",
        role: "Borçlu",
        queries: [
          {
            key: "arac",
            label: "Araç",
            count: 3,
            last_date: "2025-07-07",
            result: "YOK",
            result_date: "2025-06-05",
          },
          {
            key: "tapu",
            label: "Tapu (TAKBİS)",
            count: 1,
            last_date: "2025-03-03",
            result: "VAR",
            result_date: "2025-03-03",
          },
          {
            key: "sgk_aktif_4a",
            label: "SGK aktif 4A",
            count: 2,
            last_date: "2025-03-03",
            result: "VAR/YOK",
            result_date: "2025-03-03",
          },
          {
            key: "posta",
            label: "Posta çeki",
            count: 1,
            last_date: "2025-03-04",
            result: "BELKİ",
            result_date: null,
          },
        ],
      },
      {
        name: null,
        role: null,
        queries: [
          {
            key: "tapu",
            label: "Tapu (TAKBİS)",
            count: 1,
            last_date: null,
            result: null,
            result_date: null,
          },
        ],
      },
      { name: "SORGUSUZ", role: "Borçlu", queries: [] },
    ],
  },
  services: [
    {
      barcode: "2700000000001",
      recipient: "BORÇLU VE MÜFLİS AYŞE ÖRNEK",
      method: "Kapalı Tebligat",
      sent_date: "2025-02-03",
      result: "Tebliğ Edildi",
      result_date: "2025-02-10",
    },
    {
      barcode: "2700000000002",
      recipient: "3. Taraf DENEME BANKASI",
      method: "Kapalı Tebligat",
      sent_date: "2025-03-05",
      result: null,
      result_date: "2025-03-12",
    },
    {
      barcode: "2700000000003",
      recipient: null,
      method: null,
      sent_date: "2025-03-06",
      result: null,
      result_date: null,
    },
  ],
};

test("UYAP bilgisi özeti güvenle okunur; bozuk alan atılır, özet yoksa null döner", () => {
  assert.equal(detail.parseBreakdown({ case_id: "c1" }).overview, null);
  assert.equal(detail.parseBreakdown({ case_id: "c1", overview: "bozuk" }).overview, null);
  const overview = detail.parseBreakdown({ case_id: "c1", overview: OVERVIEW }).overview;

  assert.deepEqual(overview.identity, [
    { label: "Türü", value: "İlamsız Takip" },
    { label: "Dosya Durumu", value: "Açık" },
  ]);
  assert.equal(overview.parties.length, 3); // adı olmayan taraf satırı atılır
  assert.deepEqual(overview.activity, {
    entries: 12,
    undated: 0,
    firstDate: "2025-02-01",
    lastDate: "2026-09-30",
    daysSinceLast: 10,
    lastType: "Gelen Evrak Kaydedilmesi",
    lastText: "yazı",
  });
  assert.deepEqual(
    overview.milestones.map((item) => item.key),
    ["acilis", "gelen_evrak"],
  );
  assert.deepEqual(overview.milestones[1].recent, [
    { date: "2025-03-25", text: "89/1 Haciz İhbarnamesi Cevabı" },
  ]);
  assert.deepEqual(overview.otherActions, [
    { name: "Vekaletname İle Vekil Kaydedildi", count: 1, lastDate: "2025-03-27" },
  ]);
  assert.deepEqual(
    overview.people.map((person) => person.name),
    ["AYŞE ÖRNEK", null],
  ); // sorgusu olmayan kişi listelenmez
  assert.equal(overview.people[0].queries[3].result, null); // tanınmayan sonuç "VAR" ya da "YOK" sayılmaz
  assert.equal(overview.services.length, 3);
  // Boş özet de çökmez.
  const empty = detail.parseOverview({});
  assert.deepEqual(
    [empty.complete, empty.parties, empty.people, empty.activity.daysSinceLast],
    [false, [], [], null],
  );
});

test("taraflar rol başlıkları altında toplanır", () => {
  const overview = detail.parseOverview(OVERVIEW);
  assert.deepEqual(
    detail
      .groupParties(overview.parties)
      .map((group) => [group.role, group.members.map((party) => party.name)]),
    [
      ["Alacaklı", ["DENEME ALACAK A.Ş."]],
      ["Borçlu", ["AYŞE ÖRNEK", "ISMAIL DENEMECI"]],
    ],
  );
  assert.deepEqual(
    detail.groupParties([{ role: "", type: "", name: "X", lawyer: "" }])[0].role,
    "Rolü yazılmamış",
  );
});

test("sorgu hücresi kayıtta yazan sonucu ve tarihini gösterir; yazmayan sonuç tahmin edilmez", () => {
  const [car, deed, sgk, post] = detail.parseOverview(OVERVIEW).people[0].queries;
  assert.deepEqual(detail.queryCell(car), {
    text: "YOK · 05.06.2025 · son sorgu 07.07.2025 (sonuç yazılmamış) · 3 sorgu",
    tone: "yok",
  });
  assert.deepEqual(detail.queryCell(deed), { text: "VAR · 03.03.2025", tone: "var" });
  assert.deepEqual(detail.queryCell(sgk), {
    text: "aynı gün VAR ve YOK · 03.03.2025 · 2 sorgu",
    tone: "mixed",
  });
  assert.deepEqual(detail.queryCell(post), { text: "sonuç yazılmamış · 04.03.2025", tone: "none" });
  assert.deepEqual(detail.queryCell(detail.parseOverview(OVERVIEW).people[1].queries[0]), {
    text: "sonuç yazılmamış · tarihi yok",
    tone: "none",
  });
});

test("önemli işlem tarihleri: tek kayıtta tek tarih, çok kayıtta ilk ve son", () => {
  const [opened, incoming] = detail.parseOverview(OVERVIEW).milestones;
  assert.equal(detail.milestoneDates(opened), "01.02.2025");
  assert.equal(detail.milestoneDates(incoming), "24.03.2025 – 25.03.2025");
  assert.equal(
    detail.milestoneDates({ ...incoming, firstDate: null, lastDate: null }),
    "tarihi yok",
  );
});

test("tebligat sonucu yazıyorsa aynen, yazmıyorsa öyle söylenir", () => {
  const services = detail.parseOverview(OVERVIEW).services;
  assert.deepEqual(detail.serviceOutcome(services[0]), {
    text: "Tebliğ Edildi · 10.02.2025",
    known: true,
  });
  assert.deepEqual(detail.serviceOutcome(services[1]), {
    text: "Sonuç kaydı girilmiş (12.03.2025); sonucun ne olduğu kayıtta yazmıyor",
    known: false,
  });
  assert.deepEqual(detail.serviceOutcome(services[2]), { text: "Sonuç kaydı yok", known: false });
  assert.equal(
    detail.servicesHeadline(services),
    "3 tebligat kaydı · sonuç kaydı girilen: 2 · sonucu yazan: 1",
  );
  assert.equal(detail.servicesHeadline([]), "Safahatta tebligat kaydı yok.");
});

// --- Liste ---------------------------------------------------------------------------------------------------------------

const row = (case_id, extra = {}) => ({
  case_id,
  file_no: `2025/${case_id}`,
  court: "Ankara 7. Genel İcra Dairesi",
  kind: "takip",
  ...extra,
});
const FILES = list.parseExecution({
  files: [
    row("a", {
      overview: {
        type: "İlamsız Takip",
        status: "Açık",
        creditors: ["DENEME ALACAK A.Ş."],
        debtors: ["AYŞE ÖRNEK", "ISMAIL DENEMECI", "ÜÇÜNCÜ BORÇLU"],
        party_count: 4,
        last_activity: "2026-09-30",
        days_since_last: 10,
        history_entries: 12,
        positive_queries: ["Araç", 5],
      },
    }),
    row("b", {
      overview: {
        status: "Takipsizlik",
        creditors: [],
        debtors: ["ESKİ BORÇLU"],
        last_activity: "2021-07-01",
        days_since_last: 1927,
      },
    }),
    row("c", {
      uyap: {
        durum: "Kapalı ( 27.06.2025 11:43:11 )",
        complete: true,
        missing: 0,
        checked_at: "2026-10-09T10:00:00Z",
        removed_since: 110,
      },
    }),
    row("d", {
      uyap: { durum: "Açık", complete: true, missing: 0, checked_at: "2026-10-09T10:00:00Z" },
    }),
    row("e"),
  ],
}).files;

test("liste özeti okunur: taraf adları, durum, son işlem; UYAP bilgisi yoksa null", () => {
  assert.deepEqual(FILES[0].overview, {
    type: "İlamsız Takip",
    path: null,
    status: "Açık",
    creditors: ["DENEME ALACAK A.Ş."],
    debtors: ["AYŞE ÖRNEK", "ISMAIL DENEMECI", "ÜÇÜNCÜ BORÇLU"],
    partyCount: 4,
    lastActivity: "2026-09-30",
    daysSinceLast: 10,
    historyEntries: 12,
    positiveQueries: ["Araç"],
  });
  assert.equal(FILES[4].overview, null);
  assert.equal(list.namesLine(FILES[0].overview.debtors), "AYŞE ÖRNEK, ISMAIL DENEMECI +1");
  assert.equal(list.namesLine(["TEK"]), "TEK");
  assert.equal(list.namesLine([]), "");
});

test("dosya durumu önce dosya bilgisinden, yoksa dosya listesinden gelir; bilinmeyen durum açık ya da kapalı sayılmaz", () => {
  assert.deepEqual(
    FILES.map((file) => list.fileStatus(file)),
    ["Açık", "Takipsizlik", "Kapalı", "Açık", null],
  );
  assert.deepEqual(
    FILES.map((file) => list.isOpenFile(file)),
    [true, false, false, true, null],
  );
  assert.deepEqual(
    list.filterFiles(FILES, "", "all", "open").map((file) => file.case_id),
    ["a", "d"],
  );
  assert.deepEqual(
    list.filterFiles(FILES, "", "all", "other").map((file) => file.case_id),
    ["b", "c"],
  ); // durumu bilinmeyen "e" ikisinde de yok
  assert.deepEqual(
    list.filterFiles(FILES, "", "all").map((file) => file.case_id),
    ["a", "b", "c", "d", "e"],
  );
});

test("arama taraf adını ve durumu da tarar", () => {
  assert.deepEqual(
    list.filterFiles(FILES, "ismail", "all").map((file) => file.case_id),
    ["a"],
  );
  assert.deepEqual(
    list.filterFiles(FILES, "ESKİ BORÇLU", "all").map((file) => file.case_id),
    ["b"],
  );
  assert.deepEqual(
    list.filterFiles(FILES, "takipsizlik", "all").map((file) => file.case_id),
    ["b"],
  );
});

test("sıralama: işlem tarihi bilinmeyen dosya 'en uzun süredir işlemsiz' diye öne alınmaz", () => {
  assert.deepEqual(
    list.sortFiles(FILES, "recent").map((file) => file.case_id),
    ["a", "b", "c", "d", "e"],
  );
  assert.deepEqual(
    list.sortFiles(FILES, "idle").map((file) => file.case_id),
    ["b", "a", "c", "d", "e"],
  );
  assert.deepEqual(
    list.sortFiles(FILES, "active").map((file) => file.case_id),
    ["a", "b", "c", "d", "e"],
  );
  assert.deepEqual(
    FILES.map((file) => file.case_id),
    ["a", "b", "c", "d", "e"],
  ); // özgün dizi değişmez
});

test("geçen süre yalnız sayıdır", () => {
  assert.equal(list.daysAgo(0), "bugün");
  assert.equal(list.daysAgo(8), "8 gün önce");
  assert.equal(list.daysAgo(516), "516 gün önce (yaklaşık 1,4 yıl)");
  assert.equal(list.daysAgo(null), "");
});

test("doğrulamadan sonra evrak silindiyse eski 'eksiksiz' kaydı gösterilmez", () => {
  assert.deepEqual(list.verificationLabel(FILES[2].uyap), {
    text: "Son doğrulamadan (09.10.2026) sonra 110 evrak silinmiş; UYAP'tan yeniden aktarın",
    tone: "warn",
  });
  assert.deepEqual(list.verificationLabel(FILES[3].uyap), {
    text: "UYAP'taki evrakların tamamı aktarılmış (09.10.2026)",
    tone: "ok",
  });
});

test("arama Türkçe harf yazımından bağımsızdır: 'ayse' ve 'AYŞE', 'ismail' ve 'ISMAIL' aynı bulunur", () => {
  assert.deepEqual(
    list.filterFiles(FILES, "ayse ornek", "all").map((file) => file.case_id),
    ["a"],
  );
  assert.deepEqual(
    list.filterFiles(FILES, "İSMAİL", "all").map((file) => file.case_id),
    ["a"],
  );
  assert.deepEqual(
    list.filterFiles(FILES, "ucuncu", "all").map((file) => file.case_id),
    ["a"],
  );
});

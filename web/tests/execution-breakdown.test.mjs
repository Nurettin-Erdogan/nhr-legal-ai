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
  new Function("require", "module", "exports", outputText)(
    (name) => (name === "@/lib/auth-api" ? { inMemoryAccessToken: () => null } : require(name)),
    module,
    module.exports,
  );
  return module.exports;
}
const lib = compile("../src/lib/execution-breakdown.ts");

const doc = (id) => ({ id, file_name: `${id}.pdf`, storage_path: `sahip/${id}` });
const SERVER = {
  case_id: "c1",
  file_no: "2025/123",
  court: "Ankara Banka Alacakları İcra Dairesi",
  kind: "takip",
  receipts: [
    {
      document: doc("r1"),
      kind: "tahsilat",
      label: "Tahsilat",
      date: "2025-03-12",
      readable: true,
      amount: "100,00 TL",
      amounts: ["100,00 TL"],
    },
    {
      document: doc("r2"),
      kind: "masraf",
      label: "Masraf",
      date: "2025-03-10",
      readable: true,
      amount: null,
      amounts: ["45,00 TL", "90,00 TL"],
    },
    {
      document: doc("r3"),
      kind: "reddiyat",
      label: "Reddiyat",
      date: null,
      readable: false,
      amount: null,
      amounts: [],
    },
    {
      document: doc("r4"),
      kind: "tahsilat",
      label: "Tahsilat",
      date: "2025-01-02",
      readable: true,
      amount: null,
      amounts: [],
    },
  ],
  replies: {
    envelopes: 3,
    attachments: 5,
    unread: 1,
    items: [
      {
        date: "2025-03-12",
        readable: true,
        documents: [doc("a1")],
        group: "amount",
        sender: "DENEMEBANK T.A.Ş.",
        amounts: ["1.250,75 TL"],
        quotes: ["… 1.250,75 TL üzerine bloke konulmuştur."],
      },
      {
        date: "2025-03-12",
        readable: false,
        documents: [doc("a2")],
        group: "unclear",
        sender: null,
        amounts: [],
        quotes: [],
      },
      {
        date: "2025-03-11",
        readable: true,
        documents: [doc("a3"), doc("a4")],
        group: "negative",
        sender: "Örnek Bankası A.Ş.",
        amounts: [],
        quotes: ["Hak ve alacağı bulunmadığı tespit edilmiştir."],
      },
    ],
    groups: { amount: 1, unclear: 1, negative: 1 },
  },
  labels: {
    receipts: {},
    reply_groups: { amount: "Tutar geçiyor", negative: "“Bulunmamaktadır” türü ifade geçiyor" },
  },
};

test("sunucu yanıtı okunur: makbuzlar, cevaplar ve belgeyi açmak için gerekenler", () => {
  const data = lib.parseBreakdown(SERVER);
  assert.equal(data.fileNo, "2025/123");
  assert.equal(data.receipts.length, 4);
  assert.deepEqual(data.receipts[0].document, {
    id: "r1",
    fileName: "r1.pdf",
    storagePath: "sahip/r1",
  });
  assert.equal(data.replies.items.length, 3);
  assert.deepEqual(
    data.replies.items[2].documents.map((item) => item.id),
    ["a3", "a4"],
  );
  assert.deepEqual(data.replies.groups, { amount: 1, unclear: 1, negative: 1 });
  assert.equal(data.replyGroupLabels.unclear, "Belirleyici ifade bulunamadı"); // sunucu göndermediyse yerel etiket
});

test("bozuk yanıt sayfayı çökertmez; tanınmayan grup okunmadan geçilmeyecek gruba düşer", () => {
  for (const bad of [null, undefined, "x", 5, [], { replies: "x", receipts: {} }]) {
    const data = lib.parseBreakdown(bad);
    assert.deepEqual(data.receipts, []);
    assert.deepEqual(data.replies.items, []);
  }
  const data = lib.parseBreakdown({
    receipts: [{ kind: "tahsilat" }, "x", { document: { id: "" } }],
    replies: {
      items: [
        { documents: [doc("a1")], group: "olumlu", quotes: [5, "", "alıntı"], amounts: "x" },
        { documents: [] },
        7,
      ],
    },
  });
  assert.deepEqual(data.receipts, []);
  assert.equal(data.replies.items.length, 1);
  assert.equal(data.replies.items[0].group, "unclear");
  assert.deepEqual(data.replies.items[0].quotes, ["alıntı"]);
  assert.deepEqual(data.replies.items[0].amounts, []);
  assert.equal(data.replies.items[0].readable, false);
});

test("tek tutar yalnız listede gerçekten tek tutar varsa gösterilir", () => {
  const data = lib.parseBreakdown({
    receipts: [
      {
        document: doc("r1"),
        kind: "masraf",
        readable: true,
        amount: "45,00 TL",
        amounts: ["45,00 TL", "90,00 TL"],
      },
      {
        document: doc("r2"),
        kind: "masraf",
        readable: true,
        amount: "999,00 TL",
        amounts: ["45,00 TL"],
      },
    ],
  });
  assert.equal(data.receipts[0].amount, null);
  assert.equal(data.receipts[1].amount, null); // sunucunun dediği tutar listede yoksa uydurulmaz
});

test("makbuz hücresi: tek tutar, farklı tutarların listesi ya da açık bir okunamadı", () => {
  const { receipts } = lib.parseBreakdown(SERVER);
  assert.equal(lib.receiptCell(receipts[0]), "100,00 TL");
  assert.equal(lib.receiptCell(receipts[1]), "2 farklı tutar: 45,00 TL · 90,00 TL");
  assert.equal(lib.receiptCell(receipts[2]), "Metni okunamadı");
  assert.equal(lib.receiptCell(receipts[3]), "Tutar bulunamadı");
});

test("makbuz sayımı türleri listedeki sırayla ve tek tutarı okunanlarla verir", () => {
  const { receipts } = lib.parseBreakdown(SERVER);
  assert.deepEqual(lib.receiptCounts(receipts), [
    { kind: "tahsilat", label: "Tahsilat", count: 2, single: 1 },
    { kind: "masraf", label: "Masraf", count: 1, single: 0 },
    { kind: "reddiyat", label: "Reddiyat", count: 1, single: 0 },
  ]);
  assert.deepEqual(lib.receiptCounts([]), []);
});

test("cevap başlığı sayıları saklamaz: evrak, ek, ayrı yazı ve okunamayan", () => {
  const { replies } = lib.parseBreakdown(SERVER);
  assert.equal(
    lib.replyHeadline(replies),
    "3 cevap evrakı · 5 ek · 3 ayrı yazı · 1 ekin metni okunamadı",
  );
  assert.equal(
    lib.replyHeadline({ envelopes: 2, attachments: 2, unread: 0, items: [{}, {}], groups: {} }),
    "2 cevap evrakı · 2 ek",
  );
  assert.equal(
    lib.replyHeadline({ envelopes: 0, attachments: 0, unread: 0, items: [], groups: {} }),
    "Bu dosyada haciz ihbarnamesi cevabı yok.",
  );
});

test("cevaplar gruba göre süzülür", () => {
  const { replies } = lib.parseBreakdown(SERVER);
  assert.equal(lib.filterReplies(replies.items, "all").length, 3);
  assert.deepEqual(
    lib.filterReplies(replies.items, "amount").map((item) => item.sender),
    ["DENEMEBANK T.A.Ş."],
  );
  assert.deepEqual(lib.filterReplies(replies.items, "block"), []);
});

test("icra birimi sunucudaki kuralla tanınır", () => {
  for (const court of [
    "Ankara Banka Alacakları İcra Dairesi",
    "(Kapatılan)Ankara 2. İcra Dairesi",
    "ANKARA 7. GENEL İCRA DAİRESİ",
    "Kahramankazan İcra Müdürlüğü",
    "Ankara 13. İcra Hukuk Mahkemesi",
    "İstanbul 3. İcra  Ceza Mahkemesi",
  ])
    assert.equal(lib.isExecutionCourt(court), true, court);
  for (const court of [
    "Ankara 5. Sulh Hukuk Mahkemesi",
    "Ankara Bölge Adliye Mahkemesi 18. Hukuk Dairesi",
    "",
    null,
    undefined,
  ])
    assert.equal(lib.isExecutionCourt(court), false, String(court));
});

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
const { buildSearchRows, groupRows, legalShortcuts, moveSelection, searchable } = compile(
  "../src/lib/global-search.ts",
);

const result = {
  query: "demir",
  cases: [
    {
      id: "c1",
      title: "Demir / Kaya Tahliye Davası",
      case_no: "D-7",
      esas_no: "2025/321",
      court: "Ankara 5. Sulh Hukuk",
      client_name: "Ayşe Demir",
    },
  ],
  clients: [
    {
      id: "m1",
      full_name: "Ayşe Demir",
      client_type: "individual",
      phone: "+90 532 123 45 67",
      email: null,
    },
  ],
  documents: [
    {
      id: "d1",
      file_name: "Demir ihtarname.pdf",
      case_id: "c1",
      uyap_file_no: null,
      uyap_birim: null,
      case_title: "Demir / Kaya Tahliye Davası",
    },
    {
      id: "d2",
      file_name: "demir & oğulları.docx",
      case_id: null,
      uyap_file_no: "2024/15",
      uyap_birim: null,
      case_title: null,
    },
  ],
  tasks: [
    {
      id: "t1",
      title: "Demir dosyası cevap dilekçesi",
      status: "todo",
      due_date: null,
      case_id: null,
      case_title: null,
    },
  ],
};

test("kısa terimde arama yapılmaz, kısayol da gösterilmez", () => {
  assert.equal(searchable(" a "), false);
  assert.equal(searchable("ab"), true);
  assert.deepEqual(legalShortcuts("a"), []);
  assert.deepEqual(buildSearchRows(null, "a"), []);
});

test("her kayıt kendi sayfasını açar; davaya bağlı belge davanın evraklarına gider", () => {
  const rows = buildSearchRows(result, "demir");
  const byKey = Object.fromEntries(rows.map((row) => [row.key, row]));
  assert.equal(byKey["case-c1"].href, "/dashboard/cases/c1");
  assert.equal(byKey["case-c1"].detail, "2025/321 · Ankara 5. Sulh Hukuk · Ayşe Demir");
  assert.equal(byKey["client-m1"].href, "/dashboard/clients?q=Ay%C5%9Fe%20Demir");
  assert.equal(byKey["client-m1"].detail, "Gerçek kişi · +90 532 123 45 67");
  assert.equal(byKey["document-d1"].href, "/dashboard/cases/c1?tab=evraklar");
  assert.equal(
    byKey["document-d2"].href,
    "/dashboard/files?q=demir%20%26%20o%C4%9Fullar%C4%B1.docx",
  );
  assert.equal(byKey["document-d2"].detail, "Davaya bağlı değil · 2024/15");
  assert.equal(byKey["task-t1"].href, "/dashboard/tasks");
  assert.equal(byKey["task-t1"].detail, "Bekliyor");
});

test("kayıt bulunmasa da aynı terim hukuk kaynaklarında aranabilir", () => {
  const rows = buildSearchRows(
    { query: "kıdem tazminatı", cases: [], clients: [], documents: [], tasks: [] },
    "kıdem tazminatı",
  );
  assert.deepEqual(
    rows.map((row) => row.href),
    [
      "/dashboard/case-law?q=k%C4%B1dem%20tazminat%C4%B1",
      "/dashboard/legislation?q=k%C4%B1dem%20tazminat%C4%B1",
      "/dashboard/ai?q=k%C4%B1dem%20tazminat%C4%B1",
    ],
  );
});

test("satırlar grup başlıklarıyla ve sunucu sırasıyla gösterilir", () => {
  const groups = groupRows(buildSearchRows(result, "demir"));
  assert.deepEqual(
    groups.map((group) => [group.group, group.rows.length]),
    [
      ["Davalar", 1],
      ["Müvekkiller", 1],
      ["Belgeler", 2],
      ["Görevler", 1],
      ["Hukuk kaynaklarında ara", 3],
    ],
  );
});

test("ok tuşları listede döner", () => {
  assert.equal(moveSelection(-1, 1, 3), 0);
  assert.equal(moveSelection(-1, -1, 3), 2);
  assert.equal(moveSelection(2, 1, 3), 0);
  assert.equal(moveSelection(0, -1, 3), 2);
  assert.equal(moveSelection(0, 1, 0), -1);
});

test("içtihat kısayolu yalnız yöneticiye gösterilir", () => {
  const empty = { query: "kira", cases: [], clients: [], documents: [], tasks: [] };
  const hrefs = (admin) => buildSearchRows(empty, "kira", admin).map((row) => row.href);
  assert.ok(hrefs(true).some((href) => href.startsWith("/dashboard/case-law")));
  assert.ok(!hrefs(false).some((href) => href.startsWith("/dashboard/case-law")));
  assert.ok(
    hrefs(false).some((href) => href.startsWith("/dashboard/legislation")),
    "mevzuat kısayolu kalır",
  );
});

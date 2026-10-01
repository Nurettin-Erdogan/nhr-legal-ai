// ============================================================================
// Mevzuat ETL betiği — Bedesten'den kanun listesi çekip veritabanına yazar.
// ----------------------------------------------------------------------------
// Kullanım:  bun scripts/load-mevzuat.ts [--limit 25] [--offset 0] [--mode full|update]
// - full:   tüm çekilen kanunları upsert eder (mevcut kayıtlar güncellenir)
// - update: yalnız veritabanında olmayan yeni kanunları ekler
// Yalnızca service_role ile çalışır (exec ortamında SUPABASE_SERVICE_ROLE_KEY set).
// ============================================================================

import { createClient } from "@supabase/supabase-js";
import {
  searchDocuments,
  getDocumentContent,
  getMaddeTree,
  htmlToPlain,
} from "../src/lib/mevzuat.server";

const args = process.argv.slice(2);
const parseArg = (flag: string, def: string) => {
  const i = args.indexOf(flag);
  return i >= 0 ? args[i + 1] : def;
};
const limit = Math.min(Number(parseArg("--limit", "25")), 100);
const offset = Number(parseArg("--offset", "0"));
const mode = parseArg("--mode", "full");

const key = process.env["SUPABASE_SERVICE_ROLE_KEY"];
const url = process.env["SUPABASE_URL"];
if (!key || !url) {
  console.error("SUPABASE_SERVICE_ROLE_KEY veya SUPABASE_URL eksik.");
  process.exit(1);
}

const supabase = createClient(url, key, {
  auth: { persistSession: false },
  global: {
    fetch: (input, init) => {
      const h = new Headers(init?.headers);
      if (key.startsWith("sb_") && h.get("Authorization") === `Bearer ${key}`)
        h.delete("Authorization");
      h.set("apikey", key);
      return fetch(input, { ...init, headers: h });
    },
  },
});

async function main() {
  console.log(`Mevzuat ETL başlıyor: limit=${limit} offset=${offset} mode=${mode}`);
  const result = await searchDocuments({
    page: Math.floor(offset / limit) + 1,
    pageSize: limit,
    mevzuatTurList: ["KANUN"],
  });
  if (result.error) {
    console.error("searchDocuments hatası:", result.error);
    process.exit(1);
  }
  console.log(`Bulunan: ${result.documents.length} kanun (toplam: ${result.total})`);

  let inserted = 0,
    skipped = 0,
    failed = 0;

  for (const doc of result.documents) {
    if (!doc.mevzuatId) {
      skipped++;
      continue;
    }
    try {
      // mevcut mu?
      const { data: existing } = await supabase
        .from("mevzuat")
        .select("id")
        .eq("mevzuat_id", doc.mevzuatId)
        .maybeSingle();
      if (mode === "update" && existing) {
        skipped++;
        console.log(`  [SKIP] ${doc.mevzuatAdi}`);
        continue;
      }

      const [tree, content] = await Promise.all([
        getMaddeTree(doc.mevzuatId).catch(() => []),
        getDocumentContent(doc.mevzuatId).catch(() => ({ content: "", mimeType: "text/html" })),
      ]);
      const plain = content.content ? htmlToPlain(content.content) : null;

      const payload = {
        mevzuat_id: doc.mevzuatId,
        mevzuat_no: doc.mevzuatNo ?? null,
        adi: doc.mevzuatAdi,
        tertip: doc.mevzuatTertip ?? null,
        tur: doc.mevzuatTur?.name ?? null,
        resmi_gazete_tarihi: doc.resmiGazeteTarihi ?? null,
        resmi_gazete_sayisi: doc.resmiGazeteSayisi ?? null,
        kaynak_url: doc.url ?? null,
        madde_listesi: tree,
        tam_metin: plain,
        metadata: { source: "bedesten.adalet.gov.tr" },
      };

      const { error } = await supabase.from("mevzuat").upsert(payload, {
        onConflict: "mevzuat_id",
      });
      if (error) {
        throw new Error(error.message);
      }
      inserted++;
      console.log(`  [OK] ${doc.mevzuatAdi} (${plain ? plain.length : 0} karakter)`);
    } catch (e) {
      failed++;
      console.error(`  [FAIL] ${doc.mevzuatAdi}:`, e instanceof Error ? e.message : e);
    }
    // Resmî servisi yormamak için kısa bekleme
    await new Promise((r) => setTimeout(r, 400));
  }

  const { count } = await supabase.from("mevzuat").select("*", { count: "exact", head: true });

  console.log(`\nBitti. Eklendi: ${inserted}, Atlandı: ${skipped}, Hata: ${failed}`);
  console.log(`Veritabanındaki toplam mevzuat: ${count ?? 0}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

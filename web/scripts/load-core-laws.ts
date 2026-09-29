// ============================================================================
// Temel kanunların ETL'si — vatandaş sohbeti için en değerli kanunları yükler.
// ----------------------------------------------------------------------------
// Kullanım:  bun scripts/load-core-laws.ts
// Resmî servise saygılı: istekler seri, aralarında 2 sn bekleme, 429'da uzun
// bekleme + retry. Arka planda yavaşça çalıştırılabilir (nohup).
// ============================================================================

import { createClient } from "@supabase/supabase-js";
import {
  searchDocuments,
  getDocumentContent,
  getMaddeTree,
  htmlToPlain,
} from "../src/lib/mevzuat.server";

// Vatandaşların en çok sorduğu hukuk konularını kapsayan temel kanunlar.
const CORE_LAWS = [
  "TÜRK MEDENİ KANUNU",
  "TÜRK BORÇLAR KANUNU",
  "TÜRK CEZA KANUNU",
  "CEZA MUHAKEMESİ KANUNU",
  "İŞ KANUNU",
  "TÜRK TİCARET KANUNU",
  "VERGİ USUL KANUNU",
  "GELİR VERGİSİ KANUNU",
  "KAT MÜLKİYETİ KANUNU",
  "İCRA VE İFLAS KANUNU",
  "HUKUK MUHAKEMELERİ KANUNU",
  "TÜRK VATANDAŞLIĞI KANUNU",
  "SOSYAL SİGORTALAR VE GENEL SAĞLIK SİGORTASI KANUNU",
  "TÜKETİCİNİN KORUNMASI HAKKINDA KANUN",
  "İŞ SAĞLIĞI VE GÜVENLİĞİ KANUNU",
];

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

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** 429'a takılırsa bekleyip yeniden dener. */
async function retry<T>(fn: () => Promise<T>, retries = 5): Promise<T> {
  for (let i = 0; i < retries; i++) {
    try {
      return await fn();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes("429")) {
        const wait = 12000 + i * 8000;
        console.log(`   [429] ${wait / 1000}s bekleniyor...`);
        await sleep(wait);
        continue;
      }
      throw e;
    }
  }
  throw new Error("429 sonrası retry tükendi");
}

async function main() {
  console.log("Temel kanun ETL başlıyor (yavaş ritim)...");
  let inserted = 0,
    failed = 0;

  for (const lawName of CORE_LAWS) {
    try {
      console.log(`\n>> Aranıyor: ${lawName}`);
      const result = await retry(() =>
        searchDocuments({ mevzuatAdi: lawName, page: 1, pageSize: 20 }),
      );
      if (result.error || result.documents.length === 0) {
        console.log(`   Sonuç yok.`);
        continue;
      }

      const doc =
        result.documents.find(
          (d) => d.mevzuatTur?.name === "KANUN" && d.mevzuatAdi === lawName,
        ) ??
        result.documents.find((d) => d.mevzuatTur?.name === "KANUN") ??
        result.documents[0];

      if (!doc.mevzuatId) continue;

// Seri çekim: önce ağaç, sonra içerik (paralel değil).
      const tree = await retry(() => getMaddeTree(doc.mevzuatId).catch(() => []));
      await sleep(2500);
      // Not: .catch ile hatayı yutmuyoruz; 429'da retry yeniden denesin.
      const content = await retry(() => getDocumentContent(doc.mevzuatId));
      const plain = content.content ? htmlToPlain(content.content) : null;
      if (!plain) {
        console.log(`   >> ${doc.mevzuatAdi} (id: ${doc.mevzuatId}) — içerik yok, atlandı`);
        failed++;
        await sleep(2500);
        continue;
      }
      console.log(`   >> ${doc.mevzuatAdi} (id: ${doc.mevzuatId}) — ${plain.length} karakter`);

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
        metadata: { source: "bedesten.adalet.gov.tr", core: true },
      };
      const { error } = await supabase.from("mevzuat").upsert(payload, {
        onConflict: "mevzuat_id",
      });
      if (error) throw new Error(error.message);
      inserted++;
    } catch (e) {
      failed++;
      console.error(`   [FAIL] ${lawName}:`, e instanceof Error ? e.message : e);
    }
    await sleep(2500);
  }

  const { count } = await supabase.from("mevzuat").select("*", { count: "exact", head: true });
  console.log(`\nBitti. Eklendi: ${inserted}, Hata: ${failed}`);
  console.log(`Veritabanındaki toplam mevzuat: ${count ?? 0}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
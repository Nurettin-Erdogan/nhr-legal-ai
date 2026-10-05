import { supabase } from "@/integrations/supabase/client";
import {
  extractTextSample,
  extOf,
  isAllowedFile,
  MAX_FILE_BYTES,
  parseUyapMeta,
  readArchive,
  storagePathFor,
  type ArchiveEntry,
} from "@/lib/uyap";

export interface ImportResult {
  found: number;
  inserted: number;
  skipped: number;
  failed: number;
  errors: string[];
}

const ARCHIVE_EXT = new Set(["zip", "eyp"]);

async function sha256(data: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new Uint8Array(data));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** Tarayıcıya bırakılan dosyaları (tek belge veya UYAP arşivi) tek tek belgelere çevirir. */
export async function expandDroppedFiles(files: File[]): Promise<ArchiveEntry[]> {
  const entries: ArchiveEntry[] = [];
  for (const file of files) {
    const ext = extOf(file.name);
    if (ARCHIVE_EXT.has(ext)) {
      try {
        entries.push(...(await readArchive(file)));
        continue;
      } catch (error) {
        if (ext === "zip" || file.size > MAX_FILE_BYTES)
          throw error;
        // Bazı .eyp dosyaları düz belgedir; yalnız ZIP imzası olmayanları tek belge say.
        const signature = new Uint8Array(await file.slice(0, 4).arrayBuffer());
        if (signature[0] === 0x50 && signature[1] === 0x4b) throw error;
      }
    }
    if (!isAllowedFile(file.name)) continue;
    if (file.size > MAX_FILE_BYTES) continue;
    entries.push({ name: file.name, data: new Uint8Array(await file.arrayBuffer()) });
  }
  return entries;
}

/**
 * Belgeleri kullanıcının özel deposuna yükler ve case_documents kaydını oluşturur.
 * Aynı dosyadaki aynı içerik daha önce aktarılmışsa atlanır (idempotent).
 */
export async function importEntries(
  userId: string,
  entries: ArchiveEntry[],
  opts: { source?: string; syncRunId?: string | null; onProgress?: (pct: number) => void } = {},
): Promise<ImportResult> {
  const source = opts.source ?? "uyap";
  let inserted = 0;
  let skipped = 0;
  let failed = 0;
  const errors: string[] = [];

  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i]!;
    const fileName = entry.name.split("/").pop()!;
    try {
      const sample = await extractTextSample(entry.name, entry.data);
      const meta = parseUyapMeta(entry.name, sample);
      const path = storagePathFor(userId, entry.name);

      let duplicateQuery = supabase
        .from("case_documents")
        .select("id,storage_path")
        .eq("owner_id", userId)
        .eq("file_name", fileName)
        .eq("source", source)
        .order("created_at", { ascending: false })
        .order("id", { ascending: false });
      duplicateQuery = meta.uyap_file_no
        ? duplicateQuery.eq("uyap_file_no", meta.uyap_file_no)
        : duplicateQuery.is("uyap_file_no", null);
      let incomingHash = "";
      let duplicate = false;
      for (let offset = 0; !duplicate; offset += 100) {
        const { data: candidates, error: lookupError } = await duplicateQuery.range(offset, offset + 99);
        if (lookupError) throw lookupError;
        if (candidates?.length && !incomingHash) incomingHash = await sha256(entry.data);
        for (const candidate of candidates ?? []) {
          if (!candidate.storage_path) throw new Error("Önceki belgenin depolama yolu eksik");
          const { data: existing, error: readError } = await supabase.storage
            .from("case-files")
            .download(candidate.storage_path);
          if (readError || !existing) throw new Error("Önceki belge karşılaştırma için okunamadı");
          const existingBytes = new Uint8Array(await existing.arrayBuffer());
          // Arşiv dosyalarında güvenilir kalıcı evrak kimliği yok; yalnız TAM bayt eşitliği
          // atlanabilir. Kısa metin örneği eşit olsa bile farklı belge/sürüm olabilir.
          if ((await sha256(existingBytes)) === incomingHash) {
            duplicate = true;
            break;
          }
        }
        if (!candidates || candidates.length < 100) break;
      }
      if (duplicate) {
        skipped++;
        continue;
      }

      const blob = new Blob([new Uint8Array(entry.data)], { type: "application/octet-stream" });
      const { error: upErr } = await supabase.storage
        .from("case-files")
        .upload(path, blob, { upsert: false });
      if (upErr) throw new Error(`Depoya yükleme başarısız: ${upErr.message}`);

      const { error: dbErr } = await supabase.from("case_documents").insert({
        owner_id: userId,
        file_name: fileName,
        storage_path: path,
        size_bytes: entry.data.length,
        source,
        content_excerpt: sample ? sample.slice(0, 1500) : null,
        sync_run_id: opts.syncRunId ?? null,
        ...meta,
      });
      if (dbErr) {
        await supabase.storage.from("case-files").remove([path]);
        throw new Error(`Belge kaydı başarısız: ${dbErr.message}`);
      } else {
        inserted++;
      }
    } catch (error) {
      failed++;
      if (errors.length < 5) errors.push(`${fileName}: ${error instanceof Error ? error.message : "Bilinmeyen hata"}`);
    } finally {
      opts.onProgress?.(((i + 1) / entries.length) * 100);
    }
  }

  return { found: entries.length, inserted, skipped, failed, errors };
}

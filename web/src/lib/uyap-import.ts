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
}

const ARCHIVE_EXT = new Set(["zip", "eyp"]);

/** Tarayıcıya bırakılan dosyaları (tek belge veya UYAP arşivi) tek tek belgelere çevirir. */
export async function expandDroppedFiles(files: File[]): Promise<ArchiveEntry[]> {
  const entries: ArchiveEntry[] = [];
  for (const file of files) {
    const ext = extOf(file.name);
    if (ARCHIVE_EXT.has(ext)) {
      try {
        entries.push(...(await readArchive(file)));
        continue;
      } catch {
        // .eyp bazen düz belge olabilir; aşağıdaki tek dosya akışına düşer
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
 * Aynı isimli belge daha önce aktarılmışsa atlanır (idempotent).
 */
export async function importEntries(
  userId: string,
  entries: ArchiveEntry[],
  opts: { source?: string; syncRunId?: string | null; onProgress?: (pct: number) => void } = {},
): Promise<ImportResult> {
  const source = opts.source ?? "uyap";
  let inserted = 0;
  let skipped = 0;

  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i]!;
    const fileName = entry.name.split("/").pop()!;
    try {
      const sample = await extractTextSample(entry.name, entry.data);
      const meta = parseUyapMeta(entry.name, sample);
      const path = storagePathFor(userId, entry.name);

      const { data: dup } = await supabase
        .from("case_documents")
        .select("id")
        .eq("owner_id", userId)
        .eq("file_name", fileName)
        .eq("source", source)
        .limit(1);
      if (dup && dup.length) {
        skipped++;
        continue;
      }

      const blob = new Blob([new Uint8Array(entry.data)], { type: "application/octet-stream" });
      const { error: upErr } = await supabase.storage
        .from("case-files")
        .upload(path, blob, { upsert: false });
      if (upErr) {
        skipped++;
        continue;
      }

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
        skipped++;
      } else {
        inserted++;
      }
    } catch {
      skipped++;
    } finally {
      opts.onProgress?.(((i + 1) / entries.length) * 100);
    }
  }

  return { found: entries.length, inserted, skipped };
}

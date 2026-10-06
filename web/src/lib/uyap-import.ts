import { importUyapDocument } from "@/lib/office-api";
import { extOf, isAllowedFile, MAX_FILE_BYTES, readArchive, type ArchiveEntry } from "@/lib/uyap";

export interface ImportResult {
  found: number;
  inserted: number;
  skipped: number;
  failed: number;
  errors: string[];
}

const ARCHIVE_EXT = new Set(["zip", "eyp"]);

/** Never silently drop an unsupported/empty/oversized member: report it in the result. */
export async function expandDroppedFiles(files: File[]): Promise<ArchiveEntry[]> {
  const entries: ArchiveEntry[] = [];
  for (const file of files) {
    const ext = extOf(file.name);
    if (ARCHIVE_EXT.has(ext)) {
      try {
        entries.push(...(await readArchive(file)));
        continue;
      } catch (error) {
        if (ext === "zip" || file.size > MAX_FILE_BYTES) throw error;
        const signature = new Uint8Array(await file.slice(0, 4).arrayBuffer());
        if (signature[0] === 0x50 && signature[1] === 0x4b) throw error;
      }
    }
    const error = !isAllowedFile(file.name) ? "Desteklenmeyen dosya türü"
      : file.size > MAX_FILE_BYTES ? "Dosya 50 MB sınırını aşıyor"
      : !file.size ? "Boş dosya" : undefined;
    entries.push({ name: file.name, data: error ? new Uint8Array() : new Uint8Array(await file.arrayBuffer()), ...(error ? { error } : {}) });
  }
  return entries;
}

/** Server-authenticated, checksum-verified, atomic import; no client-side race window. */
export async function importEntries(
  _userId: string,
  entries: ArchiveEntry[],
  opts: { source?: string; syncRunId?: string | null; onProgress?: (pct: number) => void } = {},
): Promise<ImportResult> {
  let inserted = 0, skipped = 0, failed = 0;
  const errors: string[] = [];
  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i]!;
    try {
      if (entry.error) throw new Error(entry.error);
      if (!entry.data.length || entry.data.length > MAX_FILE_BYTES) throw new Error("Boş veya çok büyük dosya");
      const response = await importUyapDocument(entry.name, entry.data, opts.syncRunId);
      if (response.duplicate) skipped++;
      else inserted++;
    } catch (error) {
      failed++;
      errors.push(`${entry.name}: ${error instanceof Error ? error.message : "Bilinmeyen hata"}`);
    } finally {
      opts.onProgress?.(((i + 1) / entries.length) * 100);
    }
  }
  return { found: entries.length, inserted, skipped, failed, errors };
}

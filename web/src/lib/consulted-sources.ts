/** Cevapta alıntılanmayan ama incelenen doğrulanmış kaynaklar (API: `consulted_sources`). */
export interface ConsultedSource {
  marker: string;
  reference: string;
  source_url: string | null;
  excerpt: string | null;
  /** Yalnız "official" (resmî) ya da "user_document" (kullanıcının kendi belgesi) olabilir. */
  verification: "official" | "user_document";
}

export const MAX_CONSULTED_SOURCES = 8;
const MAX_EXCERPT_CHARS = 500;

/**
 * Savunmacı ayrıştırma: API doğrulanmamış (üçüncü taraf) bir kaynağı yanlışlıkla gönderse bile
 * arayüz onu "incelenen kaynak" diye göstermez. Bozuk girdiler sessizce atılır, uydurulmaz.
 */
export function parseConsultedSources(value: unknown): ConsultedSource[] {
  if (!Array.isArray(value)) return [];
  const listed: ConsultedSource[] = [];
  const seen = new Set<string>();
  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const entry = item as Record<string, unknown>;
    const verification = entry.verification;
    if (verification !== "official" && verification !== "user_document") continue;
    if (typeof entry.marker !== "string" || typeof entry.reference !== "string") continue;
    const reference = entry.reference.trim();
    if (!reference) continue;
    const key = typeof entry.source_id === "string" ? entry.source_id : reference;
    if (seen.has(key)) continue;
    seen.add(key);
    const excerpt = typeof entry.excerpt === "string" ? entry.excerpt.trim() : "";
    listed.push({
      marker: entry.marker,
      reference,
      source_url:
        typeof entry.source_url === "string" && /^https?:\/\//i.test(entry.source_url)
          ? entry.source_url
          : null,
      excerpt: excerpt ? excerpt.slice(0, MAX_EXCERPT_CHARS) : null,
      verification,
    });
    if (listed.length >= MAX_CONSULTED_SOURCES) break;
  }
  return listed;
}

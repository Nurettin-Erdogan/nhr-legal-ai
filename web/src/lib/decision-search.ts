/**
 * Karar/mevzuat arama sonuç listesi için mantık (arayüzden bağımsız, test edilebilir).
 *
 * Sonuçlar `/api/legal/search`tan gelir. Doğrulama durumu her sonuçta taşınır: üçüncü taraf (`third_party`) kayıtlar aranır ve
 * atıf yapılabilir ama resmî diye sunulmaz; durumu bilinmeyen (`unknown`) sonuç asla "resmî" gösterilmez.
 */

export type Verification = "official" | "third_party" | "unknown";

export interface SearchHit {
  id: string;
  sourceType: string;
  title: string;
  sourceUrl: string | null;
  authority: string | null;
  courtName: string | null;
  chamber: string | null;
  docketNo: string | null;
  decisionNo: string | null;
  decisionDate: string | null;
  lawName: string | null;
  lawNo: string | null;
  articleNo: string | null;
  articleTitle: string | null;
  versionDate: string | null;
  excerpt: string;
  rank: number;
  verification: Verification;
}

export interface SearchPage {
  query: string;
  total: number;
  /** true: konu geniş, eşleşenlerin yalnız bir bölümü tarandı; `total` "en az" sayıdır, liste eksik olabilir. */
  partial: boolean;
  limit: number;
  offset: number;
  hits: SearchHit[];
}

const text = (value: unknown, max = 4000): string | null =>
  typeof value === "string" && value.trim()
    ? value.replace(/\s+/g, " ").trim().slice(0, max)
    : null;

export const isHttpUrl = (value: string | null): value is string =>
  !!value && /^https?:\/\//i.test(value);

/** Sunucu yanıtını savunmacı biçimde ayrıştırır: kimliksiz ya da başlıksız satırlar atılır; bilinmeyen doğrulama "unknown" olur. */
export function parseSearchPage(raw: unknown): SearchPage | null {
  if (!raw || typeof raw !== "object") return null;
  const source = raw as Record<string, unknown>;
  const rows = Array.isArray(source.results) ? source.results : [];
  const hits: SearchHit[] = [];
  for (const row of rows.slice(0, 200)) {
    if (!row || typeof row !== "object") continue;
    const entry = row as Record<string, unknown>;
    const id = typeof entry.id === "string" ? entry.id : "";
    const title = text(entry.title, 400);
    if (!id || !title) continue;
    const verification: Verification =
      entry.verification === "official" || entry.verification === "third_party"
        ? entry.verification
        : "unknown";
    hits.push({
      id,
      sourceType: text(entry.source_type, 40) ?? "other",
      title,
      sourceUrl: text(entry.source_url, 600),
      authority: text(entry.authority, 120),
      courtName: text(entry.court_name, 160),
      chamber: text(entry.chamber, 160),
      docketNo: text(entry.docket_no, 60),
      decisionNo: text(entry.decision_no, 60),
      decisionDate: text(entry.decision_date, 10),
      lawName: text(entry.law_name, 200),
      lawNo: text(entry.law_no, 20),
      articleNo: text(entry.article_no, 20),
      articleTitle: text(entry.article_title, 200),
      versionDate: text(entry.version_date, 10),
      excerpt: text(entry.excerpt, 1500) ?? "",
      rank: typeof entry.rank === "number" && Number.isFinite(entry.rank) ? entry.rank : 0,
      verification,
    });
  }
  const count = (value: unknown, fallback: number) =>
    typeof value === "number" && Number.isFinite(value) && value >= 0
      ? Math.floor(value)
      : fallback;
  return {
    query: text(source.query, 300) ?? "",
    total: count(source.total, hits.length),
    partial: source.partial === true,
    limit: count(source.limit, hits.length),
    offset: count(source.offset, 0),
    hits,
  };
}

const trDate = (iso: string | null): string => {
  const match = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  return match ? `${match[3]}.${match[2]}.${match[1]}` : "";
};

/** Atıf satırı: karar için "Yargıtay 14. Hukuk Dairesi, E. 2013/14854, K. 2013/15301, T. 09.12.2013"; mevzuat için "<kanun> m. <madde>". */
export function citationOf(hit: SearchHit): string {
  if (hit.sourceType === "legislation") {
    const law = [hit.lawName, hit.lawNo ? `(${hit.lawNo} sayılı)` : null].filter(Boolean).join(" ");
    const article = hit.articleNo ? `m. ${hit.articleNo}` : null;
    const joined = [law, article].filter(Boolean).join(" ");
    return joined || hit.title;
  }
  const court = [hit.courtName ?? hit.authority, hit.chamber].filter(Boolean).join(" ");
  const parts = [
    court,
    hit.docketNo ? `E. ${hit.docketNo}` : null,
    hit.decisionNo ? `K. ${hit.decisionNo}` : null,
    hit.decisionDate ? `T. ${trDate(hit.decisionDate)}` : null,
  ];
  const cited = parts.filter(Boolean).join(", ");
  return cited || hit.title;
}

export const yearOf = (hit: SearchHit): number | null => {
  const iso = hit.decisionDate ?? hit.versionDate;
  const year = iso ? Number(iso.slice(0, 4)) : NaN;
  return Number.isInteger(year) && year > 1800 ? year : null;
};

/**
 * Kart rozeti (kural: `@/lib/source-label`, AGENTS.md 2026-10-15). Resmî metinle karşılaştırılmış kayıt "Resmî metin ✓";
 * karşılaştırılmamış ya da durumu bilinmeyen kayıt olumsuz ibare olmadan kaynak adıyla gösterilir ve ✓ almaz.
 */
export function verificationBadge(
  verification: Verification,
  sourceUrl?: string | null,
  courtName?: string | null,
): { label: string; tone: "ok" | "neutral" } {
  if (verification === "official") return { label: "Resmî metin ✓", tone: "ok" };
  const url = (sourceUrl ?? "").trim();
  const court = (courtName ?? "").toLocaleLowerCase("tr-TR");
  if (/^https:\/\/karararama\.yargitay\.gov\.tr\//i.test(url) || court.includes("yargıtay"))
    return { label: "Yargıtay kararı", tone: "neutral" };
  if (/^https:\/\/karararama\.danistay\.gov\.tr\//i.test(url) || court.includes("danıştay"))
    return { label: "Danıştay kararı", tone: "neutral" };
  return { label: "Karar", tone: "neutral" };
}

export const sourceTypeLabel = (type: string): string =>
  type === "court_decision" ? "Karar" : type === "legislation" ? "Mevzuat" : "Diğer";

export interface Filters {
  authority: string;
  sourceType: string;
  year: string;
  onlyOfficial: boolean;
  sort: "relevance" | "newest" | "official_first";
}

export const DEFAULT_FILTERS: Filters = {
  authority: "",
  sourceType: "",
  year: "",
  onlyOfficial: false,
  sort: "relevance",
};

const dateKey = (hit: SearchHit) => hit.decisionDate ?? hit.versionDate ?? "";

/** Süzer ve sıralar; sıralama kararlıdır (eşitlikte sunucunun ilgi sırası korunur). */
export function filterAndSort(hits: SearchHit[], filters: Filters): SearchHit[] {
  const kept = hits
    .map((hit, index) => ({ hit, index }))
    .filter(({ hit }) => {
      if (filters.onlyOfficial && hit.verification !== "official") return false;
      if (filters.authority && (hit.authority ?? "") !== filters.authority) return false;
      if (filters.sourceType && hit.sourceType !== filters.sourceType) return false;
      if (filters.year && String(yearOf(hit) ?? "") !== filters.year) return false;
      return true;
    });
  const rankOf = (hit: SearchHit) => (hit.verification === "official" ? 0 : 1);
  kept.sort((a, b) => {
    if (filters.sort === "newest") {
      const diff = dateKey(b.hit).localeCompare(dateKey(a.hit));
      if (diff) return diff;
    } else if (filters.sort === "official_first") {
      const diff = rankOf(a.hit) - rankOf(b.hit);
      if (diff) return diff;
    }
    return a.index - b.index;
  });
  return kept.map(({ hit }) => hit);
}

export interface Facets {
  authorities: { value: string; count: number }[];
  years: { value: string; count: number }[];
  types: { value: string; count: number }[];
  unverified: number;
}

const tally = (values: (string | null)[]) => {
  const counts = new Map<string, number>();
  for (const value of values) if (value) counts.set(value, (counts.get(value) ?? 0) + 1);
  return counts;
};

/** Süzgeç seçenekleri: yüklenmiş sonuçlardaki mercii, yıl ve tür değerleri (sayılarıyla). */
export function facetsOf(hits: SearchHit[]): Facets {
  const sorted = (counts: Map<string, number>, by: "count" | "desc") =>
    [...counts.entries()]
      .sort((a, b) =>
        by === "desc" ? b[0].localeCompare(a[0]) : b[1] - a[1] || a[0].localeCompare(b[0], "tr"),
      )
      .map(([value, count]) => ({ value, count }));
  return {
    authorities: sorted(tally(hits.map((hit) => hit.authority)), "count"),
    years: sorted(tally(hits.map((hit) => (yearOf(hit) ? String(yearOf(hit)) : null))), "desc"),
    types: sorted(tally(hits.map((hit) => hit.sourceType)), "count"),
    unverified: hits.filter((hit) => hit.verification !== "official").length,
  };
}

export interface Segment {
  text: string;
  match: boolean;
}

const WORD = /[0-9A-Za-zÇĞİÖŞÜçğıöşüâîûÂÎÛ]+/g;
const STOP = new Set([
  "ve",
  "veya",
  "ile",
  "için",
  "bir",
  "bu",
  "şu",
  "olan",
  "gibi",
  "kadar",
  "daha",
  "mı",
  "mi",
  "mu",
  "mü",
]);

/** Sorgudaki anlamlı sözcükleri (kök biçimiyle: son 3 harf atılır) metinde işaretler. HTML üretilmez; parçalar metin olarak basılır. */
export function highlightSegments(content: string, query: string): Segment[] {
  const stems = [
    ...new Set(
      (query.toLocaleLowerCase("tr").match(WORD) ?? [])
        .filter((word) => word.length >= 3 && !STOP.has(word))
        .map((word) => (word.length >= 6 ? word.slice(0, word.length - 3) : word)),
    ),
  ];
  if (!content || !stems.length) return [{ text: content, match: false }];
  const lower = content.toLocaleLowerCase("tr");
  if (lower.length !== content.length) return [{ text: content, match: false }];
  const ranges: [number, number][] = [];
  for (const word of lower.matchAll(WORD)) {
    const start = word.index ?? 0;
    if (stems.some((stem) => word[0].startsWith(stem)))
      ranges.push([start, start + word[0].length]);
  }
  if (!ranges.length) return [{ text: content, match: false }];
  const segments: Segment[] = [];
  let cursor = 0;
  for (const [start, end] of ranges) {
    if (start > cursor) segments.push({ text: content.slice(cursor, start), match: false });
    segments.push({ text: content.slice(start, end), match: true });
    cursor = end;
  }
  if (cursor < content.length) segments.push({ text: content.slice(cursor), match: false });
  return segments;
}

const BASE = (import.meta.env?.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export class SearchError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
  }
}

export type SearchMode = "keyword" | "narrative";

/** Kelime araması en az 2, olay anlatımı en az 10 karakter ister (sunucuyla aynı). */
export const MIN_QUERY_LENGTH: Record<SearchMode, number> = { keyword: 2, narrative: 10 };

/**
 * `keyword`: `/api/legal/search` (sözcük araması, tüm sonuçları sayar). `narrative`: `/api/legal/semantic` (olayı anlat; sohbet hattının
 * hibrit getirmesi, en iyi ~60 kaynak). Zaman aşımı ve sunucu hataları anlaşılır Türkçe mesaja çevrilir.
 */
export async function searchDecisions(
  query: string,
  options: { limit?: number; offset?: number; mode?: SearchMode; signal?: AbortSignal } = {},
): Promise<SearchPage> {
  const mode = options.mode ?? "keyword";
  const params = new URLSearchParams({
    q: query.trim(),
    limit: String(options.limit ?? 10),
    offset: String(options.offset ?? 0),
  });
  const path = mode === "narrative" ? "/api/legal/semantic" : "/api/legal/search";
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}?${params}`, {
      credentials: "include",
      signal: options.signal,
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw new SearchError("Hukuk arama servisine ulaşılamadı.");
  }
  if (!response.ok) {
    if (response.status === 504)
      throw new SearchError(
        "Arama zaman aşımına uğradı; daha belirgin sözcüklerle yeniden deneyin.",
        504,
      );
    if (response.status === 422)
      throw new SearchError(
        mode === "narrative"
          ? "Olayı en az 10 karakterle, bir iki cümleyle anlatın."
          : "Arama için en az 2 karakter yazın.",
        422,
      );
    throw new SearchError(`Arama tamamlanamadı (${response.status}).`, response.status);
  }
  const page = parseSearchPage(await response.json().catch(() => null));
  if (!page) throw new SearchError("Arama servisinden geçersiz yanıt geldi.");
  return page;
}

export interface SourceDetail {
  title: string;
  sourceUrl: string | null;
  chunks: string[];
  rawText: string;
  verification: Verification;
  isCurrent: boolean | null;
}

export async function loadSourceDetail(id: string, signal?: AbortSignal): Promise<SourceDetail> {
  let response: Response;
  try {
    response = await fetch(`${BASE}/api/legal/sources/${encodeURIComponent(id)}`, {
      credentials: "include",
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new SearchError("Kaynak metnine ulaşılamadı.");
  }
  if (!response.ok)
    throw new SearchError(
      response.status === 404
        ? "Kaynak bulunamadı."
        : `Kaynak metni alınamadı (${response.status}).`,
      response.status,
    );
  const raw = (await response.json().catch(() => null)) as Record<string, unknown> | null;
  if (!raw || typeof raw !== "object" || Array.isArray(raw) || typeof raw.title !== "string")
    throw new SearchError("Kaynak servisinden geçersiz yanıt geldi.");
  if (typeof raw.id !== "string" || raw.id.toLowerCase() !== id.toLowerCase())
    throw new SearchError("Açılan kaynağın kimliği istenen kaynakla eşleşmiyor.");
  const chunks = Array.isArray(raw?.chunks)
    ? (raw.chunks as unknown[])
        .map((chunk) =>
          chunk &&
          typeof chunk === "object" &&
          typeof (chunk as Record<string, unknown>).content === "string"
            ? ((chunk as Record<string, unknown>).content as string).trim()
            : null,
        )
        .filter((value): value is string => !!value)
    : [];
  return {
    title: text(raw.title, 400) ?? "",
    sourceUrl: text(raw.official_source_url, 2000) ?? text(raw.source_url, 2000),
    chunks,
    rawText: typeof raw.raw_text === "string" ? raw.raw_text.trim() : "",
    verification:
      raw.verification === "official" || raw.verification === "third_party"
        ? raw.verification
        : "unknown",
    isCurrent: typeof raw.is_current === "boolean" ? raw.is_current : null,
  };
}

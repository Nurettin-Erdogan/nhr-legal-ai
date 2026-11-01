/**
 * Mevzuat gezgini (arayüzden bağımsız mantık): kanun listesi, madde dizini ve atıf metni.
 *
 * Sunucu yalnız resmî doğrulanmış güncel mevzuatı listeler (Resmî Gazete + MBS). Madde metni `/api/legal/sources/{id}` ile okunur.
 */

export type LegislationType =
  "constitution" | "law" | "decree" | "regulation" | "communique" | "other";

export interface LawSummary {
  lawNo: string;
  lawName: string;
  legislationType: LegislationType;
  articles: number;
  latestVersion: string | null;
  gazetteDate: string | null;
}

export interface LawPage {
  query: string;
  total: number;
  offset: number;
  /** Sorguda "4857 m. 18" gibi bir madde atfı varsa. */
  articleReference: { lawNo: string; articleNo: string } | null;
  results: LawSummary[];
}

export interface ArticleEntry {
  id: string;
  articleNo: string | null;
  articleTitle: string | null;
  versionDate: string | null;
}

export interface LawDetail {
  lawNo: string;
  lawName: string;
  legislationType: LegislationType;
  gazetteDate: string | null;
  articles: ArticleEntry[];
  truncated: boolean;
}

export const TYPE_LABELS: Record<LegislationType, string> = {
  constitution: "Anayasa",
  law: "Kanun",
  decree: "KHK / Kararname",
  regulation: "Yönetmelik",
  communique: "Tebliğ",
  other: "Diğer",
};

export const TYPE_FILTERS: LegislationType[] = [
  "law",
  "regulation",
  "decree",
  "communique",
  "constitution",
  "other",
];

const TYPES = new Set<string>(Object.keys(TYPE_LABELS));
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const str = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value.replace(/\s+/g, " ").trim() : null;
const count = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.trunc(value) : 0;
const kind = (value: unknown): LegislationType =>
  typeof value === "string" && TYPES.has(value) ? (value as LegislationType) : "other";

function parseLaw(raw: unknown): LawSummary | null {
  if (!isRecord(raw)) return null;
  const lawNo = str(raw.law_no);
  const lawName = str(raw.law_name);
  if (!lawNo || !lawName) return null;
  return {
    lawNo,
    lawName,
    legislationType: kind(raw.legislation_type),
    articles: count(raw.articles),
    latestVersion: str(raw.latest_version),
    gazetteDate: str(raw.gazette_date),
  };
}

/** Geçersiz yanıtta `null`: yarım bir liste "sonuç yok" gibi gösterilmez. */
export function parseLawPage(raw: unknown): LawPage | null {
  if (!isRecord(raw) || !Array.isArray(raw.results)) return null;
  const reference =
    isRecord(raw.article_reference) &&
    str(raw.article_reference.law_no) &&
    str(raw.article_reference.article_no)
      ? {
          lawNo: str(raw.article_reference.law_no)!,
          articleNo: str(raw.article_reference.article_no)!,
        }
      : null;
  return {
    query: typeof raw.query === "string" ? raw.query : "",
    total: count(raw.total),
    offset: count(raw.offset),
    articleReference: reference,
    results: raw.results.flatMap((item) => {
      const law = parseLaw(item);
      return law ? [law] : [];
    }),
  };
}

export function parseLawDetail(raw: unknown): LawDetail | null {
  if (!isRecord(raw) || !Array.isArray(raw.articles)) return null;
  const lawNo = str(raw.law_no);
  const lawName = str(raw.law_name);
  if (!lawNo || !lawName) return null;
  return {
    lawNo,
    lawName,
    legislationType: kind(raw.legislation_type),
    gazetteDate: str(raw.gazette_date),
    truncated: raw.truncated === true,
    articles: raw.articles.flatMap((item): ArticleEntry[] =>
      isRecord(item) && typeof item.id === "string" && item.id
        ? [
            {
              id: item.id,
              articleNo: str(item.article_no),
              articleTitle: str(item.article_title),
              versionDate: str(item.version_date),
            },
          ]
        : [],
    ),
  };
}

const fold = (text: string): string =>
  text
    .replace(/İ/g, "i")
    .replace(/I/g, "ı")
    .toLocaleLowerCase("tr")
    .replace(/ı/g, "i")
    .replace(/ç/g, "c")
    .replace(/ğ/g, "g")
    .replace(/ö/g, "o")
    .replace(/ş/g, "s")
    .replace(/ü/g, "u")
    .replace(/\s+/g, " ")
    .trim();

/** Madde dizinini "18", "geçici", "fesih" gibi bir ifadeyle süzer: numara tam/önek eşleşmesi ya da başlıkta geçme. */
export function filterArticles(articles: ArticleEntry[], query: string): ArticleEntry[] {
  const wanted = fold(query.replace(/^(madde|md\.?|m\.)\s*/i, ""));
  if (!wanted) return articles;
  return articles.filter((article) => {
    const number = fold(article.articleNo ?? "");
    const title = fold(article.articleTitle ?? "");
    return (
      number === wanted ||
      number.startsWith(`${wanted}/`) ||
      title.includes(wanted) ||
      (/\D/.test(wanted) && number.includes(wanted))
    );
  });
}

export function findArticle(articles: ArticleEntry[], articleNo: string): ArticleEntry | undefined {
  const wanted = fold(articleNo);
  return articles.find((article) => fold(article.articleNo ?? "") === wanted);
}

export function articleLabel(article: ArticleEntry): string {
  const number = article.articleNo
    ? /^\d/.test(article.articleNo)
      ? `Madde ${article.articleNo}`
      : article.articleNo
    : "Madde";
  return article.articleTitle ? `${number} — ${article.articleTitle.replace(/:\s*$/, "")}` : number;
}

/** Atıf satırı: "İŞ KANUNU (4857) m. 18". Madde numarası "Geçici Madde 1" gibi ise olduğu gibi yazılır. */
export function citationFor(
  law: Pick<LawSummary, "lawNo" | "lawName">,
  article: ArticleEntry,
): string {
  const number = article.articleNo
    ? /^\d/.test(article.articleNo)
      ? `m. ${article.articleNo}`
      : article.articleNo
    : "";
  return [`${law.lawName} (${law.lawNo})`, number].filter(Boolean).join(" ");
}

export const dateTr = (iso: string | null): string => {
  const match = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  return match ? `${match[3]}.${match[2]}.${match[1]}` : "";
};

const BASE = (import.meta.env?.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export class LegislationError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
  }
}

async function call(path: string, signal?: AbortSignal): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { credentials: "include", signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new LegislationError("Mevzuat servisine ulaşılamadı.");
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* JSON değil */
    }
    throw new LegislationError(
      detail ||
        (response.status === 404
          ? "Mevzuat bulunamadı."
          : `İstek tamamlanamadı (${response.status}).`),
      response.status,
    );
  }
  return response.json().catch(() => null);
}

export async function searchLaws(
  query: string,
  options: {
    kind?: LegislationType | "";
    offset?: number;
    limit?: number;
    signal?: AbortSignal;
  } = {},
): Promise<LawPage> {
  const params = new URLSearchParams({
    q: query.trim(),
    limit: String(options.limit ?? 30),
    offset: String(options.offset ?? 0),
  });
  if (options.kind) params.set("kind", options.kind);
  const page = parseLawPage(await call(`/api/legal/laws?${params}`, options.signal));
  if (!page) throw new LegislationError("Mevzuat servisinden geçersiz yanıt geldi.");
  return page;
}

export async function loadLaw(lawNo: string, signal?: AbortSignal): Promise<LawDetail> {
  const detail = parseLawDetail(await call(`/api/legal/laws/${encodeURIComponent(lawNo)}`, signal));
  if (!detail) throw new LegislationError("Mevzuat servisinden geçersiz yanıt geldi.");
  return detail;
}

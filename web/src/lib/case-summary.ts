/**
 * Dosya özeti (arayüzden bağımsız mantık): belirleyici olgu tablosu ve doğrulanmış yapay zekâ özeti.
 *
 * Olgu tablosu belge metninden düzenli ifadelerle çıkarılır (model yok). Özet arka plan işidir: başlatılır, ilerlemesi yoklanır ve
 * sonuç sunucuda kaydedilir. Sunucu özet maddelerini belgeyle doğrular; elenen madde sayısı ve kapsam oranı kullanıcıya gösterilir.
 */

export interface DocumentFacts {
  id: string;
  fileName: string;
  ocr: boolean;
  dates: string[];
  amounts: string[];
  esas: string[];
  karar: string[];
  numbers: string[];
  laws: string[];
  characters: number;
}

export interface FactsResponse {
  total: number;
  ready: number;
  documents: DocumentFacts[];
}

export interface SummaryDocument {
  documentId: string;
  fileName: string;
  ocr: boolean;
  /** 0-1: belgenin ne kadarı özetlendi (uzun belgede ilk pencereler). */
  coverage: number;
  bullets: string[];
  /** Belgeyle eşleşmediği için gösterilmeyen madde sayısı. */
  dropped: number;
  error: string | null;
}

export type JobState = "running" | "done" | "failed";

export interface SummaryJob {
  id: string;
  state: JobState;
  total: number;
  done: number;
  error: string | null;
  results: SummaryDocument[];
  savedId: string | null;
}

export interface SavedSummary {
  id: string;
  createdAt: string;
  documents: SummaryDocument[];
  model: string | null;
}

export interface SummaryState {
  job: SummaryJob | null;
  latest: SavedSummary | null;
}

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const strings = (value: unknown): string[] => (Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []);
const count = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.trunc(value) : 0);

export function parseFacts(raw: unknown): FactsResponse | null {
  if (!isRecord(raw) || !Array.isArray(raw.documents)) return null;
  const documents = raw.documents.flatMap((item): DocumentFacts[] =>
    isRecord(item) && typeof item.id === "string" && item.id
      ? [
          {
            id: item.id,
            fileName: typeof item.file_name === "string" && item.file_name ? item.file_name : "Adsız belge",
            ocr: item.ocr === true,
            dates: strings(item.dates),
            amounts: strings(item.amounts),
            esas: strings(item.esas),
            karar: strings(item.karar),
            numbers: strings(item.numbers),
            laws: strings(item.laws),
            characters: count(item.characters),
          },
        ]
      : [],
  );
  return { total: count(raw.total), ready: count(raw.ready), documents };
}

function parseSummaryDocument(raw: unknown): SummaryDocument | null {
  if (!isRecord(raw) || typeof raw.document_id !== "string") return null;
  const coverage = typeof raw.coverage === "number" && raw.coverage >= 0 && raw.coverage <= 1 ? raw.coverage : 1;
  return {
    documentId: raw.document_id,
    fileName: typeof raw.file_name === "string" && raw.file_name ? raw.file_name : "Adsız belge",
    ocr: raw.ocr === true,
    coverage,
    bullets: strings(raw.bullets),
    dropped: count(raw.dropped),
    error: typeof raw.error === "string" && raw.error ? raw.error : null,
  };
}

const parseDocuments = (raw: unknown): SummaryDocument[] =>
  Array.isArray(raw) ? raw.flatMap((item) => {
    const parsed = parseSummaryDocument(item);
    return parsed ? [parsed] : [];
  }) : [];

function parseJob(raw: unknown): SummaryJob | null {
  if (!isRecord(raw) || typeof raw.id !== "string") return null;
  const state: JobState = raw.state === "done" || raw.state === "failed" ? raw.state : "running";
  return {
    id: raw.id,
    state,
    total: count(raw.total),
    done: count(raw.done),
    error: typeof raw.error === "string" && raw.error ? raw.error : null,
    results: parseDocuments(raw.results),
    savedId: typeof raw.saved_id === "string" ? raw.saved_id : null,
  };
}

/** Geçersiz yanıtta `null`: yarım bir durum "özet yok" gibi gösterilmez. */
export function parseSummaryState(raw: unknown): SummaryState | null {
  if (!isRecord(raw)) return null;
  const job = raw.job === null || raw.job === undefined ? null : parseJob(raw.job);
  if (raw.job && !job) return null;
  let latest: SavedSummary | null = null;
  if (isRecord(raw.latest) && typeof raw.latest.id === "string") {
    latest = {
      id: raw.latest.id,
      createdAt: typeof raw.latest.created_at === "string" ? raw.latest.created_at : "",
      documents: parseDocuments(raw.latest.documents),
      model: typeof raw.latest.model === "string" ? raw.latest.model : null,
    };
  }
  return { job, latest };
}

/** Kullanıcıya gösterilecek kapsam notu; tam kapsamda boş. */
export function coverageNote(document: SummaryDocument): string {
  return document.coverage < 0.999 ? `Belgenin yaklaşık %${Math.round(document.coverage * 100)}'i özetlendi.` : "";
}

export function progressText(job: SummaryJob): string {
  if (job.state === "running") return `${job.done}/${job.total} belge özetlendi…`;
  if (job.state === "failed") return job.error ?? "Özet üretilemedi.";
  const failed = job.results.filter((result) => result.error).length;
  return failed ? `${job.total} belgeden ${job.total - failed} tanesi özetlendi; ${failed} belge için özet üretilemedi.` : `${job.total} belge özetlendi.`;
}

/** Panoya kopyalanacak metin (sunucudaki kayıtlı çıktıyla aynı biçim). */
export function summaryMarkdown(documents: SummaryDocument[]): string {
  const lines = ["# Dosya özeti", "", "_Yapay zekâ özetidir, belgeyle karşılaştırın; hukuki dayanak ya da resmî kaynak değildir._", ""];
  documents.forEach((document, index) => {
    lines.push(`## ${index + 1}. ${document.fileName}`);
    if (document.ocr) lines.push("_Metin OCR ile okundu; okuma hataları olabilir._");
    const note = coverageNote(document);
    if (note) lines.push(`_${note}_`);
    if (document.error) lines.push(`_${document.error}_`);
    for (const bullet of document.bullets) lines.push(`- ${bullet}`);
    if (document.dropped) lines.push(`_${document.dropped} madde belgeyle eşleşmediği için gösterilmedi._`);
    lines.push("");
  });
  return `${lines.join("\n").trimEnd()}\n`;
}

/** Tabloda gösterilecek tek hücre: boşsa "—". */
export const cell = (values: string[], max = 4): string => {
  if (!values.length) return "—";
  return values.length > max ? `${values.slice(0, max).join(", ")} +${values.length - max}` : values.join(", ");
};

export const hasFacts = (facts: DocumentFacts): boolean =>
  facts.dates.length + facts.amounts.length + facts.esas.length + facts.karar.length + facts.numbers.length + facts.laws.length > 0;

const BASE = (import.meta.env?.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export class SummaryError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
  }
}

async function call(path: string, init: RequestInit & { token?: string | null } = {}): Promise<unknown> {
  const { token, ...rest } = init;
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...rest,
      credentials: "include",
      headers: { ...(rest.body ? { "Content-Type": "application/json" } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
  } catch (error) {
    if (rest.signal?.aborted) throw error;
    throw new SummaryError("Sunucuya ulaşılamadı.");
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* JSON değil */
    }
    throw new SummaryError(detail || (response.status === 401 ? "Oturumunuz sona ermiş; yeniden giriş yapın." : `İstek tamamlanamadı (${response.status}).`), response.status);
  }
  return response.json().catch(() => null);
}

const enc = encodeURIComponent;

export async function loadFacts(caseId: string, options: { token?: string | null; signal?: AbortSignal } = {}): Promise<FactsResponse> {
  let offset = 0;
  const documents: DocumentFacts[] = [];
  const seen = new Set<string>();
  for (;;) {
    const raw = await call(`/api/office/cases/${enc(caseId)}/documents/facts?offset=${offset}&limit=100`, options);
    const parsed = parseFacts(raw);
    if (!parsed) throw new SummaryError("Sunucudan geçersiz bir olgu tablosu geldi.");
    for (const document of parsed.documents) {
      if (seen.has(document.id)) throw new SummaryError("Belge listesi değişti; yeniden yükleyin.");
      seen.add(document.id);
      documents.push(document);
    }
    if (!isRecord(raw) || raw.has_more !== true) return { ...parsed, documents };
    if (!parsed.documents.length) throw new SummaryError("Olgu tablosu eksik geldi; yeniden yükleyin.");
    offset += parsed.documents.length;
  }
}

export async function loadSummaryState(caseId: string, options: { token?: string | null; signal?: AbortSignal } = {}): Promise<SummaryState> {
  const parsed = parseSummaryState(await call(`/api/office-ai/cases/${enc(caseId)}/summary`, options));
  if (!parsed) throw new SummaryError("Sunucudan geçersiz bir özet durumu geldi.");
  return parsed;
}

export async function startSummary(caseId: string, documentIds: string[], options: { token?: string | null } = {}): Promise<{ jobId: string; total: number }> {
  const raw = await call(`/api/office-ai/cases/${enc(caseId)}/summary`, { method: "POST", body: JSON.stringify({ document_ids: documentIds }), token: options.token });
  if (!isRecord(raw) || typeof raw.job_id !== "string") throw new SummaryError("Sunucudan geçersiz bir iş yanıtı geldi.");
  return { jobId: raw.job_id, total: count(raw.total) };
}

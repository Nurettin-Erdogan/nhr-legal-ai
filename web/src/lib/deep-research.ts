/**
 * Derin araştırma (arayüzden bağımsız mantık).
 *
 * Sunucu soruyu üç sabit eksene böler (mevzuat, yargı kararları, süre/ispat/usul), her eksen için kaynaklı cevap hattını çalıştırır ve
 * adım cevaplarını kendi kaynaklarıyla raporlar. Cevaplar sunucuda kaynaklara karşı doğrulanır; burada yanıt savunmacı ayrıştırılır ve
 * doğrulanmamış (üçüncü taraf) kaynaklar rozetle ayrı gösterilir.
 */

export const MIN_QUESTION = 15;
export const MAX_QUESTION = 1500;

export interface StepCitation {
  marker: string;
  reference: string;
  sourceUrl: string | null;
  verification: "official" | "third_party" | "user_document" | "unknown";
  sourceType: string;
}

export interface ResearchStep {
  key: string;
  title: string;
  answer: string;
  /** Cevabın kaynaklarla desteklendiği sunucuda doğrulandı mı. */
  grounded: boolean;
  citations: StepCitation[];
  error: string | null;
  /** Cevap önceki başlıkla aynıysa tekrarlanmaz; neden burada (hata değildir). */
  note: string | null;
}

export type JobState = "running" | "done" | "failed";

export interface ResearchJob {
  id: string;
  state: JobState;
  stage: string;
  total: number;
  done: number;
  error: string | null;
  steps: ResearchStep[];
  savedId: string | null;
}

export interface SavedReport {
  id: string;
  createdAt: string;
  question: string;
  markdown: string;
  steps: ResearchStep[];
}

export interface ResearchState {
  job: ResearchJob | null;
  latest: SavedReport | null;
}

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const count = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.trunc(value) : 0);
const text = (value: unknown): string => (typeof value === "string" ? value : "");

function parseCitation(raw: unknown): StepCitation | null {
  if (!isRecord(raw) || typeof raw.marker !== "string" || typeof raw.reference !== "string") return null;
  const verification = raw.verification === "official" || raw.verification === "third_party" || raw.verification === "user_document" ? raw.verification : "unknown";
  return {
    marker: raw.marker,
    reference: raw.reference,
    sourceUrl: typeof raw.source_url === "string" && /^https?:\/\//i.test(raw.source_url) ? raw.source_url : null,
    verification,
    sourceType: text(raw.source_type),
  };
}

function parseStep(raw: unknown): ResearchStep | null {
  if (!isRecord(raw) || typeof raw.title !== "string") return null;
  return {
    key: text(raw.key),
    title: raw.title,
    answer: text(raw.answer),
    // Belirsizse "doğrulandı" sayılmaz.
    grounded: raw.grounded === true,
    citations: Array.isArray(raw.citations) ? raw.citations.flatMap((item) => {
      const parsed = parseCitation(item);
      return parsed ? [parsed] : [];
    }) : [],
    error: typeof raw.error === "string" && raw.error ? raw.error : null,
    note: typeof raw.note === "string" && raw.note ? raw.note : null,
  };
}

const parseSteps = (raw: unknown): ResearchStep[] =>
  Array.isArray(raw) ? raw.flatMap((item) => {
    const parsed = parseStep(item);
    return parsed ? [parsed] : [];
  }) : [];

function parseJob(raw: unknown): ResearchJob | null {
  if (!isRecord(raw) || typeof raw.id !== "string") return null;
  return {
    id: raw.id,
    state: raw.state === "done" || raw.state === "failed" ? raw.state : "running",
    stage: text(raw.stage),
    total: count(raw.total),
    done: count(raw.done),
    error: typeof raw.error === "string" && raw.error ? raw.error : null,
    steps: parseSteps(raw.steps),
    savedId: typeof raw.saved_id === "string" ? raw.saved_id : null,
  };
}

/** Geçersiz yanıtta `null`: yarım bir durum "rapor yok" gibi gösterilmez. */
export function parseResearchState(raw: unknown): ResearchState | null {
  if (!isRecord(raw)) return null;
  const job = raw.job === null || raw.job === undefined ? null : parseJob(raw.job);
  if (raw.job && !job) return null;
  let latest: SavedReport | null = null;
  if (isRecord(raw.latest) && typeof raw.latest.id === "string") {
    latest = {
      id: raw.latest.id,
      createdAt: text(raw.latest.created_at),
      question: text(raw.latest.question),
      markdown: text(raw.latest.markdown),
      steps: parseSteps(raw.latest.steps),
    };
  }
  return { job, latest };
}

export function verificationLabel(verification: StepCitation["verification"]): string {
  if (verification === "third_party") return "doğrulanmadı";
  if (verification === "user_document") return "kullanıcı belgesi";
  if (verification === "unknown") return "doğrulama durumu bilinmiyor";
  return "";
}

/** İlerleme satırı. */
export function progressLine(job: ResearchJob): string {
  if (job.state === "running") return job.stage || `${job.done}/${job.total} başlık tamamlandı…`;
  if (job.state === "failed") return job.error ?? "Araştırma tamamlanamadı.";
  const failed = job.steps.filter((step) => step.error).length;
  return failed ? `${job.total} başlıktan ${job.total - failed} tanesi tamamlandı; ${failed} başlık için cevap üretilemedi.` : `${job.total} başlık tamamlandı.`;
}

export const canStart = (question: string): boolean => question.trim().length >= MIN_QUESTION && question.length <= MAX_QUESTION;

const BASE = (import.meta.env?.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export class ResearchError extends Error {
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
    throw new ResearchError("Sunucuya ulaşılamadı.");
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* JSON değil */
    }
    throw new ResearchError(detail || (response.status === 401 ? "Oturumunuz sona ermiş; yeniden giriş yapın." : `İstek tamamlanamadı (${response.status}).`), response.status);
  }
  return response.json().catch(() => null);
}

export async function loadResearchState(options: { token?: string | null; signal?: AbortSignal } = {}): Promise<ResearchState> {
  const parsed = parseResearchState(await call("/api/office-ai/deep-research", options));
  if (!parsed) throw new ResearchError("Sunucudan geçersiz bir araştırma durumu geldi.");
  return parsed;
}

export async function startResearch(question: string, options: { token?: string | null } = {}): Promise<{ jobId: string }> {
  const raw = await call("/api/office-ai/deep-research", { method: "POST", body: JSON.stringify({ question: question.trim() }), token: options.token });
  if (!isRecord(raw) || typeof raw.job_id !== "string") throw new ResearchError("Sunucudan geçersiz bir iş yanıtı geldi.");
  return { jobId: raw.job_id };
}

import { inMemoryAccessToken } from "@/lib/auth-api";
import {
  parseCaseDocumentIndex,
  parseDocumentScope,
  type CaseDocumentIndex,
  type DocumentScope,
} from "./document-scope";
import type { ConsultedSource } from "./consulted-sources";
import { parseSearchSummary, type SearchSummaryData } from "./search-summary";

const API_BASE_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export type AnswerKind = "conversation" | "clarification" | "legal" | "insufficient_sources";

/** Eski veya tanınmayan cevaplar kaynak denetiminden muaf tutulmaz. */
export function parseAnswerKind(value: unknown): AnswerKind {
  return value === "conversation" || value === "clarification" || value === "insufficient_sources"
    ? value
    : "legal";
}

export interface Citation {
  marker: string;
  source_id: string | null;
  source_type: string | null;
  reference: string;
  source_url: string | null;
  excerpt: string | null;
  /** "official" dışındaki her değer üçüncü taraf/doğrulanmamış kaynaktır. */
  verification: string;
}

export interface ChatMessage {
  id?: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  /** Cevapta alıntılanmayan ama incelenen doğrulanmış kaynaklar (canlı cevapta; geçmişte yok). */
  consultedSources?: ConsultedSource[];
  grounded?: boolean | null;
  answerKind?: AnswerKind;
  unverifiedMarkers?: string[];
  searchSummary?: SearchSummaryData;
  /** Dava kapsamlı cevapta: belgelerin ne kadarı cevaba katılabildi. */
  documentScope?: DocumentScope;
  /** Takip sorusu önceki sorulara göre nasıl yorumlandı (yalnız canlı cevapta). */
  interpretedQuestion?: string;
  /** Uzun kanun maddesi cevabı için denetlenmiş kısa özet (yapay zekâ; dayanak madde metnidir). */
  summary?: string[];
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  project_id?: string | null;
  case_id?: string | null;
  office_project_id?: string | null;
  selected_document_ids?: string[];
  last_message_at: string;
  message_count: number;
}

export interface AnswerResult {
  answer: string;
  answer_kind?: AnswerKind;
  grounded: boolean;
  unverified_markers: string[];
  conversation_id: string | null;
  message_id: string | null;
  citations: Citation[];
  consulted_sources?: Citation[];
  search_summary?: SearchSummaryData;
  document_scope?: DocumentScope | null;
  interpreted_question?: string | null;
  summary?: string[];
}

export const STAGE_LABELS: Record<string, string> = {
  searching: "Kaynaklar aranıyor…",
  summarizing: "Madde özetleniyor…",
  candidates_found: "Aday belgeler bulundu; kaynaklar kontrol ediliyor…",
  verifying_source: "Adaylar resmî kaynaklarla karşılaştırılıyor…",
  search_summary: "Kaynak seçimi tamamlandı…",
  sources_found: "Kaynaklar bulundu…",
  generating: "Cevap yazılıyor…",
  verifying: "Atıflar doğrulanıyor…",
};

function authHeaders(): Record<string, string> {
  const token = inMemoryAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...authHeaders(),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let detail = `Sunucu isteği başarısız oldu (${response.status}).`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      /* JSON değil */
    }
    throw Object.assign(new Error(detail), { status: response.status });
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface ConversationScope {
  projectId?: string | null;
  caseId?: string | null;
  officeProjectId?: string | null;
  selectedDocumentIds?: string[];
}

export const listConversations = (scope: ConversationScope = {}) => {
  const params = new URLSearchParams();
  if (scope.projectId) params.set("project_id", scope.projectId);
  if (scope.caseId) params.set("case_id", scope.caseId);
  if (scope.officeProjectId) params.set("office_project_id", scope.officeProjectId);
  return api<ConversationSummary[]>(`/api/conversations${params.size ? `?${params}` : ""}`);
};

export async function getConversationDetail(
  id: string,
): Promise<{ scope: ConversationScope; messages: ChatMessage[] }> {
  const detail = await api<{
    project_id: string | null;
    case_id: string | null;
    office_project_id: string | null;
    selected_document_ids: string[];
    messages: Array<{
      id: string;
      role: string;
      content: string;
      grounded: boolean | null;
      answer_kind?: unknown;
      document_scope?: unknown;
      unverified_markers: string[];
      citations: Citation[];
      summary?: string[];
    }>;
  }>(`/api/conversations/${id}`);
  const messages: ChatMessage[] = detail.messages
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({
      id: m.id,
      role: m.role as "user" | "assistant",
      content: m.content,
      citations: m.citations,
      grounded: m.grounded,
      answerKind: parseAnswerKind(m.answer_kind),
      documentScope: parseDocumentScope(m.document_scope),
      unverifiedMarkers: m.unverified_markers,
      summary: Array.isArray(m.summary)
        ? m.summary.filter((item): item is string => typeof item === "string")
        : undefined,
    }));
  return {
    messages,
    scope: {
      projectId: detail.project_id ?? null,
      caseId: detail.case_id ?? null,
      officeProjectId: detail.office_project_id ?? null,
      selectedDocumentIds: detail.selected_document_ids ?? [],
    },
  };
}

export const getConversation = async (id: string): Promise<ChatMessage[]> =>
  (await getConversationDetail(id)).messages;

export const deleteConversation = (id: string) =>
  api<void>(`/api/conversations/${id}`, { method: "DELETE" });

/** Dava belgelerinin aranabilirlik durumu (hazır / okunamadı + neden / işlenmedi). */
export async function getCaseDocumentIndex(caseId: string): Promise<CaseDocumentIndex> {
  return parseCaseDocumentIndex(
    await api<unknown>(`/api/office/cases/${encodeURIComponent(caseId)}/documents/index`),
  );
}

/** Belgeyi açıkça yeniden işletir (ör. okunamayan ya da henüz işlenmeyen belge). */
export const reindexCaseDocument = (caseId: string, documentId: string) =>
  api<{ status: string }>(
    `/api/office/cases/${encodeURIComponent(caseId)}/documents/${encodeURIComponent(documentId)}/reindex`,
    { method: "POST" },
  );

/** NDJSON aşama akışını okur; "done" olayındaki sonucu döndürür. */
export async function askAssistant(
  question: string,
  opts: {
    conversationId?: string | null;
    projectId?: string | null;
    /** Büro davası: yalnız bu davaya bağlı belgeler de aranır. `projectId` ile birlikte verilmez. */
    caseId?: string | null;
    officeProjectId?: string | null;
    /** office_case_documents kimlikleri: yalnız seçili belgeler; caseId varsa onun alt kümesi. */
    selectedDocumentIds?: string[];
    onStage?: (stage: string) => void;
    onSearchSummary?: (summary: SearchSummaryData) => void;
    /** Doğrulanmış cevap hazır, ek adım (madde özeti) sürüyor: cevap beklemeden gösterilebilir. Kalıcı sonuç yine döner. */
    onPreview?: (preview: AnswerResult) => void;
  },
): Promise<AnswerResult> {
  const response = await fetch(`${API_BASE_URL}/api/ai/answer/progress`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      question,
      conversation_id: opts.conversationId ?? null,
      project_id: opts.projectId ?? null,
      case_id: opts.caseId ?? null,
      office_project_id: opts.officeProjectId ?? null,
      selected_document_ids: opts.selectedDocumentIds ?? [],
    }),
  });
  if (!response.ok || !response.body) {
    if (!response.ok) {
      const error = await response.json().catch(() => null);
      if (typeof error?.detail === "string") throw new Error(error.detail);
    }
    throw new Error(
      response.status === 401
        ? "Oturum süresi doldu, tekrar giriş yapın."
        : "Asistana ulaşılamadı.",
    );
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: AnswerResult | null = null;
  const handle = (line: string) => {
    if (!line.trim()) return;
    const event = JSON.parse(line) as {
      stage: string;
      result?: AnswerResult;
      preview?: AnswerResult;
      detail?: unknown;
    };
    if (event.stage === "error") {
      throw new Error(typeof event.detail === "string" ? event.detail : "Cevap üretilemedi.");
    }
    if (event.stage === "search_summary") {
      const summary = parseSearchSummary(event);
      if (summary) opts.onSearchSummary?.(summary);
    }
    if (event.preview) {
      opts.onPreview?.({
        ...event.preview,
        answer_kind: parseAnswerKind(event.preview.answer_kind),
        search_summary: parseSearchSummary(event.preview.search_summary),
        document_scope: parseDocumentScope(event.preview.document_scope),
      });
    }
    if (event.stage === "done" && event.result) {
      result = {
        ...event.result,
        answer_kind: parseAnswerKind(event.result.answer_kind),
        search_summary: parseSearchSummary(event.result.search_summary),
        document_scope: parseDocumentScope(event.result.document_scope),
      };
    } else if (event.stage !== "ping") opts.onStage?.(event.stage);
  };
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl: number;
      while ((nl = buffer.indexOf("\n")) !== -1) {
        handle(buffer.slice(0, nl));
        buffer = buffer.slice(nl + 1);
      }
    }
    handle(buffer + decoder.decode());
    if (!result) throw new Error("Cevap tamamlanmadan bağlantı kesildi.");
    return result;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

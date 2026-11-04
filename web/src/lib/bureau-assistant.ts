import { inMemoryAccessToken } from "@/lib/auth-api";
import type { DocumentJobInput } from "@/lib/document-jobs";

export interface BureauProposal {
  key: string;
  kind: "hearing" | "document";
  title: string;
  description: string;
  case_id: string | null;
  case_title: string;
  source_label: string;
  source_url: string;
  date: string;
  priority: "high" | "medium";
  action_label: string;
}
export interface BureauData {
  proposals: BureauProposal[];
  hearings: {
    id: string;
    title: string;
    next_hearing: string;
    case_no: string | null;
    court: string | null;
  }[];
  tasks: { id: string; title: string; due_date: string | null; case_id: string | null }[];
  counts: {
    open_tasks: number;
    overdue_tasks: number;
    upcoming_hearings: number;
    today_tasks?: number;
    today_hearings?: number;
  };
  limited: boolean;
  generated_at: string;
  window_days: number | null;
}
const BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

async function call(path: string, body?: unknown, signal?: AbortSignal) {
  const token = inMemoryAccessToken();
  const response = await fetch(`${BASE}/api/bureau-assistant${path}`, {
    method: body ? "POST" : "GET",
    credentials: "include",
    cache: "no-store",
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    signal: signal
      ? AbortSignal.any([signal, AbortSignal.timeout(20000)])
      : AbortSignal.timeout(20000),
  });
  if (!response.ok) {
    let detail = "Büro Asistanı verileri alınamadı. Yeniden deneyin.";
    try {
      const data = await response.json();
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      /* keep safe message */
    }
    throw new Error(detail);
  }
  return response.json();
}
export const loadBureau = (signal?: AbortSignal): Promise<BureauData> =>
  call("", undefined, signal);
export const decideBureau = (key: string, action: "approve" | "dismiss", title?: string) =>
  call("/decisions", { key, action, ...(title ? { title } : {}) });

export interface BureauReview {
  proposal: BureauProposal;
  documents: {
    id: string;
    file_name: string;
    ready: boolean;
    ocr: boolean;
    excerpt: string | null;
  }[];
  limited: boolean;
  suggested_action: string;
  generated_at: string;
  action_available?: boolean;
  preparation?: {
    case_no: string | null;
    court: string | null;
    status: string;
    hearing_at: string;
    total_documents: number;
    ready_documents: number;
    tasks: { id: string; title: string; status: string; due_date: string | null }[];
    tasks_limited: boolean;
    checklist: string[];
  };
}
export const loadBureauReview = (key: string, signal?: AbortSignal): Promise<BureauReview> =>
  call(`/review?key=${encodeURIComponent(key)}`, undefined, signal);
export const loadCasePreparation = (caseId: string, signal?: AbortSignal): Promise<BureauReview> =>
  call(`/cases/${encodeURIComponent(caseId)}/preparation`, undefined, signal);

export function preparationNote(
  review: BureauReview,
  summary?: string,
  selectedIds?: string[],
): string {
  const p = review.preparation;
  const when = (date: string) =>
    new Date(date).toLocaleString("tr-TR", { timeZone: "Europe/Istanbul" });
  return [
    "# Duruşma hazırlık notu",
    review.proposal.case_title,
    `Kayıt tarihi: ${when(review.generated_at)}`,
    ...(p
      ? [
          `Mahkeme: ${p.court || "Kayıtlı değil"}`,
          `Dosya no: ${p.case_no || "Kayıtlı değil"}`,
          `Kayıtlı duruşma: ${when(p.hearing_at)}`,
          `Belge kapsamı: ${review.documents.length}/${p.total_documents} belge listelendi; dosyada ${p.ready_documents} okunabilir belge var.`,
          "## Açık görevler",
          ...p.tasks.map(
            (t) =>
              `- ${t.title}${t.due_date ? ` · Kayıtlı son tarih: ${when(t.due_date)}` : " · Son tarih kayıtlı değil"}`,
          ),
          ...(p.tasks_limited
            ? ["Görev listesi sınırlıdır; tüm görevleri dosyadan kontrol edin."]
            : []),
          "## Kontrol listesi",
          ...p.checklist.map((c) => `- ${c}`),
        ]
      : []),
    "## İnceleme listesi (tamamının özetlendiği anlamına gelmez)",
    ...review.documents.map(
      (d) => `- ${d.file_name} (${d.ready ? "okunabilir" : "okunamadı"}${d.ocr ? ", OCR" : ""})`,
    ),
    ...(selectedIds
      ? [
          "## Özet için seçilen belgeler",
          ...review.documents
            .filter((d) => d.ready && selectedIds.includes(d.id))
            .map((d) => `- ${d.file_name}`),
        ]
      : []),
    "## Belge özeti",
    summary || "Henüz belge özeti oluşturulmadı.",
    "Bu not kayıtlı dosya bilgilerine ve belirtilen belgelere dayanır. Hukuki görüş veya süre hesabı değildir.",
  ].join("\n\n");
}

export function bureauSummaryInput(review: BureauReview, selectedIds?: string[]): DocumentJobInput {
  const selected = selectedIds === undefined ? null : new Set(selectedIds);
  const ids = [
    ...new Set(
      review.documents
        .filter((d) => d.ready && d.excerpt && (!selected || selected.has(d.id)))
        .map((d) => d.id),
    ),
  ];
  if (!ids.length) throw new Error("Özetlenebilecek okunabilir belge yok.");
  return {
    module: "auto_summary",
    document_ids: ids,
    ...(review.proposal.case_id ? { case_id: review.proposal.case_id } : {}),
    title:
      review.proposal.kind === "hearing"
        ? "Duruşma öncesi belge özeti"
        : "Büro Asistanı belge özeti",
    prompt:
      "Seçili belgeleri ayrı ayrı, yalnız içeriklerine dayanarak özetle. Hukuki süre veya yapılacak işlem uydurma.",
  };
}

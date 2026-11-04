import { inMemoryAccessToken } from "@/lib/auth-api";
const BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");
export interface DocumentJobInput {
  module: "document_analysis" | "auto_summary" | "risk_analysis" | "draft";
  document_ids?: string[];
  text?: string;
  prompt?: string;
  title?: string;
  case_id?: string;
  project_id?: string;
  doc_type?: string;
  parties?: string[];
  subject?: string;
  details?: string;
  draft_fields?: import("./draft-fields").DraftFields;
}
export interface DocumentJob {
  id: string;
  module: string;
  state: "queued" | "running" | "done" | "partial" | "failed" | "cancelled";
  progress: {
    total: number;
    done: number;
    documents: Array<{
      file_name: string;
      windows_done: number;
      windows_total: number;
      errors?: string[];
    }>;
  };
  output_id: string | null;
  output?: string | null;
  error: string | null;
}
export function parseDocumentJob(raw: unknown): DocumentJob {
  const value = raw as Partial<DocumentJob> | null;
  if (
    !value ||
    typeof value.id !== "string" ||
    !value.id ||
    typeof value.module !== "string" ||
    !["document_analysis", "auto_summary", "risk_analysis", "draft"].includes(value.module) ||
    !["queued", "running", "done", "partial", "failed", "cancelled"].includes(value.state ?? "") ||
    !value.progress ||
    !Number.isInteger(value.progress.total) ||
    !Number.isInteger(value.progress.done) ||
    value.progress.total < 1 ||
    value.progress.done < 0 ||
    value.progress.done > value.progress.total ||
    !Array.isArray(value.progress.documents) ||
    (value.output != null && typeof value.output !== "string") ||
    (value.output_id != null && typeof value.output_id !== "string") ||
    value.progress.documents.some(
      (document) =>
        !document ||
        typeof document.file_name !== "string" ||
        !Number.isInteger(document.windows_done) ||
        !Number.isInteger(document.windows_total) ||
        document.windows_done < 0 ||
        document.windows_done > document.windows_total,
    )
  )
    throw new Error("Belge işi yanıtı doğrulanamadı.");
  return value as DocumentJob;
}
async function call(path: string, body?: unknown) {
  const token = inMemoryAccessToken();
  const response = await fetch(`${BASE}/api/office-ai/jobs${path}`, {
    method: body === undefined ? "GET" : "POST",
    credentials: "include",
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      typeof payload?.detail === "string"
        ? payload.detail
        : `Belge kuyruğu yanıt vermedi (${response.status}).`,
    );
  return payload;
}
export async function startDocumentJob(input: DocumentJobInput): Promise<string> {
  const result = await call("", input);
  if (typeof result?.job_id !== "string") throw new Error("İş kimliği doğrulanamadı.");
  return result.job_id;
}
export async function loadDocumentJob(id: string) {
  return parseDocumentJob(await call(`/${encodeURIComponent(id)}`));
}
export async function listDocumentJobs(): Promise<DocumentJob[]> {
  const result = await call("");
  if (!Array.isArray(result?.jobs)) throw new Error("Belge işleri listelenemedi.");
  return result.jobs.map(parseDocumentJob);
}
export async function cancelDocumentJob(id: string) {
  await call(`/${encodeURIComponent(id)}/cancel`, {});
}
export async function resumeDocumentJob(id: string) {
  await call(`/${encodeURIComponent(id)}/resume`, {});
}

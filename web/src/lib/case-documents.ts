import { db } from "@/lib/db";
import { inMemoryAccessToken } from "@/lib/auth-api";

const API_BASE_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export interface UnlinkedDocument {
  id: string;
  file_name: string;
  client_id: string | null;
  created_at: string;
}

export function validateCaseFile(file: Pick<File, "size" | "name">): void {
  if (!file.size) throw new Error("Boş dosya yüklenemez.");
  if (!file.name.trim() || file.name.length > 255) throw new Error("Geçersiz dosya adı.");
}

async function mutate(caseId: string, suffix: string, body?: FormData) {
  if (!UUID.test(caseId)) throw new Error("Geçersiz dava kimliği.");
  const token = inMemoryAccessToken();
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/office/cases/${caseId}/documents${suffix}`, {
      method: "POST",
      credentials: "include",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body,
    });
  } catch {
    // Never automatically repeat a write: the server may have committed it.
    throw new Error(
      "Sunucuya ulaşılamadı. Tekrar yüklemeden önce evrak listesini yenileyip kontrol edin.",
    );
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(
      typeof payload?.detail === "string"
        ? payload.detail
        : `İşlem başarısız (${response.status}).`,
    );
  }
  const result = await response.json();
  if (!result?.id || result.case_id !== caseId)
    throw new Error("Sonuç doğrulanamadı. Evrak listesini yenileyin.");
  return result;
}

export async function uploadCaseDocument(caseId: string, file: File) {
  validateCaseFile(file);
  const form = new FormData();
  form.append("file", file);
  return mutate(caseId, "", form);
}
export async function linkCaseDocument(caseId: string, documentId: string) {
  if (!UUID.test(documentId)) throw new Error("Geçersiz belge kimliği.");
  return mutate(caseId, `/${documentId}/link`);
}
export async function listUnlinkedDocuments(query: string, page: number, client = db) {
  const term = query
    .trim()
    .slice(0, 100)
    .replace(/[\\%_]/g, "\\$&");
  let request = client
    .from("case_documents")
    .select("id,file_name,client_id,created_at")
    .is("case_id", null)
    .order("created_at", { ascending: false })
    .order("id", { ascending: false });
  if (term) request = request.ilike("file_name", `%${term}%`);
  const result = await request.range(page * 25, page * 25 + 25);
  if (result.error) throw new Error(result.error.message);
  if (!Array.isArray(result.data)) throw new Error("Belge listesi yüklenemedi.");
  return { rows: result.data.slice(0, 25) as UnlinkedDocument[], hasMore: result.data.length > 25 };
}

import { inMemoryAccessToken } from "@/lib/auth-api";
const BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");
export interface ProjectDocument {
  id: string;
  file_name: string;
  size_bytes: number;
  source: string;
  doc_type: string | null;
  doc_date: string | null;
  case_id: string | null;
  created_at: string;
  uyap_file_no: string | null;
  uyap_birim: string | null;
  status: string;
  error: string | null;
  ocr: boolean;
  direct_linked: boolean;
}
export interface ProjectDocumentPage {
  project_id: string;
  case_id: string | null;
  total: number;
  ready: number;
  pending: number;
  ocr: number;
  failed: { file_name: string; reason: string }[];
  documents: ProjectDocument[];
}
async function request<T>(
  project: string,
  suffix = "",
  method = "GET",
  body?: unknown,
): Promise<T> {
  const token = inMemoryAccessToken();
  const response = await fetch(
    `${BASE}/api/office/projects/${encodeURIComponent(project)}/documents${suffix}`,
    {
      method,
      credentials: "include",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    },
  );
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(
      typeof error?.detail === "string" ? error.detail : "Proje belgeleriyle işlem yapılamadı.",
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export async function getProjectDocuments(project: string): Promise<ProjectDocumentPage> {
  let result: ProjectDocumentPage | undefined;
  const documents: ProjectDocument[] = [],
    seen = new Set<string>();
  for (let offset = 0; offset < 50000; offset += 500) {
    const page = await request<ProjectDocumentPage>(project, `?limit=500&offset=${offset}`);
    if (
      !Array.isArray(page.documents) ||
      !Number.isInteger(page.total) ||
      page.total < 0 ||
      page.project_id !== project
    )
      throw new Error("Proje belge listesi doğrulanamadı.");
    result = page;
    for (const doc of page.documents) {
      if (!doc || typeof doc.id !== "string" || seen.has(doc.id))
        throw new Error("Belge listesi değişti. Yeniden yükleyin.");
      seen.add(doc.id);
      documents.push(doc);
    }
    if (documents.length === page.total) return { ...page, documents };
    if (page.documents.length < 500 || documents.length > page.total)
      throw new Error("Belge listesi değişti. Yeniden yükleyin.");
  }
  throw new Error(
    `Projedeki ${result?.total ?? ""} belge tek görünüm için fazla. Daha küçük projelerle çalışın.`,
  );
}
export const linkProjectDocuments = (project: string, ids: string[]) =>
  request<{ linked: number; already_linked: number }>(project, "", "POST", { document_ids: ids });
export const unlinkProjectDocument = (project: string, document: string) =>
  request<void>(project, `/${encodeURIComponent(document)}`, "DELETE");

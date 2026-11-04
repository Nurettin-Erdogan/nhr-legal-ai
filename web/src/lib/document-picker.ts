import { inMemoryAccessToken } from "@/lib/auth-api";
import type { CaseDocRow } from "@/components/CaseDocPicker";

const BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");
export async function getDocumentPickerPage(options: {
  caseId?: string;
  projectId?: string;
  query: string;
  offset: number;
}) {
  const params = new URLSearchParams({
    q: options.query,
    offset: String(options.offset),
    limit: "50",
  });
  if (options.caseId) params.set("case_id", options.caseId);
  if (options.projectId) params.set("project_id", options.projectId);
  const token = inMemoryAccessToken();
  const response = await fetch(`${BASE}/api/office/documents/picker?${params}`, {
    credentials: "include",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) throw new Error("Belge listesi yüklenemedi. Yeniden deneyin.");
  const page = await response.json();
  if (
    !Array.isArray(page.documents) ||
    page.documents.length > 50 ||
    typeof page.has_more !== "boolean"
  )
    throw new Error("Belge listesi doğrulanamadı.");
  return page as { documents: CaseDocRow[]; has_more: boolean };
}

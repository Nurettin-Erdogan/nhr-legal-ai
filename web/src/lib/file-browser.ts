import { inMemoryAccessToken } from "@/lib/auth-api";

export interface FileBrowserDocument {
  id: string;
  file_name: string;
  storage_path: string;
  size_bytes: number | null;
  source: string;
  uyap_file_no: string | null;
  uyap_birim: string | null;
  case_id: string | null;
  doc_type: string | null;
  doc_date: string | null;
  created_at: string;
  category: string;
  folder_key: string;
  content_match?: {
    before: string;
    match: string;
    after: string;
    page_number: number | null;
    section_title: string | null;
  } | null;
}

export interface FileBrowserFolder {
  key: string;
  source: string;
  file_no: string | null;
  birim: string | null;
  count: number;
  matching_count: number;
}

export interface FileBrowserCategory {
  id: string;
  label: string;
  count: number;
}
export interface FileBrowserFilters {
  q: string;
  source: string;
  category: string;
  folder: string;
  order: string;
  search_in?: "metadata" | "content";
}
export interface ContentSearchCoverage {
  total: number;
  ready: number;
  pending: number;
  failed: number;
}
export interface FileBrowserResult {
  rows: FileBrowserDocument[];
  total: number;
  folders: FileBrowserFolder[];
  categories: FileBrowserCategory[];
  content_coverage?: ContentSearchCoverage;
}

export async function listFileBrowser(
  filters: FileBrowserFilters,
  signal: AbortSignal,
  summaryOnly = false,
  offset = 0,
): Promise<FileBrowserResult> {
  const query = new URLSearchParams({
    ...filters,
    search_in: filters.search_in ?? "metadata",
    organized: "true",
    summary_only: String(summaryOnly),
    offset: String(offset),
    limit: "100",
  });
  const base = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");
  const token = inMemoryAccessToken();
  const response = await fetch(`${base}/api/office/case-documents/search?${query}`, {
    credentials: "include",
    signal,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Belge listesi yüklenemedi (${response.status})`);
  }
  const result = (await response.json()) as FileBrowserResult;
  if (
    !Array.isArray(result.rows) ||
    !Array.isArray(result.folders) ||
    !Array.isArray(result.categories) ||
    !Number.isInteger(result.total) ||
    result.total < 0
  )
    throw new Error("Belge listesi beklenmeyen biçimde döndü");
  return result;
}

/** Sunucu istekleri küçük parçalarla yapılır; arayüzde sayfa veya belge sınırı yoktur. */
export async function loadAllFileBrowserDocuments(
  filters: FileBrowserFilters,
  signal: AbortSignal,
): Promise<FileBrowserResult> {
  const first = await listFileBrowser(filters, signal);
  const documents = new Map(first.rows.map((row) => [row.id, row]));
  let offset = first.rows.length;
  let expected = first.total;
  let last = first;
  while (offset < expected) {
    if (!last.rows.length) throw new Error("Belge listesi eksik döndü. Yenileyip tekrar deneyin.");
    last = await listFileBrowser(filters, signal, false, offset);
    for (const row of last.rows) documents.set(row.id, row);
    offset += last.rows.length;
    expected = last.total;
  }
  return { ...last, rows: [...documents.values()] };
}

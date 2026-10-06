/**
 * Üst menüdeki genel arama: kullanıcının kendi dava, müvekkil, belge ve görevleri; ayrıca aynı terimi hukuk kaynaklarında
 * aramaya götüren kısayollar. Sunucu yalnız oturum sahibinin kayıtlarını döndürür.
 */
import { inMemoryAccessToken } from "@/lib/auth-api";

export interface WorkspaceSearchResult {
  query: string;
  cases: Array<{ id: string; title: string; case_no: string | null; esas_no: string | null; court: string | null; client_name: string | null }>;
  clients: Array<{ id: string; full_name: string; client_type: string; phone: string | null; email: string | null }>;
  documents: Array<{ id: string; file_name: string; case_id: string | null; uyap_file_no: string | null; uyap_birim: string | null; case_title: string | null }>;
  tasks: Array<{ id: string; title: string; status: string; due_date: string | null; case_id: string | null; case_title: string | null }>;
}

export type SearchGroup = "Davalar" | "Müvekkiller" | "Belgeler" | "Görevler" | "Hukuk kaynaklarında ara";

export interface SearchRow {
  key: string;
  group: SearchGroup;
  label: string;
  detail: string;
  href: string;
}

export const MIN_SEARCH_CHARS = 2;

const enc = encodeURIComponent;
const joined = (...parts: Array<string | null | undefined>) => parts.filter((part) => part && part.trim()).join(" · ");

const TASK_STATUS: Record<string, string> = { todo: "Bekliyor", in_progress: "Sürüyor", done: "Tamamlandı" };

/** Arama terimi yeterince uzun mu (kısa terimde sunucuya gidilmez). */
export function searchable(query: string): boolean {
  return query.trim().length >= MIN_SEARCH_CHARS;
}

/** Hukuk kaynaklarında aynı terimi aramaya götüren kısayollar; kayıt bulunmasa da gösterilir. */
export function legalShortcuts(query: string): SearchRow[] {
  const text = query.trim();
  if (!searchable(text)) return [];
  return [
    { key: "legal-case-law", group: "Hukuk kaynaklarında ara", label: `İçtihatta ara: “${text}”`, detail: "Yargıtay, Danıştay, AYM kararları", href: `/dashboard/case-law?q=${enc(text)}` },
    { key: "legal-legislation", group: "Hukuk kaynaklarında ara", label: `Mevzuatta ara: “${text}”`, detail: "Kanun ve madde", href: `/dashboard/legislation?q=${enc(text)}` },
    { key: "legal-assistant", group: "Hukuk kaynaklarında ara", label: "Hukuk Asistanı'na sor", detail: "Soru kutusuna yazılır; göndermeden önce düzenleyebilirsiniz", href: `/dashboard/ai?q=${enc(text)}` },
  ];
}

/** Sunucu sonucunu, gösterilecek ve tıklanınca açılacak satırlara çevirir. */
export function buildSearchRows(result: WorkspaceSearchResult | null, query: string): SearchRow[] {
  const rows: SearchRow[] = [];
  for (const item of result?.cases ?? []) {
    rows.push({
      key: `case-${item.id}`,
      group: "Davalar",
      label: item.title,
      detail: joined(item.esas_no || item.case_no, item.court, item.client_name),
      href: `/dashboard/cases/${item.id}`,
    });
  }
  for (const item of result?.clients ?? []) {
    rows.push({
      key: `client-${item.id}`,
      group: "Müvekkiller",
      label: item.full_name,
      detail: joined(item.client_type === "corporate" ? "Tüzel kişi" : "Gerçek kişi", item.phone, item.email),
      href: `/dashboard/clients?q=${enc(item.full_name)}`,
    });
  }
  for (const item of result?.documents ?? []) {
    rows.push({
      key: `document-${item.id}`,
      group: "Belgeler",
      label: item.file_name,
      detail: joined(item.case_title ?? "Davaya bağlı değil", item.uyap_file_no, item.uyap_birim),
      // Davaya bağlı belge davanın sayfasında, bağlı olmayan Dosyalar sayfasında (aynı adla aranmış olarak) açılır.
      href: item.case_id ? `/dashboard/cases/${item.case_id}?tab=evraklar` : `/dashboard/files?q=${enc(item.file_name)}`,
    });
  }
  for (const item of result?.tasks ?? []) {
    rows.push({
      key: `task-${item.id}`,
      group: "Görevler",
      label: item.title,
      detail: joined(TASK_STATUS[item.status] ?? item.status, item.case_title),
      href: item.case_id ? `/dashboard/cases/${item.case_id}?tab=gorevler` : "/dashboard/tasks",
    });
  }
  return [...rows, ...legalShortcuts(query)];
}

/** Satırları, sırayı bozmadan grup başlıklarıyla ayırır. */
export function groupRows(rows: SearchRow[]): Array<{ group: SearchGroup; rows: SearchRow[] }> {
  const groups: Array<{ group: SearchGroup; rows: SearchRow[] }> = [];
  for (const row of rows) {
    const last = groups[groups.length - 1];
    if (last && last.group === row.group) last.rows.push(row);
    else groups.push({ group: row.group, rows: [row] });
  }
  return groups;
}

/** Ok tuşlarıyla gezinme: liste başında ve sonunda döner; liste boşsa seçim yoktur. */
export function moveSelection(current: number, delta: 1 | -1, count: number): number {
  if (count <= 0) return -1;
  if (current < 0) return delta === 1 ? 0 : count - 1;
  return (current + delta + count) % count;
}

const BASE = (import.meta.env?.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export async function searchWorkspace(query: string, signal?: AbortSignal): Promise<WorkspaceSearchResult> {
  const token = inMemoryAccessToken();
  const response = await fetch(`${BASE}/api/office/search?q=${enc(query.trim())}`, {
    credentials: "include",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal,
  });
  if (!response.ok) throw new Error(response.status === 401 ? "Oturumunuz sona ermiş; yeniden giriş yapın." : "Arama şu an yapılamıyor.");
  return (await response.json()) as WorkspaceSearchResult;
}

import { db } from "@/lib/db";

export interface CaseRecord {
  id: string;
  client_id: string | null;
  title: string;
  case_no: string | null;
  esas_no: string | null;
  court: string | null;
  case_type: string | null;
  opponent: string | null;
  status: string;
  opened_at: string | null;
  next_hearing: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}
export interface CaseDocument {
  id: string;
  file_name: string;
  storage_path: string;
  doc_type: string | null;
  /** UYAP ağacındaki klasör yolu ("<dosya> / <evrak türü> / …"); elle yüklenen belgede boş. */
  uyap_path?: string | null;
  created_at: string;
}
export interface CaseTask {
  id: string;
  title: string;
  status: string;
  due_date: string | null;
}
export interface CaseEvent {
  id: string;
  title: string;
  start_at: string;
  location: string | null;
}
export interface CaseCall {
  id: string;
  direction: string;
  status: string;
  started_at: string;
  duration_sec: number;
}
export interface Section<T> {
  rows: T[];
  hasMore: boolean;
  error?: string;
}
export interface CaseDetailData {
  record: CaseRecord;
  clientName: string | null;
  clientError?: string;
  documents: Section<CaseDocument>;
  tasks: Section<CaseTask>;
  events: Section<CaseEvent>;
  calls: Section<CaseCall>;
}
const PAGE_SIZE = 50;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Uses the authenticated office API; ownership stays enforced by RLS. */
export async function loadCaseDetail(id: string, client = db): Promise<CaseDetailData> {
  if (!UUID.test(id)) throw new Error("Geçersiz dava kimliği.");
  const result = await client
    .from("cases")
    .select(
      "id,client_id,title,case_no,esas_no,court,case_type,opponent,status,opened_at,next_hearing,notes,created_at,updated_at",
    )
    .eq("id", id)
    .maybeSingle();
  if (result.error) throw new Error(result.error.message);
  if (!result.data || result.data.id !== id)
    throw new Error("Dava bulunamadı veya bu davaya erişim yetkiniz yok.");
  const record = result.data as CaseRecord;
  async function section<T>(table: string, columns: string, order: string): Promise<Section<T>> {
    try {
      if (table === "case_documents") {
        const rows: T[] = [];
        const seen = new Set<string>();
        for (let offset = 0; ; offset += 1000) {
          const response = await client
            .from(table)
            .select(columns)
            .eq("case_id", id)
            .order(order, { ascending: false })
            .order("id", { ascending: false })
            .range(offset, offset + 999);
          if (response.error) return { rows: [], hasMore: false, error: response.error.message };
          if (!Array.isArray(response.data)) throw new Error("Beklenmeyen belge yanıtı.");
          for (const row of response.data) {
            if (seen.has(row.id)) throw new Error("Belge listesi değişti; yeniden yükleyin.");
            seen.add(row.id);
            rows.push(row);
          }
          if (response.data.length < 1000) return { rows, hasMore: false };
        }
      }
      const response = await client
        .from(table)
        .select(columns)
        .eq("case_id", id)
        .order(order, { ascending: false })
        .limit(PAGE_SIZE + 1);
      if (response.error) return { rows: [], hasMore: false, error: response.error.message };
      if (!Array.isArray(response.data))
        return { rows: [], hasMore: false, error: "Beklenmeyen sunucu yanıtı." };
      return { rows: response.data.slice(0, PAGE_SIZE), hasMore: response.data.length > PAGE_SIZE };
    } catch {
      return { rows: [], hasMore: false, error: "Bu bölüm yüklenemedi. Yenilemeyi deneyin." };
    }
  }
  const [person, documents, tasks, events, calls] = await Promise.all([
    record.client_id
      ? Promise.resolve(
          client.from("clients").select("id,full_name").eq("id", record.client_id).maybeSingle(),
        ).catch(() => ({ data: null, error: { message: "Müvekkil bilgisi yüklenemedi." } }))
      : Promise.resolve({ data: null, error: null }),
    section<CaseDocument>(
      "case_documents",
      "id,file_name,storage_path,doc_type,uyap_path,created_at",
      "created_at",
    ),
    section<CaseTask>("tasks", "id,title,status,due_date", "created_at"),
    section<CaseEvent>("calendar_events", "id,title,start_at,location", "start_at"),
    section<CaseCall>("calls", "id,direction,status,started_at,duration_sec", "started_at"),
  ]);
  return {
    record,
    clientName: person.data?.full_name ?? null,
    clientError:
      person.error?.message ??
      (record.client_id && !person.data ? "Bağlı müvekkil kaydı görüntülenemedi." : undefined),
    documents,
    tasks,
    events,
    calls,
  };
}

export function displayCaseDate(value: string | null, dateOnly = false): string {
  if (!value) return "Belirtilmemiş";
  const date = new Date(dateOnly ? `${value.slice(0, 10)}T12:00:00` : value);
  if (Number.isNaN(date.getTime())) return "Geçersiz tarih";
  return dateOnly ? date.toLocaleDateString("tr-TR") : date.toLocaleString("tr-TR");
}
export const caseStatusLabels: Record<string, string> = {
  active: "Aktif",
  pending: "Beklemede",
  closed: "Kapalı",
};

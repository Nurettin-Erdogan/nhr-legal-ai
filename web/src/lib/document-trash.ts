import { inMemoryAccessToken } from "@/lib/auth-api";

/** Dava belgeleri çöp kutusu: önce çöpe taşınır (geri alınabilir), sonra kalıcı silinir. */

const API_BASE_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface TrashedDocument {
  id: string;
  file_name: string;
  case_id: string | null;
  size_bytes: number | null;
  deleted_at: string;
  /** Kalıcı silinmeye kalan gün. */
  days_left: number;
  /** Bu belgeye dayanan sohbet cevabı sayısı: kalıcı silinirse bu cevaplar da kaldırılır. */
  cited_answers: number;
}

export interface TrashListing {
  retention_days: number;
  documents: TrashedDocument[];
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const count = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.trunc(value) : 0;

export function parseTrashListing(raw: unknown): TrashListing {
  if (!isRecord(raw)) return { retention_days: 30, documents: [] };
  const documents = Array.isArray(raw.documents)
    ? raw.documents.flatMap((item): TrashedDocument[] =>
        isRecord(item) &&
        typeof item.id === "string" &&
        typeof item.file_name === "string" &&
        typeof item.deleted_at === "string"
          ? [
              {
                id: item.id,
                file_name: item.file_name,
                case_id: typeof item.case_id === "string" ? item.case_id : null,
                size_bytes: typeof item.size_bytes === "number" ? item.size_bytes : null,
                deleted_at: item.deleted_at,
                days_left: count(item.days_left),
                cited_answers: count(item.cited_answers),
              },
            ]
          : [],
      )
    : [];
  return { retention_days: count(raw.retention_days) || 30, documents };
}

/** Çöpteki belgenin ne zaman kalıcı silineceğini söyler. */
export function describeRetention(item: Pick<TrashedDocument, "days_left">): string {
  if (item.days_left <= 0) return "Bugün kalıcı silinecek";
  if (item.days_left === 1) return "Yarın kalıcı silinecek";
  return `${item.days_left} gün sonra kalıcı silinecek`;
}

/** Kalıcı silme onayı: geri alınamaz; belgeye dayanan cevaplar da kaldırılır, kullanıcı bunu bilmeli. */
export function permanentDeleteWarning(
  item: Pick<TrashedDocument, "file_name" | "cited_answers">,
): string {
  const lines = [
    `"${item.file_name}" KALICI olarak silinsin mi?`,
    "Belgenin metni ve dosyası silinir. Bu işlem geri alınamaz.",
  ];
  if (item.cited_answers > 0) {
    lines.push(
      `Bu belgeye dayanan ${item.cited_answers} sohbet cevabı da kaldırılır (cevaplar belgeden alıntı içerebilir).`,
    );
  }
  return lines.join("\n\n");
}

async function call<T>(
  path: string,
  method: "GET" | "POST" | "DELETE",
  body?: Record<string, unknown>,
): Promise<T> {
  const token = inMemoryAccessToken();
  const response = await fetch(`${API_BASE_URL}/api/office/documents${path}`, {
    method,
    credentials: "include",
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
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
  return (await response.json()) as T;
}

function checked(id: string): string {
  if (!UUID.test(id)) throw new Error("Geçersiz belge kimliği.");
  return id;
}

// `async`: geçersiz kimlik de senkron fırlatma değil, söz reddi olur (çağıranlar `.catch` bekler).
export async function trashDocument(id: string) {
  return call<{ trashed: boolean }>(`/${checked(id)}/trash`, "POST");
}

export interface BatchTrashResult {
  requested: number;
  trashed: number;
  not_found: number;
  retention_days: number;
}

/** Görünür filtre sonucundaki seçili belgeleri geri alınabilir biçimde çöpe taşır. */
export async function trashDocuments(ids: string[]): Promise<BatchTrashResult> {
  const document_ids = [...new Set(ids.map(checked))];
  if (!document_ids.length) throw new Error("Çöpe taşınacak belge seçilmedi.");
  try {
    return await call<BatchTrashResult>("/trash/batch", "POST", { document_ids });
  } catch (error) {
    // Eski, yeniden başlatılmamış yerel API'ler toplu rotayı henüz
    // bilmeyebilir. Tekli rota aynı yetki kontrolünü ve denetim kaydını
    // kullandığından, yalnızca bu uyumluluk durumunda ona düş.
    if (!(error instanceof Error) || (error as Error & { status?: number }).status !== 404) {
      throw error;
    }

    const workers = Math.min(8, document_ids.length);
    let nextIndex = 0;
    let trashed = 0;
    await Promise.all(
      Array.from({ length: workers }, async () => {
        while (nextIndex < document_ids.length) {
          const id = document_ids[nextIndex++];
          try {
            const result = await call<{ trashed: boolean }>(`/${id}/trash`, "POST");
            if (result.trashed) trashed += 1;
          } catch (itemError) {
            // Aynı anda başka bir sekmede çöpe alınan ya da erişilemeyen
            // belgeler toplu sonuçta "bulunamadı" sayılır; başka hatalar gizlenmez.
            if (!(itemError instanceof Error) || (itemError as Error & { status?: number }).status !== 404) {
              throw itemError;
            }
          }
        }
      }),
    );
    return {
      requested: document_ids.length,
      trashed,
      not_found: document_ids.length - trashed,
      retention_days: 30,
    };
  }
}

export async function restoreDocument(id: string) {
  return call<{ trashed: boolean }>(`/${checked(id)}/restore`, "POST");
}

export async function deleteDocumentForever(id: string) {
  return call<{ deleted: boolean; redacted_answers: number }>(`/${checked(id)}`, "DELETE");
}

export async function listTrash(caseId?: string): Promise<TrashListing> {
  const query = caseId ? `?case_id=${encodeURIComponent(checked(caseId))}` : "";
  return parseTrashListing(await call<unknown>(`/trash${query}`, "GET"));
}

/** UYAP eşitleme doğrulamasının sunucuya yazılması ve okunması (oturumlu istekler; evrak içeriği geçmez). */
import { inMemoryAccessToken } from "@/lib/auth-api";
import { reconcileSaved, type SavedSync, type ServerSyncItem } from "@/lib/uyap-sync-all";
import { parseDetail, type DosyaDetail } from "@/lib/uyap-bridge";

const BASE = (import.meta.env?.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");
const CHUNK = 200;
const SAVE_TIMEOUT_MS = 60_000;

const headers = (json: boolean): Record<string, string> => {
  const token = inMemoryAccessToken();
  return {
    ...(json ? { "Content-Type": "application/json" } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
};

/** Ağ yanıt vermese de aktarım/kayıt durumu sonsuza kadar çalışıyor görünmesin. */
async function postBounded(path: string, body: unknown): Promise<Response> {
  try {
    return await fetch(`${BASE}${path}`, {
      method: "POST",
      credentials: "include",
      headers: headers(true),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(SAVE_TIMEOUT_MS),
    });
  } catch {
    throw new Error(
      "JurisAI sunucusuna ulaşılamadı veya kayıt isteği zaman aşımına uğradı; sonuç kaydedilmiş sayılmadı.",
    );
  }
}

/** Raporu parça parça kaydeder; kaydedilemezse hata fırlatır (aktarımın kendisi bundan etkilenmez). */
export async function saveSyncReport(items: ServerSyncItem[]): Promise<SavedSync> {
  const total: SavedSync = { saved: 0, downgraded: [], unmatched: 0 };
  for (let start = 0; start < items.length; start += CHUNK) {
    const part = items.slice(start, start + CHUNK);
    const response = await postBounded("/api/office/uyap/sync-report", { items: part });
    if (!response.ok)
      throw new Error(
        response.status === 401
          ? "Oturumunuz sona ermiş; yeniden giriş yapın."
          : "Doğrulama sonucu JurisAI'a kaydedilemedi.",
      );
    const saved = reconcileSaved(part, await response.json().catch(() => null));
    total.saved += saved.saved;
    total.unmatched += saved.unmatched;
    total.downgraded.push(...saved.downgraded);
  }
  return total;
}

export interface SyncStatusRow {
  case_id: string;
  esas: string | null;
  birim: string | null;
  complete: boolean;
  found_count: number;
  missing_count: number;
  server_documents: number;
  checked_at: string;
}

export interface SyncStatus {
  files: SyncStatusRow[];
  summary: { files: number; complete: number; missing: number };
}

const num = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.trunc(value) : 0;

/** Sunucudaki son doğrulama durumu; okunamazsa null (sayfa bunu "bilinmiyor" diye gösterir, sıfır diye değil). */
export async function loadSyncStatus(signal?: AbortSignal): Promise<SyncStatus | null> {
  try {
    const response = await fetch(`${BASE}/api/office/uyap/sync-status`, {
      credentials: "include",
      headers: headers(false),
      signal,
    });
    if (!response.ok) return null;
    const body = (await response.json()) as Record<string, unknown>;
    const rows = Array.isArray(body.files) ? body.files : [];
    const files: SyncStatusRow[] = rows.flatMap((raw) => {
      const row = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
      if (typeof row.case_id !== "string") return [];
      return [
        {
          case_id: row.case_id,
          esas: typeof row.esas === "string" ? row.esas : null,
          birim: typeof row.birim === "string" ? row.birim : null,
          complete: row.complete === true,
          found_count: num(row.found_count),
          missing_count: num(row.missing_count),
          server_documents: num(row.server_documents),
          checked_at: typeof row.checked_at === "string" ? row.checked_at : "",
        },
      ];
    });
    return {
      files,
      summary: {
        files: files.length,
        complete: files.filter((row) => row.complete).length,
        missing: files.reduce((sum, row) => sum + row.missing_count, 0),
      },
    };
  } catch {
    return null;
  }
}

/** Bir dosyanın evrak dışı bilgilerini (taraflar, safahat, dosya hesabı…) hesaba kaydeder. Sunucu eksiksizliği kendisi yeniden hesaplar. */
export async function saveCaseDetail(
  detail: DosyaDetail,
): Promise<{ complete: boolean; caseCreated: boolean }> {
  const response = await postBounded("/api/office/uyap/case-detail", {
    esas: detail.who.esas,
    birim: detail.who.birim,
    tabs: detail.tabs,
    problems: detail.problems,
    complete: detail.complete,
  });
  if (response.status === 401) throw new Error("Oturumunuz sona ermiş; yeniden giriş yapın.");
  const body = (await response.json().catch(() => null)) as Record<string, unknown> | null;
  if (!response.ok)
    throw new Error(
      typeof body?.detail === "string" ? body.detail : "Dosya bilgileri kaydedilemedi.",
    );
  if (body?.status !== "saved") {
    const reason =
      body?.status === "ambiguous"
        ? "aynı esas no ve birimde birden çok dava var"
        : "esas no ya da birim okunamadı";
    throw new Error(`Dosya bilgileri hiçbir davaya yazılmadı: ${reason}.`);
  }
  return { complete: body.complete === true, caseCreated: body.case_created === true };
}

export interface StoredCaseDetail {
  detail: DosyaDetail;
  fetchedAt: string;
  /** Sunucunun kendi hesabıyla her tablo UYAP'ın sayısıyla tutuyor. */
  complete: boolean;
}

/** Davanın saklanan UYAP dosya bilgileri; kayıt yoksa (ya da okunamazsa) null. */
export async function loadCaseDetail(
  caseId: string,
  signal?: AbortSignal,
): Promise<StoredCaseDetail | null> {
  try {
    const response = await fetch(
      `${BASE}/api/office/uyap/case-detail/${encodeURIComponent(caseId)}`,
      { credentials: "include", headers: headers(false), signal },
    );
    if (!response.ok) return null;
    const body = (await response.json()) as Record<string, unknown>;
    const parsed = parseDetail({
      who: {},
      tabs: body.tabs,
      problems: body.problems,
      complete: body.complete,
    });
    if (!parsed) return null;
    return {
      detail: parsed,
      fetchedAt: typeof body.fetched_at === "string" ? body.fetched_at : "",
      complete: parsed.complete,
    };
  } catch {
    return null;
  }
}

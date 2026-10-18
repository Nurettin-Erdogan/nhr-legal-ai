/**
 * UYAP sayfası tanınmadığında (liste ya da dosya ağacı okunamadı) eklentiden sayfanın YAPI özetini alıp sahibin hesabına
 * kaydeder (2026-10-18). Avukat Portalı gibi canlıda hiç görülmemiş sayfalar ilk gerçek kullanımda düzeltilebilsin diye.
 * Özet içerik, ad, dosya numarası ya da bağlantı değeri taşımaz (eklenti maskeler; sunucu ayrıca denetler). Aynı sorun türü
 * bir sayfa oturumunda bir kez gönderilir; hata kullanıcının işini hiçbir zaman bozmaz.
 */
import { inMemoryAccessToken } from "@/lib/auth-api";
import { bridgeRequest } from "@/lib/uyap-bridge";

const BASE = (import.meta.env?.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

/** Yapı özeti gönderilecek okuma hataları: sayfa düzeni beklenenden farklı olabilir. */
export const DIAGNOSE_CODES = new Set(["no_list", "query_failed", "no_tree", "open_failed", "no_content", "cannot_close", "no_dialog"]);

const sent = new Set<string>();

export async function reportUyapProblem(
  code: string | undefined,
  context: Record<string, string | number | boolean> = {},
): Promise<boolean> {
  if (!code || !DIAGNOSE_CODES.has(code) || sent.has(code)) return false;
  sent.add(code);
  try {
    const diagnosis = (await bridgeRequest<{ reports?: unknown[] }>("DIAGNOSE", {}, 15000)) as { ok?: boolean; reports?: unknown[] };
    if (!diagnosis?.ok || !Array.isArray(diagnosis.reports)) return false;
    const token = inMemoryAccessToken();
    const response = await fetch(`${BASE}/api/office/uyap/diagnostics`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ code, context, reports: diagnosis.reports.slice(0, 8) }),
      signal: AbortSignal.timeout(15000),
    });
    return response.ok;
  } catch {
    return false;
  }
}

/** Testler için: gönderilmiş sorun türlerini unutur. */
export function resetUyapProblemReports(): void {
  sent.clear();
}

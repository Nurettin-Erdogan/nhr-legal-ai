import { inMemoryAccessToken } from "@/lib/auth-api";

const BASE = (import.meta.env?.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export interface ExportSummary {
  clients: number;
  cases: number;
  conversations: number;
  truncated: string[];
}

/** İndirilen dışa aktarmanın okunur özeti; bozuk gövdede null. */
export function summarizeExport(raw: unknown): ExportSummary | null {
  if (typeof raw !== "object" || raw === null) return null;
  const data = raw as {
    office?: Record<string, unknown>;
    conversations?: unknown;
    truncated_tables?: unknown;
  };
  if (typeof data.office !== "object" || data.office === null) return null;
  const size = (value: unknown) => (Array.isArray(value) ? value.length : 0);
  return {
    clients: size(data.office.clients),
    cases: size(data.office.cases),
    conversations: size(data.conversations),
    truncated: Array.isArray(data.truncated_tables)
      ? data.truncated_tables.filter((item): item is string => typeof item === "string")
      : [],
  };
}

export function exportMessage(summary: ExportSummary): string {
  const base = `Dosya indirildi: ${summary.clients} müvekkil, ${summary.cases} dava, ${summary.conversations} sohbet.`;
  return summary.truncated.length
    ? `${base} Uyarı: ${summary.truncated.join(", ")} kayıtları sınır nedeniyle eksik olabilir.`
    : base;
}

/** `/api/office/account/export` → tarayıcıda "jurisai-verilerim.json" olarak kaydeder; sonuç özetini döndürür. */
export async function downloadMyData(): Promise<string> {
  const token = inMemoryAccessToken();
  let response: Response;
  try {
    response = await fetch(`${BASE}/api/office/account/export`, {
      credentials: "include",
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
  } catch {
    throw new Error("Sunucuya ulaşılamadı.");
  }
  if (!response.ok)
    throw new Error(
      response.status === 401
        ? "Oturumunuz sona ermiş; yeniden giriş yapın."
        : `Veriler indirilemedi (${response.status}).`,
    );
  const text = await response.text();
  let summary: ExportSummary | null = null;
  try {
    summary = summarizeExport(JSON.parse(text));
  } catch {
    summary = null;
  }
  if (!summary) throw new Error("Sunucudan geçersiz bir dışa aktarma geldi.");
  const url = URL.createObjectURL(new Blob([text], { type: "application/json;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "jurisai-verilerim.json";
  document.body.appendChild(anchor);
  try {
    anchor.click();
  } finally {
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return exportMessage(summary);
}

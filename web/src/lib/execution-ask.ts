/**
 * Dosyalar arası soru: `/api/office/execution/ask` yanıtının okunması.
 *
 * Sunucu soruyu bir dil modeline sormaz; bilinen kalıpları süzgece çevirir ve UYAP kayıtlarına uygular. Yanıt, sorunun nasıl
 * anlaşıldığını (`understood`) ve her eşleşen dosya için eşleşmeyi sağlayan kayıt satırlarını (`facts`) taşır.
 */
import { inMemoryAccessToken } from "@/lib/auth-api";

export interface AskRow {
  caseId: string;
  fileNo: string | null;
  court: string;
  status: string | null;
  creditors: string[];
  debtors: string[];
  lastActivity: string | null;
  daysSinceLast: number | null;
  /** Eşleşmeyi sağlayan UYAP kayıtları ("Araç sorgusu: VAR · 05.10.2026 (…)"); sunucunun yazdığı gibi. */
  facts: string[];
}

export interface AskAnswer {
  /** Soru bir süzgece çevrilebildi mi; çevrilemediyse satır yoktur ve `note` nedenini söyler. */
  ok: boolean;
  understood: string[];
  totalFiles: number;
  matched: number;
  /** UYAP bilgisi çekilmediği için bu soruda değerlendirilemeyen dosya sayısı. */
  notEvaluated: number;
  rows: AskRow[];
  note: string | null;
  examples: string[];
}

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): string => (typeof value === "string" ? value : "");
const count = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.trunc(value) : 0);
const strings = (value: unknown): string[] => (Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim() !== "") : []);

/** Sunucu yanıtını güvenli biçimde okur; bozuk satır atılır, sayfa çökmez. */
export function parseAnswer(raw: unknown): AskAnswer {
  const body = isRecord(raw) ? raw : {};
  const rows = (Array.isArray(body.rows) ? body.rows : []).flatMap((item): AskRow[] => {
    if (!isRecord(item) || !text(item.case_id)) return [];
    const days = item.days_since_last;
    return [{
      caseId: text(item.case_id),
      fileNo: text(item.file_no) || null,
      court: text(item.court),
      status: text(item.status) || null,
      creditors: strings(item.creditors),
      debtors: strings(item.debtors),
      lastActivity: text(item.last_activity) || null,
      daysSinceLast: typeof days === "number" && Number.isFinite(days) && days >= 0 ? Math.trunc(days) : null,
      facts: strings(item.facts),
    }];
  });
  return {
    ok: body.ok === true,
    understood: strings(body.understood),
    totalFiles: count(body.total_files),
    // Sayı, listeden kısa olamaz; sunucu satırları 200'de keser, o zaman `matched` daha büyüktür.
    matched: Math.max(count(body.matched), rows.length),
    notEvaluated: count(body.not_evaluated),
    rows,
    note: text(body.note) || null,
    examples: strings(body.examples),
  };
}

/** Sonuç başlığı: "18 dosyadan 7'si eşleşti" yerine ek gerektirmeyen yazım. */
export function answerHeadline(answer: AskAnswer): string {
  if (!answer.ok) return "Soru anlaşılamadı";
  const shown = answer.rows.length < answer.matched ? ` (ilk ${answer.rows.length} dosya gösteriliyor)` : "";
  return `Eşleşen dosya: ${answer.matched} / ${answer.totalFiles}${shown}`;
}

const BASE = (import.meta.env?.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export async function askExecution(question: string, signal?: AbortSignal): Promise<AskAnswer> {
  const token = inMemoryAccessToken();
  let response: Response;
  try {
    response = await fetch(`${BASE}/api/office/execution/ask`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ question }),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error("Sunucuya ulaşılamadı.");
  }
  if (response.status === 401) throw new Error("Oturumunuz sona ermiş; yeniden giriş yapın.");
  if (response.status === 422) throw new Error("Soru en az 2, en çok 300 karakter olmalı.");
  if (!response.ok) throw new Error("Dosyalar şu an sorgulanamıyor.");
  return parseAnswer(await response.json().catch(() => null));
}

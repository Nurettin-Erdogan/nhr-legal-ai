/**
 * OCR ve dilekçe üretimi. Eskiden Lovable/Gemini sunucu işleviydi; artık yerel FastAPI uç noktalarını
 * çağırır (`/api/office-ai/ocr`, `/petition`). Çağıranlar `{ data }` biçimini kullanmaya devam eder.
 */
import { inMemoryAccessToken } from "@/lib/auth-api";
import { saveTextDocument } from "@/lib/office-api";

const API_BASE_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

async function post<T>(path: string, body: unknown): Promise<T> {
  const token = inMemoryAccessToken();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  }).catch(() => {
    throw new Error("Sunucuya ulaşılamadı. API servisinin çalıştığını kontrol edin.");
  });
  if (!response.ok) {
    let detail = `İstek başarısız oldu (${response.status}).`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      /* JSON değil */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

/** Görsel/PDF sayfalarını yerel OCR motoruyla metne çevirir. */
export const ocrImages = ({ data }: { data: { images: string[]; fileName?: string } }) =>
  post<{ text: string; pages: number }>("/api/office-ai/ocr", { images: data.images });

/** OCR ile okunmuş belge metninden, korpus kaynaklarına atıflı dilekçe taslağı üretir. */
export const generatePetitionFromText = ({
  data,
}: {
  data: { text: string; petitionType: string; notes?: string; fileName?: string };
}) =>
  post<{ content: string; label: string }>("/api/office-ai/petition", {
    text: data.text,
    petition_type: data.petitionType,
    notes: data.notes ?? null,
    file_name: data.fileName ?? null,
  });

/** OCR metnini kullanıcının belge deposuna kaydeder. */
export const saveOcrDocument = ({
  data,
}: {
  data: { fileName: string; text: string; mimeType?: string; sizeBytes?: number };
}) => saveTextDocument({ ...data, source: "ocr" });

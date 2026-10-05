/**
 * Büro AI ve belge uç noktalarının (`/api/office-ai/*`, `/api/public/*`) istemcisi.
 * Üretim yerel modelle FastAPI'de yapılır; bu dosya yalnız HTTP çağrılarını sarar.
 */
import { currentUser, inMemoryAccessToken } from "@/lib/auth-api";
import { db } from "@/lib/db";
import { parseUyapMeta, safeFileName } from "@/lib/uyap";

const API_BASE_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

async function post<T>(path: string, body: unknown, options?: { auth?: boolean }): Promise<T> {
  const token = inMemoryAccessToken();
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(options?.auth !== false && token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error("Sunucuya ulaşılamadı. API servisinin çalıştığını kontrol edin.");
  }
  if (!response.ok) {
    let detail = `İstek başarısız oldu (${response.status}).`;
    try {
      const payload = (await response.json()) as { detail?: unknown; error?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
      else if (typeof payload.error === "string") detail = payload.error;
    } catch {
      /* JSON değil */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export interface OfficeSource {
  marker: string;
  reference: string;
  source_url: string | null;
  verification: string;
}

export interface ModuleResult {
  id: string;
  title: string;
  output: string;
  model: string;
  sources: OfficeSource[];
  unverified_references: string[];
}

export const runOfficeModule = (input: {
  module: string;
  prompt: string;
  title?: string;
  docIds?: string[];
  caseId?: string | null;
  projectId?: string | null;
}) =>
  post<ModuleResult>("/api/office-ai/run", {
    module: input.module,
    prompt: input.prompt,
    title: input.title || null,
    doc_ids: input.docIds ?? [],
    case_id: input.caseId ?? null,
    project_id: input.projectId ?? null,
  });

export const generateDocument = (input: {
  docType: string;
  title?: string;
  parties?: string[];
  subject: string;
  details?: string;
  docIds?: string[];
}) =>
  post<{ content: string; sources: OfficeSource[]; unverified_references: string[] }>(
    "/api/office-ai/document",
    {
      doc_type: input.docType,
      title: input.title || null,
      parties: input.parties ?? [],
      subject: input.subject,
      details: input.details || null,
      doc_ids: input.docIds ?? [],
    },
  );

export const submitApplication = (input: {
  ad_soyad: string;
  telefon: string | null;
  eposta: string | null;
  hukuk_alani: string | null;
  konu: string;
  sohbet_ozeti: string | null;
  /** KVKK: aydınlatma metni okundu onayı ve gösterilen metnin sürümü (sunucu onaysız başvuru almaz). */
  aydinlatma_okundu: boolean;
  aydinlatma_surum: string;
}) => post<{ ok: true }>("/api/public/basvuru", input, { auth: false });

/** Kullanıcının kendi belge deposuna (kişisel çalışma alanı) metin belgesi kaydeder. */
export async function saveTextDocument(input: {
  fileName: string;
  text: string;
  mimeType?: string;
  sizeBytes?: number;
  source?: string;
  docType?: string;
}): Promise<{ id: string | null }> {
  const user = await currentUser();
  if (!user) throw new Error("Oturum gerekli");
  const text = input.text.trim();
  if (!text) throw new Error("Kaydedilecek metin yok");

  const fileName = safeFileName(input.fileName || "belge.txt");
  const path = `${user.id}/${new Date().getFullYear()}/${crypto.randomUUID()}-${fileName.replace(/\.[^.]+$/, "")}.txt`;
  const { error: uploadError } = await db.storage
    .from("case-files")
    .upload(path, new Blob([text], { type: "text/plain;charset=utf-8" }));
  if (uploadError) throw new Error("Metin depoya yüklenemedi");

  const meta = parseUyapMeta(fileName, text);
  const { data, error } = await db
    .from("case_documents")
    .insert({
      owner_id: user.id,
      file_name: fileName,
      storage_path: path,
      size_bytes: input.sizeBytes ?? new TextEncoder().encode(text).length,
      source: input.source ?? "ocr",
      mime_type: input.mimeType ?? "text/plain",
      content_excerpt: text.slice(0, 100000),
      ...meta,
      doc_type: input.docType ?? meta.doc_type,
    })
    .select("id")
    .single();
  if (error) {
    await db.storage.from("case-files").remove([path]);
    throw new Error("Belge kaydedilemedi");
  }
  return { id: data?.id ?? null };
}

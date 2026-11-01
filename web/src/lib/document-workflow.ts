/** Geçici belge seçimi: içerik URL'ye ya da kalıcı tarayıcı deposuna yazılmaz. */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TTL = 30 * 60 * 1000;
export const DOCUMENT_MODES = {
  analysis: {
    label: "Belge analizi",
    module: "document_analysis",
    max: 2000,
    prompt: "Seçili belgelerdeki olguları ve önemli bilgileri özetle.",
  },
  summary: {
    label: "Özetle",
    module: "auto_summary",
    max: 2000,
    prompt: "Seçili belgeleri ayrı başlıklar altında özetle.",
  },
  risk: {
    label: "Risk incelemesi",
    module: "risk_analysis",
    max: 2000,
    prompt: "Seçili belgelerdeki olguları kaynaklara göre süre, ispat ve usul açısından incele.",
  },
  draft: { label: "Belge hazırla", module: "draft", max: 2000, prompt: "" },
} as const;
export type DocumentMode = keyof typeof DOCUMENT_MODES;
export interface DocumentContext {
  ids: string[];
  caseId?: string;
  officeProjectId?: string;
  createdAt: number;
}
interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}
const contextKey = (owner: string, key: string) => `jurisai.document-context:${owner}:${key}`;

export function saveDocumentContext(
  owner: string,
  ids: string[],
  caseId?: string,
  storage: StorageLike = sessionStorage,
  officeProjectId?: string,
): string {
  if (!owner || !ids.length || ids.some((id) => !UUID.test(id)) || (caseId && !UUID.test(caseId)))
    throw new Error("Belge seçimi geçersiz.");
  if ((officeProjectId && !UUID.test(officeProjectId)) || (caseId && officeProjectId))
    throw new Error("Proje belge kapsamı geçersiz.");
  if (ids.length > 2000) throw new Error("Bir kuyruk işi için en fazla 2000 belge seçebilirsiniz.");
  const key = crypto.randomUUID();
  storage.setItem(
    contextKey(owner, key),
    JSON.stringify({ ids: [...new Set(ids)], caseId, officeProjectId, createdAt: Date.now() }),
  );
  return key;
}

export function readDocumentContext(
  owner: string,
  key: string,
  storage: StorageLike = sessionStorage,
  now = Date.now(),
): DocumentContext | null {
  if (!owner || !UUID.test(key)) return null;
  try {
    const raw = storage.getItem(contextKey(owner, key));
    if (!raw) return null;
    const value = JSON.parse(raw);
    if (
      !Array.isArray(value.ids) ||
      !value.ids.length ||
      value.ids.length > 2000 ||
      value.ids.some((id: unknown) => typeof id !== "string" || !UUID.test(id)) ||
      (value.caseId !== undefined &&
        (typeof value.caseId !== "string" || !UUID.test(value.caseId))) ||
      (value.officeProjectId !== undefined &&
        (typeof value.officeProjectId !== "string" || !UUID.test(value.officeProjectId))) ||
      (value.caseId && value.officeProjectId) ||
      typeof value.createdAt !== "number" ||
      !Number.isFinite(value.createdAt) ||
      now < value.createdAt ||
      now - value.createdAt > TTL
    ) {
      storage.removeItem(contextKey(owner, key));
      return null;
    }
    return {
      ids: [...new Set<string>(value.ids)],
      caseId: value.caseId,
      ...(value.officeProjectId ? { officeProjectId: value.officeProjectId } : {}),
      createdAt: value.createdAt,
    };
  } catch {
    return null;
  }
}

export function workflowPath(mode: DocumentMode, context: string): string {
  return `${mode === "draft" ? "/dashboard/drafts" : "/dashboard/ai"}?${new URLSearchParams({ ...(mode === "draft" ? {} : { mode }), context })}`;
}

/** Dava belgelerinin cevaba katılma durumu: sessizce yok sayılan belge olmaması için gösterilir. */

export interface DocumentScope {
  total: number;
  ready: number;
  pending: number;
  /** OCR ile okunan hazır belge sayısı: okuma hataları olabilir. */
  ocr: number;
  failed: { file_name: string; reason: string }[];
  /** Soru yalnız dava belgelerinden cevaplandı; hukuk kaynaklarına bakılmadı. */
  fileOnly?: boolean;
}

/** Yalnız belgelerden cevaplanan soruda gösterilen not: hukuki değerlendirme için ne yapılacağını söyler. */
export const FILE_ONLY_NOTE =
  "Bu soru yalnız dava belgelerinizden cevaplandı; kanun ve içtihat kaynaklarına bakılmadı. Hukuki değerlendirme için soruya kanun, madde ya da içtihat ekleyin veya Hukuk Asistanı'nı kullanın.";

export interface CaseDocumentIndexItem {
  id: string;
  file_name: string;
  /** "ready" aranabilir; "failed" okunamadı (neden `error`); diğerleri henüz işlenmedi. */
  status: string;
  error: string | null;
  /** Metin OCR ile okundu; okuma hataları olabilir. */
  ocr: boolean;
  chunk_count: number;
  semantic_ready: boolean;
}

export interface CaseDocumentIndex {
  total: number;
  ready: number;
  documents: CaseDocumentIndexItem[];
}

/** Kullanıcı belgesi atıfı resmî kaynak değildir; belgede yazanı aktarır. */
export const USER_DOCUMENT_NOTE =
  "Kullanıcı belgesi atıfları belgede yazanı aktarır. Dilekçe gibi belgelerdeki ifadeler bir tarafın iddiasıdır; hukuki dayanak ya da resmî kaynak değildir.";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const count = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.trunc(value) : 0;

export function parseDocumentScope(raw: unknown): DocumentScope | undefined {
  if (!isRecord(raw)) return undefined;
  const failed = Array.isArray(raw.failed)
    ? raw.failed.flatMap((item) =>
        isRecord(item) && typeof item.file_name === "string"
          ? [
              {
                file_name: item.file_name,
                reason: typeof item.reason === "string" ? item.reason : "Belge işlenemedi.",
              },
            ]
          : [],
      )
    : [];
  return {
    total: count(raw.total),
    ready: count(raw.ready),
    pending: count(raw.pending),
    ocr: count(raw.ocr),
    failed,
    ...(raw.file_only === true ? { fileOnly: true } : {}),
  };
}

export interface ScopeSummary {
  tone: "ok" | "warn" | "empty";
  lines: string[];
}

/** Cevabın dayandığı belge kapsamını kullanıcıya anlatan satırlar. */
export function describeDocumentScope(scope: DocumentScope): ScopeSummary {
  if (scope.total === 0) {
    return {
      tone: "empty",
      lines: ["Bu davaya bağlı belge yok; cevap yalnızca hukuk kaynaklarına dayanır."],
    };
  }
  const lines = [`${scope.total} belgeden ${scope.ready} tanesi aranabildi.`];
  if (scope.fileOnly) lines.push(FILE_ONLY_NOTE);
  if (scope.pending > 0) {
    lines.push(`${scope.pending} belge henüz işlenmedi; cevaba katılmamış olabilir.`);
  }
  for (const item of scope.failed) {
    lines.push(`${item.file_name} okunamadı: ${item.reason}`);
  }
  if (scope.ocr > 0) {
    lines.push(
      `${scope.ocr} belge OCR ile okundu; okuma hataları olabilir. Tutar, tarih ve numaraları belgenin aslından doğrulayın.`,
    );
  }
  const complete = scope.ready === scope.total && scope.ocr === 0;
  return { tone: complete ? "ok" : "warn", lines };
}

export function parseCaseDocumentIndex(raw: unknown): CaseDocumentIndex {
  if (!isRecord(raw)) return { total: 0, ready: 0, documents: [] };
  const documents = Array.isArray(raw.documents)
    ? raw.documents.flatMap((item): CaseDocumentIndexItem[] =>
        isRecord(item) && typeof item.id === "string" && typeof item.file_name === "string"
          ? [
              {
                id: item.id,
                file_name: item.file_name,
                status: typeof item.status === "string" ? item.status : "pending",
                error: typeof item.error === "string" ? item.error : null,
                ocr: item.ocr === true,
                chunk_count: count(item.chunk_count),
                semantic_ready: item.semantic_ready === true,
              },
            ]
          : [],
      )
    : [];
  return {
    total: documents.length,
    ready: documents.filter((item) => item.status === "ready").length,
    documents,
  };
}

export function documentStatusLabel(item: Pick<CaseDocumentIndexItem, "status">): string {
  if (item.status === "ready") return "Aranabilir";
  if (item.status === "failed") return "Okunamadı";
  return "Bekliyor";
}

/** Yeniden işletmenin anlamlı olduğu durumlar: başarısız ya da henüz işlenmemiş belge. */
export const canReindex = (item: Pick<CaseDocumentIndexItem, "status">): boolean =>
  item.status !== "ready";

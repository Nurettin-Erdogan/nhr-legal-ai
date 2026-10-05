/**
 * Dava belgelerinin yan yana karşılaştırması (arayüzden bağımsız mantık).
 *
 * Sunucu (`/api/office/cases/{id}/documents/compare`) iki belgenin metin farkını belirleyici biçimde hesaplar; yapay zekâ ya da
 * hukuki yorum yoktur. Burada yanıt savunmacı biçimde ayrıştırılır ve uzun "aynı" bölümler gösterim için katlanır.
 */

export interface WordPiece {
  op: "equal" | "delete" | "insert";
  text: string;
}

export type DiffBlock =
  | { kind: "equal"; units: string[] }
  | { kind: "removed"; text: string }
  | { kind: "added"; text: string }
  | { kind: "changed"; left: string; right: string; words: WordPiece[] };

export interface CompareDocument {
  id: string;
  fileName: string;
  /** Metin OCR ile okundu: farkların bir kısmı okuma hatası olabilir. */
  ocr: boolean;
}

export interface Counts {
  equal: number;
  changed: number;
  removed: number;
  added: number;
}

export interface CompareResult {
  left: CompareDocument;
  right: CompareDocument;
  similarity: number;
  leftUnits: number;
  rightUnits: number;
  counts: Counts;
  blocks: DiffBlock[];
}

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const num = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.trunc(value) : 0);
const str = (value: unknown): string => (typeof value === "string" ? value : "");
const strings = (value: unknown): string[] => (Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []);

function parseDocument(raw: unknown): CompareDocument | null {
  if (!isRecord(raw) || typeof raw.id !== "string" || !raw.id) return null;
  return { id: raw.id, fileName: str(raw.file_name) || "Adsız belge", ocr: raw.ocr === true };
}

function parseBlock(raw: unknown): DiffBlock | null {
  if (!isRecord(raw)) return null;
  if (raw.kind === "equal") {
    const units = strings(raw.units);
    return units.length ? { kind: "equal", units } : null;
  }
  if ((raw.kind === "removed" || raw.kind === "added") && typeof raw.text === "string") return { kind: raw.kind, text: raw.text };
  if (raw.kind === "changed" && typeof raw.left === "string" && typeof raw.right === "string") {
    const words: WordPiece[] = Array.isArray(raw.words)
      ? raw.words.flatMap((piece) =>
          isRecord(piece) && (piece.op === "equal" || piece.op === "delete" || piece.op === "insert") && typeof piece.text === "string"
            ? [{ op: piece.op, text: piece.text }]
            : [],
        )
      : [];
    return { kind: "changed", left: raw.left, right: raw.right, words };
  }
  return null;
}

/** Geçersiz bir yanıtta `null`: yarım bir fark "fark yok" gibi gösterilmez. */
export function parseCompare(raw: unknown): CompareResult | null {
  if (!isRecord(raw)) return null;
  const left = parseDocument(raw.left);
  const right = parseDocument(raw.right);
  if (!left || !right || !Array.isArray(raw.blocks)) return null;
  const blocks = raw.blocks.map(parseBlock);
  if (blocks.some((block) => block === null)) return null;
  const counts = isRecord(raw.counts) ? raw.counts : {};
  return {
    left,
    right,
    similarity: typeof raw.similarity === "number" && raw.similarity >= 0 && raw.similarity <= 1 ? raw.similarity : 0,
    leftUnits: num(raw.left_units),
    rightUnits: num(raw.right_units),
    counts: { equal: num(counts.equal), changed: num(counts.changed), removed: num(counts.removed), added: num(counts.added) },
    blocks: blocks as DiffBlock[],
  };
}

export const hasDifferences = (counts: Counts): boolean => counts.changed + counts.removed + counts.added > 0;

export function describeCounts(counts: Counts): string {
  if (!hasDifferences(counts)) return "Metin farkı bulunamadı: iki belgenin cümleleri aynı.";
  const parts = [
    counts.changed ? `${counts.changed} cümle değişti` : "",
    counts.added ? `${counts.added} cümle eklendi` : "",
    counts.removed ? `${counts.removed} cümle silindi` : "",
  ].filter(Boolean);
  return `${parts.join(", ")}; ${counts.equal} cümle aynı.`;
}

export type FoldedItem =
  | { kind: "equal"; units: string[] }
  | { kind: "fold"; units: string[] }
  | { kind: "removed"; text: string }
  | { kind: "added"; text: string }
  | { kind: "changed"; left: string; right: string; words: WordPiece[] };

/**
 * Aynı cümlelerden oluşan uzun bölümleri katlar: değişikliğin hemen öncesindeki/sonrasındaki `context` cümle görünür kalır,
 * ortası `fold` olur (tıklayınca açılır). Belgenin başındaki ve sonundaki aynı bölümde yalnız değişikliğe bakan taraf gösterilir.
 */
export function foldBlocks(blocks: DiffBlock[], context = 1): FoldedItem[] {
  const out: FoldedItem[] = [];
  blocks.forEach((block, index) => {
    if (block.kind !== "equal") {
      out.push(block);
      return;
    }
    const lead = index > 0 ? context : 0;
    const trail = index < blocks.length - 1 ? context : 0;
    if (block.units.length <= lead + trail + 1) {
      out.push({ kind: "equal", units: block.units });
      return;
    }
    if (lead) out.push({ kind: "equal", units: block.units.slice(0, lead) });
    out.push({ kind: "fold", units: block.units.slice(lead, block.units.length - trail) });
    if (trail) out.push({ kind: "equal", units: block.units.slice(block.units.length - trail) });
  });
  return out;
}

const BASE = (import.meta.env?.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export class CompareError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
  }
}

/** `token`: bellekteki erişim anahtarı (çerez gönderilmeyen ortamlar için); çağıran verir, böylece modül bağımsız kalır. */
export async function compareDocuments(
  caseId: string,
  leftId: string,
  rightId: string,
  options: { token?: string | null; signal?: AbortSignal } = {},
): Promise<CompareResult> {
  const params = new URLSearchParams({ left: leftId, right: rightId });
  let response: Response;
  try {
    response = await fetch(`${BASE}/api/office/cases/${encodeURIComponent(caseId)}/documents/compare?${params}`, {
      credentials: "include",
      signal: options.signal,
      headers: options.token ? { Authorization: `Bearer ${options.token}` } : undefined,
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw new CompareError("Sunucuya ulaşılamadı.");
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* JSON değil */
    }
    const fallback =
      response.status === 401 ? "Oturumunuz sona ermiş; yeniden giriş yapın." : response.status === 413 ? "Belgeler karşılaştırma için çok uzun." : `Karşılaştırma tamamlanamadı (${response.status}).`;
    throw new CompareError(detail || fallback, response.status);
  }
  const result = parseCompare(await response.json().catch(() => null));
  if (!result) throw new CompareError("Sunucudan geçersiz bir karşılaştırma yanıtı geldi.");
  return result;
}

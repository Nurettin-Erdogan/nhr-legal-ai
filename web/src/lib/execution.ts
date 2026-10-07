/**
 * İcra dosyaları: sunucudaki `/api/office/execution/files` yanıtının okunması ve gösterimi.
 *
 * İcra dosyası, UYAP aktarımında oluşan dava kaydıdır (mahkemesi bir icra dairesi). Tutarlar makbuz metninden okunur;
 * okunamayan makbuz toplama girmez ve bu her yerde sayıyla belirtilir (sıfır diye gösterilmez).
 */
import { inMemoryAccessToken } from "@/lib/auth-api";

export interface ReceiptSummary {
  count: number;
  read: number;
  /** Okunabilen makbuzların toplamı ("350.50"); hiçbiri okunamadıysa null. */
  total: string | null;
}

export interface ExecutionFile {
  case_id: string;
  file_no: string | null;
  court: string;
  /** "takip": icra dairesi dosyası; "mahkeme": icra hukuk/ceza mahkemesi (şikayet, itiraz). */
  kind: "takip" | "mahkeme";
  documents: number;
  first_date: string | null;
  last_date: string | null;
  counts: Record<string, number>;
  receipts: Record<string, ReceiptSummary>;
  /** UYAP dosya listesindeki üst veri ve son eşitleme doğrulaması; hiç doğrulanmadıysa null. */
  uyap: UyapInfo | null;
  /** UYAP'tan çekilen dosya bilgisi (taraflar, safahat, dosya hesabı…); çekilmediyse null. */
  detail: ExecutionDetail | null;
}

export interface ExecutionDetail {
  /** Her tablo UYAP'ın söylediği sayıyla tam okundu. */
  complete: boolean;
  fetchedAt: string | null;
  /** UYAP'ın "Dosya Hesabı" alanları (etiket, UYAP'ın yazdığı metin); hesaplanmaz. */
  account: { label: string; value: string }[];
}

export interface UyapInfo {
  /** UYAP'ın gösterdiği durum metni ("Açık", "Kapalı ( 27.06.2025 … )"); yorumlanmaz. */
  durum: string | null;
  tur: string | null;
  rol: string | null;
  acilis: string | null;
  /** Son doğrulamada UYAP'taki her evrak JurisAI'da kayıtlıydı. */
  complete: boolean;
  missing: number;
  checkedAt: string | null;
}

export interface ExecutionSummary {
  files: number;
  documents: number;
  /** UYAP'tan eksiksiz aktarıldığı doğrulanan / hiç doğrulanmamış dosya sayısı. */
  verifiedComplete: number;
  neverVerified: number;
  tahsilat: ReceiptSummary;
  masraf: ReceiptSummary;
}

export interface ExecutionData {
  files: ExecutionFile[];
  summary: ExecutionSummary;
  labels: Record<string, string>;
}

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const count = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.trunc(value) : 0);
const text = (value: unknown): string | null => (typeof value === "string" && value ? value : null);

function receipt(value: unknown): ReceiptSummary {
  const item = isRecord(value) ? value : {};
  const total = text(item.total);
  return { count: count(item.count), read: count(item.read), total: total && /^\d+(\.\d+)?$/.test(total) ? total : null };
}

function parseFile(value: unknown): ExecutionFile[] {
  if (!isRecord(value) || typeof value.case_id !== "string") return [];
  const counts: Record<string, number> = {};
  if (isRecord(value.counts)) for (const [key, amount] of Object.entries(value.counts)) if (count(amount) > 0) counts[key] = count(amount);
  const receipts: Record<string, ReceiptSummary> = {};
  if (isRecord(value.receipts)) for (const [key, item] of Object.entries(value.receipts)) receipts[key] = receipt(item);
  return [
    {
      case_id: value.case_id,
      file_no: text(value.file_no),
      court: text(value.court) ?? "",
      kind: value.kind === "mahkeme" ? "mahkeme" : "takip",
      documents: count(value.documents),
      first_date: text(value.first_date),
      last_date: text(value.last_date),
      counts,
      receipts,
      uyap: parseUyap(value.uyap),
      detail: parseDetailInfo(value.detail),
    },
  ];
}

function parseDetailInfo(value: unknown): ExecutionDetail | null {
  if (!isRecord(value)) return null;
  const account = Array.isArray(value.account)
    ? value.account.flatMap((item) =>
        isRecord(item) && typeof item.label === "string" && typeof item.value === "string"
          ? [{ label: item.label.slice(0, 160), value: item.value.slice(0, 200) }]
          : [],
      )
    : [];
  return { complete: value.complete === true, fetchedAt: text(value.fetched_at), account };
}

function parseUyap(value: unknown): UyapInfo | null {
  if (!isRecord(value)) return null;
  return {
    durum: text(value.durum),
    tur: text(value.tur),
    rol: text(value.rol),
    acilis: text(value.acilis),
    complete: value.complete === true,
    missing: count(value.missing),
    checkedAt: text(value.checked_at),
  };
}

/** Doğrulama rozeti: hiç doğrulanmamış dosya "eksiksiz" ya da "eksik" diye gösterilmez. */
export function verificationLabel(uyap: UyapInfo | null): { text: string; tone: "ok" | "warn" | "none" } {
  if (!uyap) return { text: "UYAP ile karşılaştırılmadı", tone: "none" };
  const when = uyap.checkedAt ? ` (${dateTr(uyap.checkedAt)})` : "";
  if (uyap.complete) return { text: `UYAP'taki evrakların tamamı aktarılmış${when}`, tone: "ok" };
  return { text: uyap.missing > 0 ? `${uyap.missing} evrak eksik${when}` : `Aktarım doğrulanamadı${when}`, tone: "warn" };
}

/** UYAP durum metninin kısa hâli: "Kapalı ( 27.06.2025 11:43:11 )" → "Kapalı". Metin tanınmıyorsa olduğu gibi kalır. */
export function shortStatus(durum: string | null | undefined): string {
  const value = (durum ?? "").trim();
  return value.replace(/\s*\(.*$/, "").trim() || value;
}

/** Sunucu yanıtını güvenli biçimde okur; bozuk ya da eksik alan boş değere düşer, sayfa çökmez. */
export function parseExecution(raw: unknown): ExecutionData {
  const body = isRecord(raw) ? raw : {};
  const files = Array.isArray(body.files) ? body.files.flatMap(parseFile) : [];
  const summary = isRecord(body.summary) ? body.summary : {};
  const labels: Record<string, string> = {};
  if (isRecord(body.labels)) for (const [key, label] of Object.entries(body.labels)) if (typeof label === "string") labels[key] = label;
  return {
    files,
    labels,
    summary: {
      files: count(summary.files) || files.length,
      documents: count(summary.documents),
      verifiedComplete: count(summary.verified_complete),
      neverVerified: count(summary.never_verified),
      tahsilat: receipt(summary.tahsilat),
      masraf: receipt(summary.masraf),
    },
  };
}

/** "1234.5" → "1.234,50 TL" (binlik nokta, ondalık virgül). */
export function formatLira(amount: string | null | undefined): string {
  if (!amount || !/^\d+(\.\d+)?$/.test(amount)) return "—";
  const [whole, fraction = ""] = amount.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `${grouped},${(fraction + "00").slice(0, 2)} TL`;
}

/** Makbuz özetinin satırı: tutar ve kaç makbuzdan okunduğu; okunamayan makbuz sessizce atlanmaz. */
export function receiptLine(summary: ReceiptSummary | undefined): string {
  if (!summary || summary.count === 0) return "—";
  if (summary.read === 0) return `okunamadı (${summary.count} makbuz)`;
  const base = formatLira(summary.total);
  return summary.read === summary.count ? `${base} (${summary.count} makbuz)` : `${base} (${summary.count} makbuzdan ${summary.read}'i okundu)`;
}

/** Özet kartının alt notu: kaç makbuzun toplandığı; makbuz yoksa boş. */
export function receiptNote(summary: ReceiptSummary | undefined): string {
  if (!summary || summary.count === 0) return "";
  if (summary.read === 0) return `okunamadı (${summary.count} makbuz)`;
  return summary.read === summary.count ? `${summary.count} makbuz` : `${summary.count} makbuzdan ${summary.read}'i okundu`;
}

const DATE = /^(\d{4})-(\d{2})-(\d{2})/;
export function dateTr(value: string | null | undefined): string {
  const match = value ? DATE.exec(value) : null;
  return match ? `${match[3]}.${match[2]}.${match[1]}` : "—";
}

export const KIND_LABELS: Record<ExecutionFile["kind"], string> = { takip: "İcra dairesi", mahkeme: "İcra mahkemesi" };

/** Dairenin adı "(Kapatılan)" ile başlıyorsa daire kapatılmıştır; dosyanın kapandığı anlamına GELMEZ. */
export function closedOffice(court: string): boolean {
  return /^\(kapatılan\)/i.test(court.trim());
}

export type KindFilter = "all" | ExecutionFile["kind"];

/** Arama kutusu ve tür süzgeci: dosya no, daire adı ve yıl/numara parçasıyla eşleşir. */
export function filterFiles(files: ExecutionFile[], query: string, kind: KindFilter): ExecutionFile[] {
  const needle = query.trim().toLocaleLowerCase("tr-TR").replace(/\s+/g, " ");
  return files.filter((file) => {
    if (kind !== "all" && file.kind !== kind) return false;
    if (!needle) return true;
    return `${file.file_no ?? ""} ${file.court}`.toLocaleLowerCase("tr-TR").includes(needle);
  });
}

/** Dosya satırındaki evrak rozetleri: en çok evrağı olan türler önce, "diğer" en sonda. */
export function countBadges(counts: Record<string, number>, labels: Record<string, string>, limit = 8): Array<{ key: string; label: string; count: number }> {
  return Object.entries(counts)
    .sort(([a, x], [b, y]) => (a === "diger" ? 1 : b === "diger" ? -1 : y - x))
    .slice(0, limit)
    .map(([key, amount]) => ({ key, label: labels[key] ?? key, count: amount }));
}

const BASE = (import.meta.env?.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export async function loadExecution(signal?: AbortSignal): Promise<ExecutionData> {
  const token = inMemoryAccessToken();
  let response: Response;
  try {
    response = await fetch(`${BASE}/api/office/execution/files`, {
      credentials: "include",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error("Sunucuya ulaşılamadı.");
  }
  if (!response.ok) throw new Error(response.status === 401 ? "Oturumunuz sona ermiş; yeniden giriş yapın." : "İcra dosyaları şu an yüklenemiyor.");
  return parseExecution(await response.json().catch(() => null));
}

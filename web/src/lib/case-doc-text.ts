/**
 * Belge seçme listelerinde bir belgenin metninin durumu.
 *
 * Yeni yüklenen belgenin metni sunucuda arka planda okunur; okuma bitene kadar belge "metin çıkarılamadı" diye
 * gösterilmemeli (kullanıcı belgenin bozuk olduğunu sanıyordu). Okuma birkaç saniye sürer; bu süre geçtiği hâlde metin
 * yoksa belge gerçekten okunamamıştır (taranmış görüntü, desteklenmeyen tür).
 */
export type DocTextState = "ready" | "reading" | "none";

/** Yüklemeden sonra metnin okunması için tanınan süre. */
export const READING_WINDOW_MS = 3 * 60 * 1000;

export function docTextState(
  excerpt: string | null | undefined,
  createdAt: string | null | undefined,
  now: number = Date.now(),
): DocTextState {
  if (excerpt && excerpt.trim()) return "ready";
  const created = createdAt ? Date.parse(createdAt) : Number.NaN;
  if (Number.isFinite(created) && now - created < READING_WINDOW_MS) return "reading";
  return "none";
}

/** Durumun satırda gösterilen eki; metni okunmuş belgede ek yoktur. */
export function docTextNote(state: DocTextState): string {
  if (state === "reading") return "metni okunuyor…";
  if (state === "none") return "metin çıkarılamadı";
  return "";
}

/** Kaynağın kullanıcıya gösterilen adı (veritabanındaki teknik değer yerine). */
export function docSourceLabel(source: string | null | undefined): string {
  if (!source || source === "manual") return "Elle yüklendi";
  if (source.startsWith("uyap")) return "UYAP";
  if (source === "google_drive") return "Google Drive";
  return source;
}

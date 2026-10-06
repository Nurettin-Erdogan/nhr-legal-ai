// UYAP benzeri dosya senkronizasyonu için istemci yardımcıları.
// Güvenlik notu: UYAP'ın açık bir API'si yoktur ve e-imza/kimlik bilgileri
// üçüncü bir sisteme verilemez. Bu nedenle akış "kullanıcı tarafından
// indirilen resmî UYAP çıktısının içe aktarılması" üzerine kuruludur;
// hiçbir UYAP şifresi/e-imzası uygulamada saklanmaz.

export const ALLOWED_EXTENSIONS = [
  "pdf",
  "udf",
  "odt",
  "docx",
  "doc",
  "txt",
  "html",
  "tif",
  "tiff",
  "jpg",
  "jpeg",
  "png",
  "xml",
  "eyp",
  "zip",
  "rar",
  "xls",
  "xlsx",
] as const;

export const MAX_FILE_BYTES = 50 * 1024 * 1024; // bucket limiti ile aynı
export const MAX_ARCHIVE_ENTRIES = 200;
export const MAX_ARCHIVE_BYTES = 50 * 1024 * 1024;
export const MAX_ARCHIVE_EXPANDED_BYTES = 200 * 1024 * 1024;

/** Elle içe aktarma ve eklenti aktarımı aynı UYAP kökenini taşır. */
export const isUyapSource = (source: string | null | undefined) =>
  source === "uyap" || source === "uyap-avukat-eklentisi" || source === "uyap-extension";

export const extOf = (name: string) => name.split(".").pop()?.toLowerCase() ?? "";

export const isAllowedFile = (name: string) =>
  (ALLOWED_EXTENSIONS as readonly string[]).includes(extOf(name));

/** Depolama yolu için güvenli ad: dizin geçişi ve özel karakterler temizlenir. */
export const safeFileName = (name: string) =>
  name
    .replace(/\\/g, "/")
    .split("/")
    .pop()!
    .normalize("NFKD")
    .replace(/[^\w.-]+/g, "_")
    .replace(/_{2,}/g, "_")
    .slice(-120) || "dosya";

export const humanSize = (bytes?: number | null) => {
  if (!bytes) return "-";
  const units = ["B", "KB", "MB", "GB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
};

export interface UyapMeta {
  uyap_file_no: string | null;
  uyap_birim: string | null;
  doc_date: string | null;
  doc_type: string | null;
}

const BIRIM_RE =
  /((?:\d+\.\s*)?(?:asliye\s+(?:hukuk|ticaret|ceza)|sulh\s+hukuk|i(?:ş|s)\s+mahkemesi|aile\s+mahkemesi|icra\s+(?:müdürlü(?:ğ|g)ü|hukuk)|a(?:ğ|g)(?:ı|i)r\s+ceza|asliye\s+ticaret|tüketici|cumhuriyet\s+ba(?:ş|s)savc(?:ı|i)l(?:ı|i)(?:ğ|g)(?:ı|i))[\w\s.]{0,25})/i;

const DOC_TYPES = [
  "dilekçe",
  "dilekce",
  "tensip",
  "karar",
  "gerekçeli",
  "gerekceli",
  "tebligat",
  "bilirkişi",
  "bilirkisi",
  "duruşma",
  "durusma",
  "tutanak",
  "müzekkere",
  "muzekkere",
  "haciz",
  "ödeme emri",
  "odeme emri",
  "vekaletname",
  "layiha",
  "cevap",
  "temyiz",
  "istinaf",
  "rapor",
  "makbuz",
];

/** Dosya adı / metin içeriğinden UYAP alanlarını çıkarır (yalnızca tahmin). */
export function parseUyapMeta(fileName: string, sample = ""): UyapMeta {
  const hay = `${fileName.replace(/_+/g, " ")} ${sample.slice(0, 4000)}`;

  const fileNo = hay.match(/\b(20\d{2})\s*[/_-]\s*(\d{1,7})\b/) ?? null;
  const dateM =
    hay.match(/\b(\d{2})[.\-/](\d{2})[.\-/](20\d{2})\b/) ??
    hay.match(/\b(20\d{2})-(\d{2})-(\d{2})\b/);

  let doc_date: string | null = null;
  if (dateM) {
    doc_date =
      dateM[0].length === 10 && dateM[1]!.length === 4
        ? `${dateM[1]}-${dateM[2]}-${dateM[3]}`
        : `${dateM[3]}-${dateM[2]}-${dateM[1]}`;
    const [year, month, day] = doc_date.split("-").map(Number);
    const parsed = new Date(Date.UTC(year!, month! - 1, day!));
    if (parsed.getUTCFullYear() !== year || parsed.getUTCMonth() + 1 !== month || parsed.getUTCDate() !== day)
      doc_date = null;
  }

  const lower = hay.toLowerCase();
  const docType = DOC_TYPES.find((t) => lower.includes(t)) ?? null;
  const birim = hay.match(BIRIM_RE)?.[1]?.trim().replace(/\s+/g, " ") ?? null;

  return {
    uyap_file_no: fileNo ? `${fileNo[1]}/${fileNo[2]}` : null,
    uyap_birim: birim,
    doc_date,
    doc_type: docType ? docType[0]!.toUpperCase() + docType.slice(1) : null,
  };
}

export interface ArchiveEntry {
  name: string;
  data: Uint8Array;
  error?: string;
}

/** UYAP'tan indirilen ZIP/EYP arşivini tarayıcıda açar. */
export async function readArchive(file: File): Promise<ArchiveEntry[]> {
  if (file.size > MAX_ARCHIVE_BYTES) throw new Error("UYAP arşivi 50 MB sınırını aşıyor");
  const { unzipSync } = await import("fflate");
  const buf = new Uint8Array(await file.arrayBuffer());
  let count = 0;
  let expanded = 0;
  const rejected: ArchiveEntry[] = [];
  const seen = new Set<string>();
  const unzipped = unzipSync(buf, {
    filter(info) {
      count++;
      expanded += info.originalSize;
      if (count > MAX_ARCHIVE_ENTRIES || expanded > MAX_ARCHIVE_EXPANDED_BYTES || info.originalSize > MAX_FILE_BYTES)
        throw new Error("UYAP arşivi güvenli açma sınırını aşıyor");
      if (info.name.endsWith("/")) return false;
      if (seen.has(info.name)) throw new Error("Arşivde aynı yolda birden çok belge var; arşivi kontrol edin");
      seen.add(info.name);
      if (!isAllowedFile(info.name)) {
        rejected.push({ name: info.name, data: new Uint8Array(), error: "Desteklenmeyen dosya türü" });
        return false;
      }
      return true;
    },
  });
  const entries: ArchiveEntry[] = [...rejected];
  for (const [name, data] of Object.entries(unzipped)) {
    if (name.endsWith("/")) continue;
    if (!data.length) {
      entries.push({ name, data, error: "Boş dosya" });
      continue;
    }
    if (!isAllowedFile(name)) continue;
    if (data.length > MAX_FILE_BYTES) continue;
    entries.push({ name, data });
  }
  return entries;
}

/** UDF (UYAP Doküman Formatı) aslında içinde content.xml barındıran bir zip'tir. */
export async function extractTextSample(name: string, bytes: Uint8Array): Promise<string> {
  try {
    const ext = extOf(name);
    if (ext === "txt" || ext === "xml") {
      return new TextDecoder().decode(bytes.slice(0, 20000));
    }
    if (ext === "udf" || ext === "odt") {
      const { unzipSync, strFromU8 } = await import("fflate");
      const inner = unzipSync(bytes, {
        filter(info) {
          return info.name.toLowerCase().endsWith("content.xml") && info.originalSize <= 2 * 1024 * 1024;
        },
      });
      const key = Object.keys(inner).find((k) => k.toLowerCase().endsWith("content.xml"));
      if (!key) return "";
      return strFromU8(inner[key]!)
        .replace(/<[^>]+>/g, " ")
        .slice(0, 20000);
    }
  } catch {
    return "";
  }
  return "";
}

export const storagePathFor = (userId: string, fileName: string) =>
  `${userId}/${new Date().getFullYear()}/${crypto.randomUUID()}-${safeFileName(fileName)}`;

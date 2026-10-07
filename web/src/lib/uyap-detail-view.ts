/**
 * UYAP dosya bilgilerinin (taraflar, safahat, dosya hesabı, tahsilat/reddiyat…) gösterimine yardımcılar.
 *
 * Değerler UYAP'ın yazdığı metindir: burada yorumlanmaz, toplanmaz, yeniden hesaplanmaz. Yalnız ayıklanır (arama) ve düzenlenir.
 */
import type { DetailPair, DetailTab, DetailTable, DosyaDetail } from "@/lib/uyap-bridge";

const FOLD: Record<string, string> = { İ: "i", I: "i", ı: "i", Ş: "s", ş: "s", Ç: "c", ç: "c", Ğ: "g", ğ: "g", Ö: "o", ö: "o", Ü: "u", ü: "u" };

/** Türkçe harf çiftlerini (ı/i, ş/s…) tek biçime indirip küçük harfe çevirir: "ISPARTA" ile "ısparta" ve "Isparta" aynı aranır. */
export const foldText = (text: string): string =>
  text
    .replace(/[İIıŞşÇçĞğÖöÜü]/g, (character) => FOLD[character] ?? character)
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();

/** Satırlardan, her arama sözcüğünü (büyük/küçük harf ve Türkçe karakter gözetmeden) içerenleri döndürür; boş arama hepsini verir. */
export function filterRows(rows: string[][], query: string): string[][] {
  const words = foldText(query).split(" ").filter(Boolean);
  if (!words.length) return rows;
  return rows.filter((row) => {
    const haystack = foldText(row.join(" "));
    return words.every((word) => haystack.includes(word));
  });
}

export const TAB_TITLES: Record<string, string> = {
  bilgiler: "Dosya bilgileri",
  hesap: "Dosya hesabı",
  taraflar: "Taraflar",
  safahat: "Safahat",
  tahsilat: "Tahsilat / reddiyat",
};
/** Gösterim sırası: önce dosyanın kimliği ve parası, sonra kişiler ve geçmiş. */
const ORDER = ["bilgiler", "hesap", "taraflar", "safahat", "tahsilat"];

export function orderedTabs(detail: DosyaDetail): DetailTab[] {
  return [...detail.tabs].sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key));
}

export const tabTitle = (tab: DetailTab): string => TAB_TITLES[tab.key] ?? tab.label ?? tab.key;

/** Bir tablonun UYAP'ın söylediği sayıyla uyuşmadığını anlatan cümle; tamamsa null. */
export function tableWarning(tab: DetailTab, table: DetailTable): string | null {
  if (table.complete) return null;
  const name = `${tabTitle(tab)}${table.title ? ` / ${table.title}` : ""}`;
  return table.declared === null
    ? `${name}: tablo eksiksiz okunamadı.`
    : `${name}: UYAP ${table.declared} kayıt yazıyor, ${table.rows.length} kayıt alındı.`;
}

/** Eksik okunan tabloların uyarıları (ayrıca eklentinin bildirdiği sorunlar) — hiçbiri sessizce gizlenmez. */
export function detailWarnings(detail: DosyaDetail): string[] {
  const out: string[] = [];
  for (const tab of detail.tabs) for (const table of tab.tables) {
    const warning = tableWarning(tab, table);
    if (warning) out.push(warning);
  }
  for (const problem of detail.problems) if (!out.includes(problem)) out.push(problem);
  return out;
}

/** İcra listesindeki tek satırlık özet: "Toplam alacak: … · Yatan para: … · Bakiye borç: …" (UYAP'ın yazdığı metin); alan yoksa boş. */
export function accountLine(pairs: DetailPair[]): string {
  return accountSummary(pairs)
    .map((pair) => `${pair.label.replace(" Miktarı", "")}: ${pair.value}`)
    .join(" · ");
}

/** UYAP'ın dosya hesabında yazdığı alanlardan istenenleri (etiket → UYAP'ın yazdığı metin) döndürür; bulunmayan alan atlanır, hiçbir şey hesaplanmaz. */
export function accountSummary(pairs: DetailPair[], wanted: string[] = ["Toplam Alacak", "Yatan Para", "Bakiye Borç Miktarı"]): DetailPair[] {
  return wanted.flatMap((label) => {
    const found = pairs.find((pair) => foldText(pair.label) === foldText(label));
    return found && found.value ? [{ label, value: found.value }] : [];
  });
}

/** Never navigate to stored executable/credential-bearing URLs. No external fetch/proxy. */
export function safeSourceUrl(value: string | null | undefined): string | null {
  if (
    !value ||
    [...value].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)
  )
    return null;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}

export function isSourceId(value: string | null | undefined): value is string {
  return !!value && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}

export function sourceSiteLabel(value: string): string {
  const host = new URL(value).hostname;
  return /(^|\.)(yargitay\.gov\.tr|danistay\.gov\.tr|anayasa\.gov\.tr|mevzuat\.gov\.tr|adalet\.gov\.tr|ombudsman\.gov\.tr)$/.test(
    host,
  )
    ? "Resmî sitede aç ↗"
    : "Kaynak sitesinde aç ↗";
}

export function isRawPortalUrl(value: string): boolean {
  const url = new URL(value);
  return (
    ["karararama.yargitay.gov.tr", "karararama.danistay.gov.tr"].includes(url.hostname) &&
    /\/getDokuman\/?$/i.test(url.pathname)
  );
}

// Satır başı işaretleri: "I. ", "1. ", "(1) ", "a) ", "MADDE 72", "- ".
const ITEM_START = /^(?:[IVX]+\.|\d+[.)]|\(\d+\)|[a-zçğıöşü]\)|MADDE\s+\d+|[-•–])(?:\s|$)/;
const HEADING = /^(?:[IVX]+\.|[A-ZÇĞİÖŞÜ0-9"' ().-]{4,})/;

export interface SourceParagraph {
  text: string;
  heading: boolean;
}

/**
 * Kaynak metnini okunur paragraflara çevirir: resmî metinler sabit genişlikte satır kırılmış gelir ("öğrendiği tarihten" / "başlayarak").
 * Aynı paragraftaki satırlar boşlukla birleştirilir, madde/fıkra/bent başlangıçları yeni paragraf olur. Sözcük ya da rakam
 * eklenip çıkarılmaz; yalnız satır sonları ve fazla boşluklar değişir.
 */
export function readableParagraphs(raw: string): SourceParagraph[] {
  const paragraphs: string[] = [];
  for (const block of raw.replace(/\r\n?/g, "\n").split(/\n\s*\n/)) {
    let current = "";
    for (const line of block.split("\n")) {
      const text = line.replace(/\s+/g, " ").trim();
      if (!text) continue;
      // Önceki satır cümleyle bitip bu satır büyük harfle başlıyorsa fıkra sınırıdır (tek satır sonu kalmış olabilir).
      if (
        current &&
        (ITEM_START.test(text) || (/[.!?]$/.test(current) && /^[A-ZÇĞİÖŞÜ]/.test(text)))
      ) {
        paragraphs.push(current);
        current = text;
      } else current = current ? `${current} ${text}` : text;
    }
    if (current) paragraphs.push(current);
  }
  return paragraphs.map((text) => ({
    text,
    heading: text.length <= 90 && !/[.;:!?,]$/.test(text) && HEADING.test(text),
  }));
}

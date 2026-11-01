export interface DocumentLayout {
  paper: "a4" | "letter";
  marginMm: number;
  fontPt: number;
  lineHeight: number;
  alignment: "left" | "justify";
  pageNumbers: boolean;
}
export const DEFAULT_DOCUMENT_LAYOUT: DocumentLayout = {
  paper: "a4",
  marginMm: 20,
  fontPt: 11,
  lineHeight: 1.5,
  alignment: "left",
  pageNumbers: true,
};
export function normalizeDocumentLayout(raw: Partial<DocumentLayout> = {}): DocumentLayout {
  const number = (value: unknown, fallback: number, min: number, max: number) =>
    typeof value === "number" && Number.isFinite(value)
      ? Math.min(max, Math.max(min, value))
      : fallback;
  return {
    paper: raw.paper === "letter" ? "letter" : "a4",
    marginMm: number(raw.marginMm, 20, 10, 35),
    fontPt: number(raw.fontPt, 11, 9, 16),
    lineHeight: number(raw.lineHeight, 1.5, 1, 2),
    alignment: raw.alignment === "justify" ? "justify" : "left",
    pageNumbers: raw.pageNumbers !== false,
  };
}
export function documentPageStyle(raw: Partial<DocumentLayout> = {}) {
  const layout = normalizeDocumentLayout(raw);
  return {
    fontFamily: "'Liberation Sans', Arial, sans-serif",
    fontSize: `${layout.fontPt}pt`,
    lineHeight: layout.lineHeight,
    textAlign: layout.alignment,
    padding: `${layout.marginMm}mm`,
    width: layout.paper === "a4" ? "210mm" : "215.9mm",
    minHeight: layout.paper === "a4" ? "297mm" : "279.4mm",
    maxWidth: "100%",
    margin: "0 auto",
  } as const;
}
export function docxPageProperties(raw: Partial<DocumentLayout> = {}) {
  const layout = normalizeDocumentLayout(raw);
  const twips = (mm: number) => Math.round((mm / 25.4) * 1440);
  const margin = twips(layout.marginMm);
  return {
    size: {
      width: twips(layout.paper === "a4" ? 210 : 215.9),
      height: twips(layout.paper === "a4" ? 297 : 279.4),
    },
    margin: { top: margin, bottom: margin, left: margin, right: margin },
  };
}

import { jsPDF } from "jspdf";
import { normalizeDocumentLayout, type DocumentLayout } from "@/lib/document-layout";

/**
 * Metni Türkçe karakterleri (ş ğ ı İ Ş Ğ) bozmadan PDF'e yazar. jsPDF'in yerleşik yazı tipleri bu harfleri içermez; bu yüzden
 * Liberation Sans (SIL OFL, `public/fonts`) PDF'e gömülür. Markdown işaretleri sadeleştirilir; `#` başlıklar kalın yazılır.
 */
const FONTS = {
  regular: "/fonts/LiberationSans-Regular.ttf",
  bold: "/fonts/LiberationSans-Bold.ttf",
} as const;

async function fontData(url: string): Promise<string> {
  const response = await fetch(url);
  if (!response.ok) throw new Error("PDF yazı tipi yüklenemedi.");
  const bytes = new Uint8Array(await response.arrayBuffer());
  let binary = "";
  for (let index = 0; index < bytes.length; index += 0x8000)
    binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  return binary;
}

export interface PdfLine {
  text: string;
  bold: boolean;
}

/** Markdown satırlarını PDF satırlarına çevirir: `#` başlık kalın, `**…**` ve diğer işaretler sade metne indirilir. */
export function pdfLines(content: string): PdfLine[] {
  return content
    .replace(/\r\n/g, "\n")
    .trimEnd()
    .replace(/\n{3,}/g, "\n\n")
    .split("\n")
    .map((raw) => {
      const heading = /^#{1,6}\s+/.test(raw) || /^\*\*[^*]+\*\*:?\s*$/.test(raw.trim());
      const text = raw
        .replace(/^\s*([-*_])\1{2,}\s*$/, "")
        .replace(/^#{1,6}\s+/, "")
        .replace(/\*\*(.*?)\*\*/g, "$1")
        .replace(/^>\s?/, "")
        .replace(/[`_]/g, "")
        .replace(/\\([\\`*_{}[\]<>#!|])/g, "$1")
        .replace(/^\s*[-*]\s+/, "• ");
      return { text, bold: heading };
    });
}

export async function exportTextPdf(
  content: string,
  fileName: string,
  options?: DocumentLayout,
): Promise<void> {
  const layout = normalizeDocumentLayout(options);
  const [regular, bold] = await Promise.all([fontData(FONTS.regular), fontData(FONTS.bold)]);
  const doc = new jsPDF({ unit: "pt", format: layout.paper });
  doc.addFileToVFS("LiberationSans-Regular.ttf", btoa(regular));
  doc.addFont("LiberationSans-Regular.ttf", "Liberation", "normal");
  doc.addFileToVFS("LiberationSans-Bold.ttf", btoa(bold));
  doc.addFont("LiberationSans-Bold.ttf", "Liberation", "bold");
  const margin = (layout.marginMm / 25.4) * 72;
  const usable = doc.internal.pageSize.getWidth() - margin * 2;
  const pageHeight = doc.internal.pageSize.getHeight();
  doc.setFontSize(layout.fontPt);
  let y = margin + layout.fontPt;
  for (const line of pdfLines(content)) {
    doc.setFont("Liberation", line.bold ? "bold" : "normal");
    const wrapped: string[] = line.text.trim() ? doc.splitTextToSize(line.text, usable) : [""];
    for (const piece of wrapped) {
      if (y > pageHeight - margin) {
        if (!piece) continue; // Whitespace alone must never create a blank page.
        doc.addPage();
        y = margin + layout.fontPt;
      }
      if (piece)
        doc.text(piece, margin, y, {
          align: layout.alignment === "justify" && piece !== wrapped.at(-1) ? "justify" : "left",
          maxWidth: usable,
        });
      y += layout.fontPt * layout.lineHeight;
    }
  }
  if (layout.pageNumbers)
    for (let page = 1; page <= doc.getNumberOfPages(); page++) {
      doc.setPage(page);
      doc.setFontSize(9);
      doc.text(
        `${page} / ${doc.getNumberOfPages()}`,
        doc.internal.pageSize.getWidth() / 2,
        pageHeight - margin / 2,
        { align: "center" },
      );
    }
  doc.save(`${(fileName || "belge").replace(/[^\p{L}\p{N}._-]+/gu, "-")}.pdf`);
}

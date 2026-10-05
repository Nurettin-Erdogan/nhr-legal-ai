import { jsPDF } from "jspdf";

/**
 * Metni Türkçe karakterleri (ş ğ ı İ Ş Ğ) bozmadan PDF'e yazar. jsPDF'in yerleşik yazı tipleri bu harfleri içermez; bu yüzden
 * Liberation Sans (SIL OFL, `public/fonts`) PDF'e gömülür. Markdown işaretleri sadeleştirilir; `#` başlıklar kalın yazılır.
 */
const FONTS = { regular: "/fonts/LiberationSans-Regular.ttf", bold: "/fonts/LiberationSans-Bold.ttf" } as const;

async function fontData(url: string): Promise<string> {
  const response = await fetch(url);
  if (!response.ok) throw new Error("PDF yazı tipi yüklenemedi.");
  const bytes = new Uint8Array(await response.arrayBuffer());
  let binary = "";
  for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
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
    .replace(/\n{3,}/g, "\n\n")
    .split("\n")
    .map((raw) => {
      const heading = /^#{1,6}\s+/.test(raw) || /^\*\*[^*]+\*\*:?\s*$/.test(raw.trim());
      const text = raw
        .replace(/^#{1,6}\s+/, "")
        .replace(/\*\*(.*?)\*\*/g, "$1")
        .replace(/^>\s?/, "")
        .replace(/[`_]/g, "")
        .replace(/^\s*[-*]\s+/, "• ");
      return { text, bold: heading };
    });
}

export async function exportTextPdf(content: string, fileName: string): Promise<void> {
  const [regular, bold] = await Promise.all([fontData(FONTS.regular), fontData(FONTS.bold)]);
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  doc.addFileToVFS("LiberationSans-Regular.ttf", btoa(regular));
  doc.addFont("LiberationSans-Regular.ttf", "Liberation", "normal");
  doc.addFileToVFS("LiberationSans-Bold.ttf", btoa(bold));
  doc.addFont("LiberationSans-Bold.ttf", "Liberation", "bold");
  const margin = 56;
  const usable = doc.internal.pageSize.getWidth() - margin * 2;
  const pageHeight = doc.internal.pageSize.getHeight();
  doc.setFontSize(11);
  let y = margin;
  for (const line of pdfLines(content)) {
    doc.setFont("Liberation", line.bold ? "bold" : "normal");
    const wrapped: string[] = line.text.trim() ? doc.splitTextToSize(line.text, usable) : [""];
    for (const piece of wrapped) {
      if (y > pageHeight - margin) {
        doc.addPage();
        y = margin;
      }
      if (piece) doc.text(piece, margin, y);
      y += 16;
    }
  }
  doc.save(`${(fileName || "belge").replace(/[\/:*?"<>|\s]+/g, "-")}.pdf`);
}

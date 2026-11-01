export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

/** Extracts plain text from a PDF, DOCX or plain-text file in the browser. */
export async function extractFileText(file: File): Promise<string> {
  const name = file.name.toLowerCase();

  if (name.endsWith(".pdf")) {
    const pdfjs = await import("pdfjs-dist");
    const workerMod = await import("pdfjs-dist/build/pdf.worker.min.mjs?url");
    pdfjs.GlobalWorkerOptions.workerSrc = (workerMod as { default: string }).default;
    const buf = await file.arrayBuffer();
    const pdf = await pdfjs.getDocument({ data: buf }).promise;
    const parts: string[] = [];
    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      const content = await page.getTextContent();
      parts.push(
        content.items.map((it) => ("str" in it ? (it as { str: string }).str : "")).join(" "),
      );
    }
    return parts.join("\n\n");
  }

  if (name.endsWith(".docx")) {
    const mammoth = await import("mammoth/mammoth.browser.js");
    const buf = await file.arrayBuffer();
    const r = await mammoth.extractRawText({ arrayBuffer: buf });
    return r.value;
  }

  if (file.type.startsWith("text/") || /\.(txt|md|csv)$/i.test(name)) {
    return await file.text();
  }

  throw new Error("unsupported");
}

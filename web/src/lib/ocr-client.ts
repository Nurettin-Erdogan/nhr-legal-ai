/** Tarayıcı tarafı: dosyadan metin ya da OCR için sayfa görselleri üretir. */

export const OCR_MAX_BYTES = 25 * 1024 * 1024;
const MAX_OCR_PAGES = 10;

const readAsDataUrl = (file: File | Blob) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("Dosya okunamadı"));
    reader.readAsDataURL(file);
  });

async function pdfPagesToImages(file: File): Promise<string[]> {
  const pdfjs = await import("pdfjs-dist");
  const workerMod = await import("pdfjs-dist/build/pdf.worker.min.mjs?url");
  pdfjs.GlobalWorkerOptions.workerSrc = (workerMod as { default: string }).default;
  const pdf = await pdfjs.getDocument({ data: await file.arrayBuffer() }).promise;
  const images: string[] = [];
  const count = Math.min(pdf.numPages, MAX_OCR_PAGES);
  for (let i = 1; i <= count; i++) {
    const page = await pdf.getPage(i);
    const base = page.getViewport({ scale: 1 });
    const scale = Math.min(2, 1600 / base.width);
    const viewport = page.getViewport({ scale });
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(viewport.width);
    canvas.height = Math.round(viewport.height);
    const ctx = canvas.getContext("2d")!;
    await page.render({ canvas, canvasContext: ctx, viewport } as never).promise;
    images.push(canvas.toDataURL("image/jpeg", 0.82));
  }
  return images;
}

export interface PreparedDoc {
  /** Dosyanın gömülü metni (varsa) */
  embeddedText: string;
  /** OCR gerekiyorsa gönderilecek sayfa görselleri */
  images: string[];
}

/** Dosyayı OCR akışına hazırlar: metin katmanı varsa onu, yoksa görselleri döndürür. */
export async function prepareForOcr(file: File): Promise<PreparedDoc> {
  const name = file.name.toLowerCase();

  if (file.type.startsWith("image/")) {
    return { embeddedText: "", images: [await readAsDataUrl(file)] };
  }

  if (name.endsWith(".pdf")) {
    let embeddedText = "";
    try {
      const { extractFileText } = await import("./extract-text");
      embeddedText = (await extractFileText(file)).trim();
    } catch {
      embeddedText = "";
    }
    if (embeddedText.replace(/\s+/g, "").length > 200) return { embeddedText, images: [] };
    return { embeddedText, images: await pdfPagesToImages(file) };
  }

  const { extractFileText } = await import("./extract-text");
  return { embeddedText: (await extractFileText(file)).trim(), images: [] };
}

/** Otomatik boru hattı yardımcıları: belge türü tespiti, dilekçe türü seçimi, Word/PDF üretimi. */

export type DocType =
  | "ceza_davasi"
  | "ticari_dava"
  | "aile_davasi"
  | "mahkeme_karari"
  | "bilgi_talep"
  | "idari_dava"
  | "icra_dosyasi"
  | "genel_dava";

export const DOC_TYPE_LABELS: Record<DocType, string> = {
  ceza_davasi: "Ceza Dosyası",
  ticari_dava: "Ticari Dava",
  aile_davasi: "Aile Davası",
  mahkeme_karari: "Mahkeme Kararı",
  bilgi_talep: "Bilgi/Veri Talebi",
  idari_dava: "İdari Dava",
  icra_dosyasi: "İcra Dosyası",
  genel_dava: "Genel Dosya",
};

/** OCR metninden belge türünü tahmin eder. */
export function detectDocType(text: string): DocType {
  const t = text.toLocaleUpperCase("tr-TR");
  const has = (...words: string[]) => words.every((w) => t.includes(w));

  if (has("KARAR") && (t.includes("GEREKÇELİ KARAR") || t.includes("HÜKÜM"))) {
    return "mahkeme_karari";
  }
  if (
    t.includes("CEZA") &&
    (t.includes("MAHKEMES") || t.includes("SAVCILI") || t.includes("İDDİANAME"))
  ) {
    return "ceza_davasi";
  }
  if (t.includes("İCRA") || t.includes("ÖDEME EMRİ") || t.includes("HACİZ")) return "icra_dosyasi";
  if (t.includes("BİLGİ EDİNME") || t.includes("BİLGİ TALEP") || t.includes("VERİ TALEB")) {
    return "bilgi_talep";
  }
  if (t.includes("ASLİYE TİCARET") || t.includes("TİCARİ")) return "ticari_dava";
  if (t.includes("AİLE MAHKEMES") || t.includes("BOŞANMA") || t.includes("NAFAKA")) {
    return "aile_davasi";
  }
  if (t.includes("İDARE MAHKEMES") || t.includes("İDARİ")) return "idari_dava";
  return "genel_dava";
}

/** Belge türüne göre yazılacak dilekçe türünü seçer (ocr.functions içindeki anahtarlar). */
export function decidePetitionType(docType: DocType): string {
  const map: Record<DocType, string> = {
    ceza_davasi: "itiraz",
    mahkeme_karari: "temyiz",
    ticari_dava: "temyiz",
    aile_davasi: "temyiz",
    idari_dava: "temyiz",
    icra_dosyasi: "itiraz",
    bilgi_talep: "talep",
    genel_dava: "itiraz",
  };
  return map[docType];
}

export const PETITION_LABELS: Record<string, string> = {
  itiraz: "İtiraz Dilekçesi",
  temyiz: "Temyiz Dilekçesi",
  istinaf: "İstinaf Dilekçesi",
  cevap: "Cevap Dilekçesi",
  dava: "Dava Dilekçesi",
  beyan: "Beyan Dilekçesi",
  talep: "Başvuru/Talep Dilekçesi",
};

const clean = (line: string) => line.replace(/[#*_`]/g, "");

/** Dilekçe metnini .docx dosyası olarak indirir. */
export async function downloadPetitionDocx(text: string, fileName: string) {
  const [{ Document, Packer, Paragraph, TextRun }, { saveAs }] = await Promise.all([
    import("docx"),
    import("file-saver"),
  ]);
  const doc = new Document({
    sections: [
      {
        children: text.split("\n").map(
          (line) =>
            new Paragraph({
              children: [new TextRun({ text: clean(line), font: "Times New Roman", size: 24 })],
              spacing: { after: 120 },
            }),
        ),
      },
    ],
  });
  saveAs(await Packer.toBlob(doc), `${fileName}.docx`);
}

/** Dilekçe metnini .pdf dosyası olarak indirir. */
export async function downloadPetitionPdf(text: string, fileName: string) {
  const { jsPDF } = await import("jspdf");
  const pdf = new jsPDF({ unit: "pt", format: "a4" });
  pdf.setFontSize(11);
  const lines = pdf.splitTextToSize(clean(text), 500) as string[];
  let y = 60;
  for (const line of lines) {
    if (y > 780) {
      pdf.addPage();
      y = 60;
    }
    pdf.text(line, 50, y);
    y += 16;
  }
  pdf.save(`${fileName}.pdf`);
}

/** Dosya adı için güvenli metin. */
export function slugName(input: string) {
  return input
    .replace(/\.[^.]+$/, "")
    .replace(/[\\/:*?"<>|]+/g, " ")
    .replace(/\s+/g, "_")
    .slice(0, 60);
}

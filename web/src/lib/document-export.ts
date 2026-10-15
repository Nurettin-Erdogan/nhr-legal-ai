import {
  Document,
  Paragraph,
  TextRun,
  HeadingLevel,
  Footer,
  PageNumber,
  AlignmentType,
} from "docx";
import { documentInlineRuns } from "@/lib/document-editor";
import {
  docxPageProperties,
  normalizeDocumentLayout,
  type DocumentLayout,
} from "@/lib/document-layout";

export function buildDocumentDocx(content: string, options: DocumentLayout) {
  const layout = normalizeDocumentLayout(options);
  const paragraphs = content.split("\n").map((line) => {
    const heading = /^#{1,3}\s/.test(line);
    const text = line.replace(/^#+\s*/, "").replace(/^\s*[-*]\s+/, "");
    return new Paragraph({
      heading: heading ? HeadingLevel.HEADING_2 : undefined,
      bullet: /^\s*[-*]\s+/.test(line) ? { level: 0 } : undefined,
      children: documentInlineRuns(text || " ").map(
        (run) =>
          new TextRun({
            ...run,
            bold: heading || run.bold,
            font: "Arial",
            size: layout.fontPt * 2,
          }),
      ),
      spacing: { after: 120, line: Math.round(layout.lineHeight * 240) },
      alignment: layout.alignment === "justify" ? AlignmentType.JUSTIFIED : AlignmentType.LEFT,
    });
  });
  return new Document({
    sections: [
      {
        properties: { page: docxPageProperties(layout) },
        children: paragraphs,
        footers: layout.pageNumbers
          ? {
              default: new Footer({
                children: [
                  new Paragraph({
                    alignment: AlignmentType.CENTER,
                    children: [
                      new TextRun({
                        children: [PageNumber.CURRENT, " / ", PageNumber.TOTAL_PAGES],
                      }),
                    ],
                  }),
                ],
              }),
            }
          : undefined,
      },
    ],
  });
}

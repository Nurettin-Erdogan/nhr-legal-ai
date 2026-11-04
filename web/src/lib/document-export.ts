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
  const paragraphs = content
    .replace(/\r\n/g, "\n")
    .split("\n")
    .filter((line) => line.trim() && !/^\s*([-*_])\1{2,}\s*$/.test(line))
    .map((line) => {
      const heading = /^#{1,3}\s/.test(line);
      const sectionHeading = /^\s*\*\*[^*]+\*\*\s*$/.test(line);
      const text = line
        .replace(/^#+\s*/, "")
        .replace(/^\s*[-*]\s+/, "")
        .replace(/(^|\s)_([^_\n]+)_/g, "$1$2")
        .replace(/`([^`]+)`/g, "$1");
      return new Paragraph({
        heading: heading
          ? /^#\s/.test(line)
            ? HeadingLevel.TITLE
            : HeadingLevel.HEADING_2
          : undefined,
        keepNext: heading || sectionHeading,
        widowControl: true,
        bullet: /^\s*[-*]\s+/.test(line) ? { level: 0 } : undefined,
        children: documentInlineRuns(text || " ").map(
          (run) =>
            new TextRun({
              ...run,
              bold: heading || run.bold,
              font: "Arial",
              color: "000000",
              size: layout.fontPt * 2,
            }),
        ),
        spacing: { after: 120, line: Math.round(layout.lineHeight * 240) },
        alignment: layout.alignment === "justify" ? AlignmentType.JUSTIFIED : AlignmentType.LEFT,
      });
    });
  return new Document({
    styles: {
      default: { document: { run: { font: "Arial", color: "000000", size: layout.fontPt * 2 } } },
    },
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

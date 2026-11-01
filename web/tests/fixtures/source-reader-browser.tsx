import { createElement } from "react";
import { createRoot } from "react-dom/client";
import { SourceReader } from "../../src/components/SourceReader";
import { CitationList, ConsultedSourceList } from "../../src/components/ChatCitations";
import { StepCard } from "../../src/components/DeepResearch";
import "../../src/styles.css";

const citation = {
  marker: "K1",
  source_id: "2de38edc-7b09-466d-98e7-e1b2693d9c76",
  reference: "Kaynak okuyucu bağlantı denetimi",
  source_url: "https://karararama.yargitay.gov.tr/getDokuman?id=1219103100",
  verification: "third_party",
  source_type: "court_decision",
  excerpt: "Kısa alıntı",
};
const privateCitation = {
  ...citation,
  marker: "K2",
  source_id: "12345678-1234-1234-1234-123456789abc",
  reference: "Sentetik özel belge",
  source_type: "document",
  verification: "user_document",
  source_url: null,
};
const linkChecks = createElement(
  "div",
  { style: { maxWidth: "900px", margin: "auto" } },
  createElement(
    "section",
    { "aria-label": "Sohbet atıfları" },
    createElement(CitationList, { citations: [citation, privateCitation] }),
  ),
  createElement(
    "section",
    { "aria-label": "İncelenen kaynaklar" },
    createElement(ConsultedSourceList, { sources: [{ ...citation, verification: "official" }] }),
  ),
  createElement(
    "section",
    { "aria-label": "Derin araştırma atıfları" },
    createElement(StepCard, {
      index: 1,
      step: {
        key: "ictihat",
        title: "Kaynak bağlantı denetimi",
        answer: "Bu bir arayüz testidir.",
        grounded: true,
        error: null,
        note: null,
        citations: [citation, privateCitation].map((c) => ({
          marker: c.marker,
          sourceId: c.source_id,
          sourceType: c.source_type,
          sourceUrl: c.source_url,
          reference: c.reference,
          excerpt: c.excerpt,
          verification: c.verification as "third_party" | "user_document",
        })),
      },
    }),
  ),
);

createRoot(document.getElementById("root")!).render(
  new URLSearchParams(location.search).has("citations")
    ? linkChecks
    : createElement(SourceReader, {
        sourceId: "2de38edc-7b09-466d-98e7-e1b2693d9c76",
        reference: "Yargıtay 3. Hukuk Dairesi · kaynak okuyucu denetimi",
        sourceUrl: "https://karararama.yargitay.gov.tr/getDokuman?id=1219103100",
      }),
);

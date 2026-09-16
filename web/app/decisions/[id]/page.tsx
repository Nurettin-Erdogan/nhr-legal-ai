import Link from "next/link";
import { notFound } from "next/navigation";
import { getLegalSource } from "@/lib/api";

export default async function DecisionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const source = await getLegalSource(id);
  if (!source) notFound();

  const isLegislation = source.source_type === "legislation";
  const isAdministrative = source.source_type === "other";
  const isConstitutionalCourt = source.court_name === "Anayasa Mahkemesi";
  const facts = isLegislation
    ? [
        ["Mevzuat", source.law_name ?? "—"],
        ["Kanun no", source.law_no ?? "—"],
        ["Madde", source.article_no ?? "—"],
        ["Resmî Gazete", source.official_gazette_date ? new Date(source.official_gazette_date).toLocaleDateString("tr-TR") : "—"],
      ]
    : isAdministrative
    ? [
        ["Kurum", source.authority ?? "Kamu Denetçiliği Kurumu"],
        ["Karar no", source.decision_no ?? "—"],
        ["Karar tarihi", source.decision_date ? new Date(source.decision_date).toLocaleDateString("tr-TR") : "—"],
        ["Karar türü", String(source.metadata.decision_type ?? "—")],
      ]
    : [
        ["Daire", source.chamber ?? source.court_name ?? "—"],
        [isConstitutionalCourt ? "Başvuru no" : "Esas no", source.docket_no ?? "—"],
        ["Karar no", source.decision_no ?? "—"],
        ["Karar tarihi", source.decision_date ? new Date(source.decision_date).toLocaleDateString("tr-TR") : "—"],
      ];

  return (
    <main className="detail-page">
      <header className="detail-nav">
        <Link href="/" className="back-link">← Arama sonuçlarına dön</Link>
        <div className="brand compact"><div className="brand-mark">N</div><strong>NHR Legal AI</strong></div>
      </header>
      <article className="decision-document">
        <div className="document-heading">
          <span className="section-kicker">{isLegislation ? "MEVZUAT MADDESİ" : isAdministrative ? "KDK KARARI" : "YÜKSEK YARGI KARARI"}</span>
          <h1>{source.title}</h1>
          <div className="document-facts">
            {facts.map(([label, value]) => <div key={label}><small>{label}</small><strong>{value}</strong></div>)}
          </div>
          {source.source_url && <a className="source-button" href={source.source_url} target="_blank" rel="noreferrer">Resmî kaynağı aç ↗</a>}
        </div>
        <div className="document-body">
          <aside><span>{isLegislation ? "Madde metni" : "Karar metni"}</span><small>{source.chunks.length} RAG parçası</small></aside>
          <div className="legal-text">{source.raw_text}</div>
        </div>
      </article>
    </main>
  );
}

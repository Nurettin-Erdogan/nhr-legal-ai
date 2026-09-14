import Link from "next/link";
import { notFound } from "next/navigation";
import { getDecision } from "@/lib/api";

export default async function DecisionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const decision = await getDecision(id);
  if (!decision) notFound();

  return (
    <main className="detail-page">
      <header className="detail-nav">
        <Link href="/" className="back-link">← Arama sonuçlarına dön</Link>
        <div className="brand compact"><div className="brand-mark">N</div><strong>NHR Legal AI</strong></div>
      </header>
      <article className="decision-document">
        <div className="document-heading">
          <span className="section-kicker">YARGITAY KARARI</span>
          <h1>{decision.title}</h1>
          <div className="document-facts">
            <div><small>Daire</small><strong>{decision.chamber ?? "—"}</strong></div>
            <div><small>Esas no</small><strong>{decision.docket_no ?? "—"}</strong></div>
            <div><small>Karar no</small><strong>{decision.decision_no ?? "—"}</strong></div>
            <div><small>Karar tarihi</small><strong>{decision.decision_date ? new Date(decision.decision_date).toLocaleDateString("tr-TR") : "—"}</strong></div>
          </div>
          {decision.source_url && <a className="source-button" href={decision.source_url} target="_blank" rel="noreferrer">Resmî kaynağı aç ↗</a>}
        </div>
        <div className="document-body">
          <aside><span>Karar metni</span><small>{decision.chunks.length} RAG parçası</small></aside>
          <div className="legal-text">{decision.raw_text}</div>
        </div>
      </article>
    </main>
  );
}

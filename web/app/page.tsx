"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import AppSidebar, { Icon } from "@/app/ui/app-sidebar";
import { API_URL, CorpusStats, LegalSearchResponse } from "@/lib/api";

const initialQuery = "kıdem tazminatı";

export default function Home() {
  const [query, setQuery] = useState(initialQuery);
  const [stats, setStats] = useState<CorpusStats | null>(null);
  const [results, setResults] = useState<LegalSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function runSearch(value: string) {
    const cleaned = value.trim();
    if (cleaned.length < 2) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/api/legal/search?q=${encodeURIComponent(cleaned)}&limit=20`);
      if (!response.ok) throw new Error("Arama servisine ulaşılamadı");
      setResults(await response.json());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Beklenmeyen bir hata oluştu");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetch(`${API_URL}/api/legal/stats`)
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then(setStats)
      .catch(() => setError("API çalışmıyor. Önce FastAPI sunucusunu başlatın."));
    void runSearch(initialQuery);
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    void runSearch(query);
  }

  return (
    <main className="app-shell">
      <AppSidebar active="research" />

      <section className="workspace">
        <header className="topbar">
          <div><span className="eyebrow">NHR ARAŞTIRMA</span><h1>Hukuk araştırması</h1></div>
          <div className="corpus-pill"><span>{stats?.decision_count ?? "—"}</span> yargı kararı · <span>{stats?.other_count ?? "—"}</span> idarî karar · <span>{stats?.legislation_count ?? "—"}</span> mevzuat · <span>{stats?.chunk_count ?? "—"}</span> parça</div>
        </header>

        <div className="content">
          <section className="hero-panel">
            <div>
              <span className="section-kicker">MEVZUAT, YÜKSEK YARGI VE KDK KARARLARI</span>
              <h2>Aradığınız hukuki dayanağa<br/>doğrudan ulaşın.</h2>
              <p>Mevzuat maddeleri ve karar metinlerinde Türkçe kök tabanlı arama yapın; doğrulanabilir resmî kaynağa gidin.</p>
            </div>
            <div className="hero-stat"><small>En güncel karar</small><strong>{stats?.latest_decision_date ? new Date(stats.latest_decision_date).toLocaleDateString("tr-TR") : "—"}</strong></div>
          </section>

          <form className="search-box" onSubmit={submit}>
            <Icon name="search"/>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Örn. kıdem tazminatı, işe iade, fazla mesai…" aria-label="Hukuki arama"/>
            <button disabled={loading || query.trim().length < 2}>{loading ? "Aranıyor…" : "Ara"}</button>
          </form>

          {error && <div className="error-banner">{error}</div>}

          <div className="results-heading">
            <div><h3>Hukuk kaynakları</h3><p>{results ? `“${results.query}” için ${results.total} kaynak` : "Korpus içinde arama yapın"}</p></div>
            <span className="method-badge">Türkçe tam metin</span>
          </div>

          <div className="result-list">
            {results?.results.map((result) => {
              const isLegislation = result.source_type === "legislation";
              const isAdministrative = result.source_type === "other";
              const isConstitutionalCourt = result.court_name === "Anayasa Mahkemesi";
              const sourceDate = isLegislation ? result.official_gazette_date ?? result.version_date : result.decision_date;
              return (
              <article className="result-card" key={result.id}>
                <div className="result-meta"><span>{isLegislation ? `${result.law_name ?? "Mevzuat"} · Madde ${result.article_no ?? "—"}` : isAdministrative ? result.authority ?? "İdarî karar" : result.chamber ?? result.court_name ?? "Yüksek yargı"}</span><time>{sourceDate ? new Date(sourceDate).toLocaleDateString("tr-TR") : "Tarih yok"}</time></div>
                <Link href={`/decisions/${result.id}`}><h4>{result.title}</h4></Link>
                <p>{result.excerpt}</p>
                <footer>
                  <div>{isLegislation ? <><code>Kanun {result.law_no ?? "—"}</code><code>m. {result.article_no ?? "—"}</code></> : isAdministrative ? <code>Karar {result.decision_no ?? "—"}</code> : isConstitutionalCourt ? <code>B. No: {result.docket_no ?? "—"}</code> : <><code>E. {result.docket_no ?? "—"}</code><code>K. {result.decision_no ?? "—"}</code></>}</div>
                  <Link href={`/decisions/${result.id}`}>Kaynağı incele <span>→</span></Link>
                </footer>
              </article>
            )})}
            {!loading && results && results.results.length === 0 && (
              <div className="empty-state"><Icon name="search"/><h4>Sonuç bulunamadı</h4><p>Daha kısa veya farklı bir hukuki ifade deneyin.</p></div>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}

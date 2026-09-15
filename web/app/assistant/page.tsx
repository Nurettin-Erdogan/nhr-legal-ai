"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import AppSidebar, { Icon } from "@/app/ui/app-sidebar";
import { API_URL } from "@/lib/api";

type AIStatus = { provider: string; model: string; configured: boolean };
type Citation = {
  marker: string;
  source_id: string;
  source_type: string;
  title: string;
  reference: string;
  excerpt: string;
};
type AIAnswer = {
  answer: string;
  provider: string;
  model: string;
  citations: Citation[];
  grounded: boolean;
  unverified_markers: string[];
};

const suggestions = [
  "Kıdem tazminatına hak kazanma şartları nelerdir?",
  "İş sözleşmesinin haklı feshi nasıl değerlendirilir?",
  "Yıllık izin alacağının ispat yükü kimdedir?",
];

export default function AssistantPage() {
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [question, setQuestion] = useState(suggestions[0]);
  const [result, setResult] = useState<AIAnswer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API_URL}/api/ai/status`)
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then(setStatus)
      .catch(() => setError("AI servisinin durumuna ulaşılamadı."));
  }, []);

  async function ask(event: FormEvent) {
    event.preventDefault();
    if (question.trim().length < 5) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const response = await fetch(`${API_URL}/api/ai/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ question: question.trim() }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "AI yanıtı üretilemedi");
      setResult(payload);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "AI yanıtı üretilemedi");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <AppSidebar active="assistant" />
      <section className="workspace">
        <header className="topbar">
          <div><span className="eyebrow">KAYNAKLI HUKUK ASİSTANI</span><h1>AI asistanı</h1></div>
          <div className={`ai-status ${status?.configured ? "ready" : "waiting"}`}>
            <i/><span>{status?.configured ? `${status.provider} · ${status.model}` : "Gemini anahtarı bekleniyor"}</span>
          </div>
        </header>

        <div className="assistant-content">
          <section className="assistant-intro">
            <div className="assistant-symbol"><Icon name="spark"/></div>
            <span className="section-kicker">NHR LEGAL AI</span>
            <h2>Hukuki sorunuzu kaynaklarıyla değerlendirin.</h2>
            <p>Asistan önce hukuk korpusunda ilgili mevzuat ve karar parçalarını bulur, sonra yalnızca bu kaynaklara dayanarak cevap üretir.</p>
          </section>

          {!status?.configured && status && (
            <div className="setup-banner">
              <div><strong>Gemini bağlantısı için son bir ayar gerekiyor</strong><span>Proje kökündeki `.env` dosyasına GEMINI_API_KEY ekleyip API’yi yeniden başlatın.</span></div>
              <code>GEMINI_API_KEY=...</code>
            </div>
          )}

          <form className="question-card" onSubmit={ask}>
            <label htmlFor="legal-question">Hukuki sorunuz</label>
            <textarea id="legal-question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={5} placeholder="Somut hukuki sorunuzu yazın…"/>
            <div className="question-actions"><small>Yanıtlar mevcut Yargıtay kararlarıyla sınırlandırılır.</small><button disabled={loading || !status?.configured}>{loading ? "Kaynaklar inceleniyor…" : "Kaynaklı cevap üret"}</button></div>
          </form>

          <div className="suggestion-row">
            {suggestions.map((suggestion) => <button key={suggestion} onClick={() => setQuestion(suggestion)}>{suggestion}</button>)}
          </div>

          {error && <div className="error-banner">{error}</div>}

          {result && (
            <section className="answer-layout">
              <article className="answer-card">
                <div className="answer-heading"><Icon name="spark"/><div><span>AI DEĞERLENDİRMESİ</span><small>{result.provider} · {result.model}</small></div></div>
                {!result.grounded && (
                  <div className="ungrounded-notice">
                    Bu yanıt korpustaki hiçbir kaynağa atıf yapmıyor; hukuki dayanak olarak kullanmayın.
                  </div>
                )}
                <div className="answer-text">{result.answer}</div>
                {result.unverified_markers.length > 0 && (
                  <small className="answer-footnote">
                    Modelin ürettiği {result.unverified_markers.join(", ")} atfı korpusta karşılık bulmadığı için metinden çıkarıldı.
                  </small>
                )}
              </article>
              <aside className="citation-panel">
                <h3>Başvurulan kaynaklar</h3>
                <p>{result.citations.length} kaynak parçası</p>
                {result.citations.map((citation) => (
                  <Link href={`/decisions/${citation.source_id}`} className="citation-card" key={citation.marker}>
                    <span>[{citation.marker}] {citation.source_type === "legislation" ? "Mevzuat" : "Karar"}</span>
                    <strong>{citation.reference}</strong>
                    <small>{citation.excerpt.slice(0, 130)}…</small>
                  </Link>
                ))}
              </aside>
            </section>
          )}
        </div>
      </section>
    </main>
  );
}

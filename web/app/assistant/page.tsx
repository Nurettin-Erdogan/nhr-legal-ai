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
type Project = { id: string; name: string; document_count: number };
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
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");

  useEffect(() => {
    fetch(`${API_URL}/api/ai/status`)
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then(setStatus)
      .catch(() => setError("AI servisinin durumuna ulaşılamadı."));
    fetch(`${API_URL}/api/projects`, { credentials: "include" })
      .then((response) => response.ok ? response.json() : [])
      .then(setProjects)
      .catch(() => setProjects([]));
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
        body: JSON.stringify({
          question: question.trim(),
          project_id: projectId || null,
        }),
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
            <i/><span>{status?.configured ? `${status.provider} · ${status.model}` : "Ollama / Qwen3 bekleniyor"}</span>
          </div>
        </header>

        <div className="assistant-content">
          <section className="assistant-intro">
            <div className="assistant-symbol"><Icon name="spark"/></div>
            <span className="section-kicker">NHR LEGAL AI</span>
            <h2>Hukuki sorunuzu kaynaklarıyla değerlendirin.</h2>
            <p>Asistan hukuk korpusundaki mevzuat ve kararları, proje seçildiğinde de yalnızca o projeye ait belgeleri tarar; cevabı getirilen kaynaklarla sınırlar.</p>
          </section>

          {!status?.configured && status && (
            <div className="setup-banner">
              <div><strong>Qwen3 modeli Ollama'da hazır değil</strong><span>Ollama'yı başlatın, seçili modeli indirin ve API'yi yeniden başlatın.</span></div><code>ollama pull {status.model}</code>
            </div>
          )}

          <form className="question-card" onSubmit={ask}>
            <label htmlFor="legal-question">Hukuki sorunuz</label>
            <textarea id="legal-question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={5} placeholder="Somut hukuki sorunuzu yazın…"/>
            {projects.length > 0 && (
              <div className="assistant-project-row">
                <label htmlFor="assistant-project">Çalışma kapsamı</label>
                <select id="assistant-project" value={projectId} onChange={(event) => setProjectId(event.target.value)}>
                  <option value="">Yalnız merkezi hukuk korpusu</option>
                  {projects.map((project) => <option key={project.id} value={project.id}>{project.name} · {project.document_count} belge</option>)}
                </select>
              </div>
            )}
            <div className="question-actions"><small>{projectId ? "Mevzuat, kararlar ve seçili proje belgeleri birlikte aranır." : "Yanıtlar mevcut mevzuat ve karar kaynaklarıyla sınırlandırılır."}</small><button disabled={loading || !status?.configured}>{loading ? "Kaynaklar inceleniyor…" : "Kaynaklı cevap üret"}</button></div>
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
                {result.citations.map((citation) => {
                  const content = <><span>[{citation.marker}] {citation.source_type === "legislation" ? "Mevzuat" : citation.source_type === "document" ? "Proje belgesi" : citation.source_type === "other" ? "İdarî karar" : "Yargı kararı"}</span><strong>{citation.reference}</strong><small>{citation.excerpt.slice(0, 130)}…</small></>;
                  return citation.source_type === "document" ? (
                    <div className="citation-card" key={citation.marker}>{content}</div>
                  ) : (
                    <Link href={`/decisions/${citation.source_id}`} className="citation-card" key={citation.marker}>{content}</Link>
                  );
                })}
              </aside>
            </section>
          )}
        </div>
      </section>
    </main>
  );
}

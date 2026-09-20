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
  verification?: "official" | "third_party" | "user_document";
};
type Project = { id: string; name: string; document_count: number };
type AIAnswer = {
  answer: string;
  provider: string;
  model: string;
  citations: Citation[];
  grounded: boolean;
  unverified_markers: string[];
  from_cache?: boolean;
};
type PipelineStage = "searching" | "sources_found" | "generating" | "verifying" | "done";

const suggestions = [
  "Kıdem tazminatına hak kazanma şartları nelerdir?",
  "İş sözleşmesinin haklı feshi nasıl değerlendirilir?",
  "Yıllık izin alacağının ispat yükü kimdedir?",
];

const STAGE_ORDER: PipelineStage[] = ["searching", "sources_found", "generating", "verifying"];
const STAGE_LABEL: Record<PipelineStage, string> = {
  searching: "Kaynaklar aranıyor",
  sources_found: "Kaynaklar bulundu",
  generating: "Cevap hazırlanıyor",
  verifying: "Atıflar doğrulanıyor",
  done: "Cevap hazır",
};

function stageIndex(stage: PipelineStage | "") {
  if (!stage || stage === "done") return STAGE_ORDER.length;
  return STAGE_ORDER.indexOf(stage);
}

export default function AssistantPage() {
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [question, setQuestion] = useState(suggestions[0]);
  const [result, setResult] = useState<AIAnswer | null>(null);
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState<PipelineStage | "">("");
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
    setStage("searching");
    try {
      const response = await fetch(`${API_URL}/api/ai/answer/progress`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
        credentials: "include",
        signal: AbortSignal.timeout(150_000),
        body: JSON.stringify({
          question: question.trim(),
          project_id: projectId || null,
        }),
      });
      if (!response.ok || !response.body) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail ?? "AI yanıtı üretilemedi");
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed: AIAnswer | null = null;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const eventPayload = JSON.parse(line) as {
            stage?: string;
            detail?: string;
            result?: AIAnswer;
          };
          if (eventPayload.stage === "error") {
            throw new Error(eventPayload.detail ?? "AI yanıtı üretilemedi");
          }
          if (eventPayload.stage === "searching" || eventPayload.stage === "sources_found"
            || eventPayload.stage === "generating" || eventPayload.stage === "verifying"
            || eventPayload.stage === "done") {
            setStage(eventPayload.stage);
          }
          if (eventPayload.stage === "done" && eventPayload.result) {
            completed = eventPayload.result;
          }
        }
      }
      if (!completed) throw new Error("Doğrulanmış cevap alınamadı");
      setResult(completed);
      setStage("done");
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "TimeoutError") {
        setError("Yanıt 150 saniyede tamamlanamadı. Ollama ve API durumunu kontrol edip yeniden deneyin.");
      } else {
        setError(reason instanceof Error ? reason.message : "AI yanıtı üretilemedi");
      }
      setStage("");
    } finally {
      setLoading(false);
    }
  }

  const buttonLabel = loading
    ? (STAGE_LABEL[stage || "searching"] + "…")
    : "Kaynaklı cevap üret";

  return (
    <main className="app-shell">
      <AppSidebar active="assistant" />
      <section className="workspace">
        <header className="topbar">
          <div><span className="eyebrow">KAYNAKLI HUKUK ASİSTANI</span><h1>AI asistanı</h1></div>
          <div className={`ai-status ${status?.configured ? "ready" : "waiting"}`}>
            <i/><span>{status?.configured ? `${status.provider} · ${status.model}` : "Ollama / DeepSeek bekleniyor"}</span>
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
              <div><strong>DeepSeek modeli Ollama'da hazır değil</strong><span>Ollama'yı başlatın, seçili modeli indirin ve API'yi yeniden başlatın.</span></div><code>ollama pull {status.model}</code>
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
            <div className="question-actions"><small>{projectId ? "Mevzuat, kararlar ve seçili proje belgeleri birlikte aranır." : "Yanıtlar mevcut mevzuat ve karar kaynaklarıyla sınırlandırılır."}</small><button disabled={loading || !status?.configured}>{buttonLabel}</button></div>
          </form>

          <div className="suggestion-row">
            {suggestions.map((suggestion) => <button key={suggestion} onClick={() => setQuestion(suggestion)}>{suggestion}</button>)}
          </div>

          {loading && (
            <div className="assistant-progress" aria-live="polite">
              <ol>
                {STAGE_ORDER.map((item) => {
                  const current = stageIndex(stage || "searching");
                  const itemIndex = STAGE_ORDER.indexOf(item);
                  const className = itemIndex < current ? "done" : itemIndex === current ? "active" : "";
                  return <li key={item} className={className}><span/>{STAGE_LABEL[item]}</li>;
                })}
              </ol>
            </div>
          )}

          {error && <div className="error-banner">{error}</div>}

          {result && (
            <section className="answer-layout">
              <article className="answer-card">
                <div className="answer-heading"><Icon name="spark"/><div><span>AI DEĞERLENDİRMESİ</span><small>{result.provider} · {result.model}{result.from_cache ? " · önbellek" : ""}</small></div></div>
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
                  const kind = citation.source_type === "legislation" ? "Mevzuat" : citation.source_type === "document" ? "Proje belgesi" : citation.source_type === "other" ? "İdarî karar" : "Yargı kararı";
                  const unverified = citation.verification === "third_party";
                  const content = <><span>[{citation.marker}] {kind}{unverified && <em className="citation-unverified" title="Üçüncü taraf arşivden alındı; resmî portalla henüz doğrulanmadı. Kullanmadan önce resmî kaynaktan teyit edin.">doğrulanmadı</em>}</span><strong>{citation.reference}</strong><small>{citation.excerpt.slice(0, 130)}…</small></>;
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

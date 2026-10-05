import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Copy, ExternalLink, Loader2, Search, ShieldAlert, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { inMemoryAccessToken } from "@/lib/auth-api";
import {
  MAX_QUESTION,
  MIN_QUESTION,
  ResearchError,
  canStart,
  loadResearchState,
  progressLine,
  startResearch,
  verificationLabel,
  type ResearchState,
  type ResearchStep,
} from "@/lib/deep-research";

const POLL_MS = 3000;

function StepCard({ step, index }: { step: ResearchStep; index: number }) {
  return (
    <article className="space-y-3 rounded-xl border bg-card p-4" data-testid="research-step">
      <h3 className="font-semibold">
        {index}. {step.title}
      </h3>
      {step.error ? (
        <p role="alert" className="text-sm text-destructive">
          Bu başlık tamamlanamadı: {step.error}
        </p>
      ) : step.note ? (
        <p className="text-sm text-muted-foreground" data-testid="research-note">
          {step.note}
        </p>
      ) : (
        <>
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <ReactMarkdown>{step.answer}</ReactMarkdown>
          </div>
          {!step.grounded && (
            <p className="flex items-start gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-800 dark:text-amber-300" data-testid="research-ungrounded">
              <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" /> Bu bölümün cevabı kaynaklarla yeterince desteklenemedi; dikkatle okuyun.
            </p>
          )}
          {step.citations.length > 0 && (
            <ul className="space-y-1 text-xs" data-testid="research-citations">
              {step.citations.map((citation) => {
                const label = verificationLabel(citation.verification);
                return (
                  <li key={citation.marker} className="flex flex-wrap items-center gap-1.5">
                    <span className="font-mono text-muted-foreground">[{citation.marker}]</span>
                    <span>{citation.reference}</span>
                    {citation.verification === "official" ? (
                      <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" aria-label="Resmî kaynakla doğrulandı" />
                    ) : (
                      <span className="inline-flex items-center gap-1 font-medium text-amber-700 dark:text-amber-400">
                        <ShieldAlert className="h-3.5 w-3.5" /> {label}
                      </span>
                    )}
                    {citation.sourceUrl && (
                      <a href={citation.sourceUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 underline">
                        <ExternalLink className="h-3 w-3" /> kaynak
                      </a>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
    </article>
  );
}

/**
 * Derin araştırma: soru üç sabit eksene (mevzuat, yargı kararları, süre/ispat/usul) bölünür, her eksen kaynaklı cevap hattından geçer ve
 * rapor birleştirilir. Her bölümün cevabı kendi kaynaklarına karşı sunucuda doğrulanır; kaynak yoksa "kaynak bulunamadı" denir.
 */
export function DeepResearch({ examples = [] }: { examples?: string[] }) {
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<ResearchState>({ job: null, latest: null });
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(true);
  const timer = useRef<number | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      const next = await loadResearchState({ token: inMemoryAccessToken() });
      if (!active.current) return;
      setState(next);
      setError("");
      if (next.job?.state === "running") timer.current = window.setTimeout(() => void refresh(), POLL_MS);
    } catch (e) {
      if (active.current) setError(e instanceof Error ? e.message : "Araştırma durumu alınamadı.");
    }
  }, []);

  useEffect(() => {
    active.current = true;
    void refresh();
    return () => {
      active.current = false;
      window.clearTimeout(timer.current);
    };
  }, [refresh]);

  const running = state.job?.state === "running";
  const start = async (text = question) => {
    if (!canStart(text) || starting || running) return;
    setQuestion(text);
    setStarting(true);
    setError("");
    try {
      await startResearch(text, { token: inMemoryAccessToken() });
      window.clearTimeout(timer.current);
      await refresh();
    } catch (e) {
      setError(e instanceof ResearchError || e instanceof Error ? e.message : "Araştırma başlatılamadı.");
    } finally {
      setStarting(false);
    }
  };

  const steps = state.job && (state.job.state === "running" || state.job.steps.length) ? state.job.steps : (state.latest?.steps ?? []);
  const markdown = state.job?.state === "done" || !state.job ? state.latest?.markdown : undefined;
  const copy = async () => {
    if (!markdown) return;
    try {
      await navigator.clipboard.writeText(markdown);
      toast.success("Rapor kopyalandı");
    } catch {
      toast.error("Panoya kopyalanamadı");
    }
  };

  return (
    <div className="space-y-4" data-testid="deep-research">
      <section className="space-y-3 rounded-xl border bg-card p-4">
        <p className="text-sm text-muted-foreground">
          Soru üç başlıkta ayrı ayrı araştırılır: <strong>ilgili mevzuat</strong>, <strong>yargı kararları</strong>, <strong>süre, ispat ve usul</strong>. Her başlığın cevabı yalnız
          korpustaki kaynaklara dayanır ve sunucuda kaynaklara karşı doğrulanır; kaynak bulunamayan başlık açıkça belirtilir. Doktrin ve karşılaştırmalı hukuk kaynakları korpusta
          yoktur. Yerel model kullanıldığından rapor birkaç dakika sürebilir; sayfadan ayrılabilirsiniz, sonuç kaydedilir.
        </p>
        <Textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          rows={4}
          maxLength={MAX_QUESTION}
          aria-label="Araştırma sorusu"
          placeholder="Derinlemesine araştırılmasını istediğiniz hukuki soruyu yazın (en az 15 karakter)…"
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void start()} disabled={!canStart(question) || starting || running}>
            {starting || running ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
            Araştır
          </Button>
          {question.trim().length > 0 && question.trim().length < MIN_QUESTION && <span className="text-xs text-muted-foreground">En az {MIN_QUESTION} karakter yazın.</span>}
        </div>
        {!running && examples.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {examples.map((example) => (
              <button key={example} type="button" className="rounded-full border px-3 py-1 text-left text-xs text-muted-foreground hover:bg-accent" onClick={() => setQuestion(example)}>
                {example}
              </button>
            ))}
          </div>
        )}
      </section>

      {error && (
        <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
          {error}
        </div>
      )}
      {state.job && (
        <p role="status" className="text-sm font-medium" data-testid="research-progress">
          {running && <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />}
          {progressLine(state.job)}
        </p>
      )}
      {!state.job && state.latest && (
        <p className="text-xs text-muted-foreground" data-testid="research-saved-note">
          Kayıtlı son rapor gösteriliyor ({new Date(state.latest.createdAt).toLocaleString("tr-TR")}): “{state.latest.question.slice(0, 120)}”
        </p>
      )}
      {steps.length > 0 && (
        <div className="space-y-3">
          {steps.map((step, index) => (
            <StepCard key={`${step.key}-${index}`} step={step} index={index + 1} />
          ))}
          {markdown && (
            <Button variant="outline" size="sm" onClick={() => void copy()}>
              <Copy className="mr-1.5 h-3.5 w-3.5" /> Raporu kopyala
            </Button>
          )}
          <p className="text-xs text-muted-foreground">Bu rapor hukuki görüş yerine geçmez; atıf yapılan kaynakları özgün metinlerinden kontrol edin.</p>
        </div>
      )}
    </div>
  );
}

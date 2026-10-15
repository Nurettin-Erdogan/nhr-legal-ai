import { useCallback, useEffect, useRef, useState } from "react";
import { Copy, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { DocumentJobPanel } from "@/components/DocumentJobPanel";
import { startDocumentJob } from "@/lib/document-jobs";
import ReactMarkdown from "react-markdown";
import { inMemoryAccessToken } from "@/lib/auth-api";
import {
  SummaryError,
  cell,
  coverageNote,
  hasFacts,
  loadFacts,
  loadSummaryState,
  progressText,
  startSummary,
  summaryMarkdown,
  type FactsResponse,
  type SummaryDocument,
  type SummaryState,
} from "@/lib/case-summary";

const POLL_MS = 3000;
const MAX_SELECTED = 2000;

function SummaryCard({ document }: { document: SummaryDocument }) {
  const note = coverageNote(document);
  return (
    <article className="space-y-2 rounded-xl border bg-card p-4" data-testid="summary-card">
      <h4 className="font-semibold leading-snug">{document.fileName}</h4>
      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        <span>Kullanıcı belgesi</span>
        {document.ocr && (
          <span className="text-amber-700 dark:text-amber-400">
            OCR ile okundu: okuma hataları olabilir
          </span>
        )}
        {note && <span data-testid="summary-coverage">{note}</span>}
      </div>
      {document.error ? (
        <p className="text-sm text-destructive" role="alert">
          {document.error}
        </p>
      ) : (
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {document.bullets.map((bullet, index) => (
            <li key={index}>{bullet}</li>
          ))}
        </ul>
      )}
      {document.dropped > 0 && (
        <p className="text-xs text-muted-foreground" data-testid="summary-dropped">
          {document.dropped} madde belgeyle eşleşmediği için gösterilmedi.
        </p>
      )}
    </article>
  );
}

/**
 * "Dosya Özeti": davaya bağlı belgelerden (1) belirleyici olgu tablosu (tarih, tutar, esas/karar, kanun numarası; yapay zekâ yok) ve
 * (2) yerel modelle belge belge özet. Özet maddeleri sunucuda belgeyle doğrulanır; hukuki dayanak ya da resmî kaynak değildir.
 */
export function CaseDocumentSummary({ caseId }: { caseId: string }) {
  const [facts, setFacts] = useState<FactsResponse>();
  const [factsError, setFactsError] = useState("");
  const [state, setState] = useState<SummaryState>({ job: null, latest: null });
  const [selected, setSelected] = useState<string[]>([]);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [newJobId, setNewJobId] = useState<string>();
  const [newOutput, setNewOutput] = useState("");
  const active = useRef(true);
  const timer = useRef<number | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      const next = await loadSummaryState(caseId, { token: inMemoryAccessToken() });
      if (!active.current) return;
      setState(next);
      setError("");
      if (next.job?.state === "running") {
        timer.current = window.setTimeout(() => void refresh(), POLL_MS);
      }
    } catch (e) {
      if (!active.current) return;
      setError(e instanceof Error ? e.message : "Özet durumu alınamadı.");
    }
  }, [caseId]);

  useEffect(() => {
    active.current = true;
    loadFacts(caseId, { token: inMemoryAccessToken() })
      .then((result) => {
        if (!active.current) return;
        setFacts(result);
        setSelected(result.documents.slice(0, MAX_SELECTED).map((item) => item.id));
      })
      .catch((e) => {
        if (active.current)
          setFactsError(e instanceof Error ? e.message : "Olgu tablosu alınamadı.");
      });
    void refresh();
    return () => {
      active.current = false;
      window.clearTimeout(timer.current);
    };
  }, [caseId, refresh]);

  const running = state.job?.state === "running";
  const toggle = (id: string) =>
    setSelected((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : current.length >= MAX_SELECTED
          ? current
          : [...current, id],
    );

  const start = async () => {
    if (!selected.length || starting || running) return;
    setStarting(true);
    setError("");
    try {
      setNewJobId(
        await startDocumentJob({
          module: "auto_summary",
          document_ids: selected,
          case_id: caseId,
          title: "Dosya özeti",
          prompt: "Dosya belgelerini ayrı ayrı özetle.",
        }),
      );
    } catch (e) {
      setError(e instanceof SummaryError || e instanceof Error ? e.message : "Özet başlatılamadı.");
    } finally {
      setStarting(false);
    }
  };

  const shown: SummaryDocument[] =
    state.job && state.job.state !== "running"
      ? state.job.results
      : state.job?.results.length
        ? state.job.results
        : (state.latest?.documents ?? []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(summaryMarkdown(shown));
      toast.success("Özet kopyalandı");
    } catch {
      toast.error("Panoya kopyalanamadı");
    }
  };

  return (
    <div className="space-y-6" data-testid="case-document-summary">
      <DocumentJobPanel
        jobId={newJobId}
        module="auto_summary"
        onCompleted={(job) => {
          if (job.output) setNewOutput(job.output);
        }}
      />
      {newOutput && (
        <div className="prose prose-sm max-w-none dark:prose-invert">
          <ReactMarkdown components={{ img: () => null }}>{newOutput}</ReactMarkdown>
        </div>
      )}
      <section className="space-y-3">
        <h3 className="font-semibold">Olgu tablosu</h3>
        <p className="text-sm text-muted-foreground">
          Belgelerde aynen geçen tarih, tutar, esas/karar ve kanun numaraları. Yapay zekâ
          kullanılmaz; değerler metinden doğrudan çıkarılır. Kişisel kimlik numaraları çıkarılmaz.
        </p>
        {factsError && (
          <p role="alert" className="text-sm text-destructive">
            {factsError}
          </p>
        )}
        {!facts && !factsError && (
          <p role="status" className="text-sm text-muted-foreground">
            Belgeler okunuyor…
          </p>
        )}
        {facts && facts.documents.length === 0 && (
          <p className="rounded-lg border p-3 text-sm text-muted-foreground" role="status">
            Okunmuş (aranabilir) belge yok
            {facts.total > 0
              ? `: davadaki ${facts.total} belgeden hiçbiri henüz işlenmedi ya da okunamadı`
              : ""}
            .
          </p>
        )}
        {facts && facts.documents.length > 0 && (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-left text-sm" data-testid="facts-table">
              <thead className="bg-muted/50 text-xs text-muted-foreground">
                <tr>
                  <th className="p-2">Belge</th>
                  <th className="p-2">Tarihler</th>
                  <th className="p-2">Tutarlar</th>
                  <th className="p-2">Esas / Karar</th>
                  <th className="p-2">Kanun no</th>
                </tr>
              </thead>
              <tbody>
                {facts.documents.map((item) => (
                  <tr key={item.id} className="border-t align-top">
                    <td className="p-2 font-medium">
                      {item.fileName}
                      {item.ocr && (
                        <span className="ml-1 text-xs font-normal text-amber-700 dark:text-amber-400">
                          (OCR)
                        </span>
                      )}
                      {!hasFacts(item) && (
                        <span className="block text-xs font-normal text-muted-foreground">
                          Çıkarılabilir olgu bulunamadı.
                        </span>
                      )}
                    </td>
                    <td className="p-2">{cell(item.dates)}</td>
                    <td className="p-2">{cell(item.amounts)}</td>
                    <td className="p-2">
                      {cell([
                        ...item.esas.map((value) => `E. ${value}`),
                        ...item.karar.map((value) => `K. ${value}`),
                        ...item.numbers,
                      ])}
                    </td>
                    <td className="p-2">{cell(item.laws)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {facts && facts.ready < facts.total && (
          <p className="text-xs text-muted-foreground">
            Davadaki {facts.total} belgeden {facts.ready} tanesi okunmuş; kalanlar henüz işlenmedi
            ya da okunamadı, tabloda yok.
          </p>
        )}
      </section>

      <section className="space-y-3">
        <h3 className="flex items-center gap-2 font-semibold">
          <Sparkles className="h-4 w-4" /> Yapay zekâ özeti
        </h3>
        <p className="text-sm text-muted-foreground">
          Seçtiğiniz belgeleri yerel model belge belge özetler (belge başına genellikle yarım ile
          birkaç dakika). Özet maddeleri belgeyle sunucuda doğrulanır: belgede olmayan tutar, tarih
          ya da numara içeren ve belgeyle örtüşmeyen maddeler gösterilmez. İşi başlattıktan sonra
          sayfadan ayrılabilirsiniz; sonuç kaydedilir.
        </p>
        {facts && facts.documents.length > 0 && (
          <div className="space-y-2">
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
              {facts.documents.map((item) => (
                <label key={item.id} className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={selected.includes(item.id)}
                    disabled={running}
                    onChange={() => toggle(item.id)}
                  />
                  {item.fileName}
                </label>
              ))}
            </div>
            {facts.documents.length > MAX_SELECTED && (
              <p className="text-xs text-muted-foreground">
                Bir işte en çok {MAX_SELECTED} belge seçilebilir.
              </p>
            )}
            <Button onClick={() => void start()} disabled={!selected.length || starting || running}>
              {starting || running ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="mr-2 h-4 w-4" />
              )}
              Özet oluştur ({selected.length} belge)
            </Button>
          </div>
        )}
        {error && (
          <div
            role="alert"
            className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm"
          >
            {error}
          </div>
        )}
        {state.job && (
          <p role="status" className="text-sm font-medium" data-testid="summary-progress">
            {running && <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />}
            {progressText(state.job)}
          </p>
        )}
        {!state.job && state.latest && (
          <p className="text-xs text-muted-foreground" data-testid="summary-saved-note">
            Kayıtlı son özet gösteriliyor (
            {new Date(state.latest.createdAt).toLocaleString("tr-TR")}
            {state.latest.model ? ` · ${state.latest.model}` : ""}).
          </p>
        )}
        {shown.length > 0 && (
          <div className="space-y-3">
            {shown.map((document) => (
              <SummaryCard key={document.documentId} document={document} />
            ))}
            {!running && (
              <Button variant="outline" size="sm" onClick={() => void copy()}>
                <Copy className="mr-1.5 h-3.5 w-3.5" /> Özeti kopyala
              </Button>
            )}
            <p className="text-xs text-muted-foreground">
              Bu özet yapay zekâ ürünüdür: belgeyle karşılaştırın. Hukuki dayanak ya da resmî kaynak
              değildir; belgedeki ifadeler bir tarafın iddiası olabilir.
            </p>
          </div>
        )}
      </section>
    </div>
  );
}

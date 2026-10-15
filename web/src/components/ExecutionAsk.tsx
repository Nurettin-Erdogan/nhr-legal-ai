import { useRef, useState } from "react";
import { Loader2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Link } from "@/lib/router-compat";
import { dateTr, daysAgo, namesLine } from "@/lib/execution";
import { answerHeadline, askExecution, type AskAnswer } from "@/lib/execution-ask";

const STARTERS = [
  "Açık dosyalarım hangileri?",
  "Hangi dosyalarımda araç sorgusu VAR yazıyor?",
  "En uzun süredir işlem yapılmayan dosyalar",
  "Kesinleşme bilgisi girilmemiş dosyalar",
];

/**
 * İcra Takibi sayfasındaki "Dosyalarıma sor" kutusu. Soru bir dil modeline gitmez: sunucu onu bir süzgece çevirir ve UYAP
 * kayıtlarına uygular. Sorunun nasıl anlaşıldığı ve her dosyada eşleşmeyi sağlayan kayıt satırı gösterilir.
 */
export function ExecutionAsk() {
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<{ loading?: boolean; answer?: AskAnswer; error?: string }>({});
  const pending = useRef<AbortController | null>(null);

  const ask = async (value: string) => {
    const asked = value.trim();
    if (asked.length < 2) return;
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setQuestion(asked);
    setState({ loading: true });
    try {
      const answer = await askExecution(asked, controller.signal);
      if (!controller.signal.aborted) setState({ answer });
    } catch (error) {
      if (!controller.signal.aborted) setState({ error: error instanceof Error ? error.message : "Soru yanıtlanamadı." });
    }
  };

  const { answer } = state;
  const examples = answer && answer.examples.length ? answer.examples : STARTERS;

  return (
    <section className="mb-5 rounded-2xl border border-border bg-card p-4 shadow-card-elite" aria-labelledby="execution-ask-title" data-testid="execution-ask">
      <h2 id="execution-ask-title" className="text-sm font-semibold">
        Dosyalarıma sor
      </h2>
      <p className="mt-0.5 text-xs text-muted-foreground">
        Bütün icra dosyalarınızda UYAP kayıtlarına göre arar: durum, borçlu sorguları, işlemler, son işlem tarihi, taraf adı. Cevap her
        zaman kayıtların kendisidir; tahmin içermez.
      </p>
      <form
        className="mt-3 flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void ask(question);
        }}
      >
        <div className="relative min-w-[220px] flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            maxLength={300}
            placeholder="Örn. hangi dosyalarımda araç sorgusu VAR yazıyor?"
            aria-label="Dosyalarıma sor"
            className="h-10 w-full rounded-lg border border-transparent bg-secondary/60 pl-10 pr-4 text-sm outline-none focus:border-primary/40"
          />
        </div>
        <Button type="submit" disabled={state.loading || question.trim().length < 2}>
          {state.loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Sor"}
        </Button>
      </form>
      <div className="mt-2 flex flex-wrap gap-1.5" role="group" aria-label="Örnek sorular">
        {examples.slice(0, 6).map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => void ask(example)}
            className="rounded-full border border-border bg-secondary/40 px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
          >
            {example}
          </button>
        ))}
      </div>

      {state.error && (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {state.error}
        </p>
      )}

      {answer && (
        <div className="mt-4" data-testid="execution-ask-answer">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-sm font-semibold" data-testid="execution-ask-headline">
              {answerHeadline(answer)}
            </span>
            {answer.understood.length > 0 && (
              <span className="text-xs text-muted-foreground" data-testid="execution-ask-understood">
                Şöyle anladım: {answer.understood.join(" · ")}
              </span>
            )}
          </div>
          {answer.note && (
            <p role="note" className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-800 dark:text-amber-300">
              {answer.note}
            </p>
          )}
          {answer.ok && answer.rows.length === 0 && <p className="mt-2 text-sm text-muted-foreground">Bu süzgece uyan dosya yok.</p>}
          {answer.rows.length > 0 && (
            <ul className="mt-3 divide-y divide-border rounded-xl border border-border" data-testid="execution-ask-rows">
              {answer.rows.map((row) => (
                <li key={row.caseId} className="p-3 text-sm sm:px-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
                    <Link to={`/dashboard/cases/${row.caseId}?tab=icra`} className="font-medium hover:underline">
                      {row.fileNo ?? "Numarasız dosya"}
                      <span className="font-normal text-muted-foreground"> · {row.court}</span>
                    </Link>
                    <span className="text-xs text-muted-foreground">
                      {row.status ? `UYAP durumu: ${row.status}` : ""}
                      {row.lastActivity ? `${row.status ? " · " : ""}son işlem ${dateTr(row.lastActivity)} (${daysAgo(row.daysSinceLast)})` : ""}
                    </span>
                  </div>
                  {(row.creditors.length > 0 || row.debtors.length > 0) && (
                    <div className="mt-0.5 break-words text-xs text-muted-foreground">
                      {row.creditors.length > 0 && `Alacaklı: ${namesLine(row.creditors)}`}
                      {row.creditors.length > 0 && row.debtors.length > 0 && " · "}
                      {row.debtors.length > 0 && `Borçlu: ${namesLine(row.debtors)}`}
                    </div>
                  )}
                  {row.facts.length > 0 && (
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs">
                      {row.facts.map((fact) => (
                        <li key={fact} className="break-words">
                          {fact}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}
          {answer.ok && (
            <p className="mt-2 text-xs text-muted-foreground">
              Satırlar UYAP'tan çekilen kayıtlardır; “VAR” ve “YOK” UYAP'ın yazdığı ifadedir, içeriği için dosyadaki sorgu sonucuna bakın.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

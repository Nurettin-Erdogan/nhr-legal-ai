import { useCallback, useEffect, useRef, useState } from "react";
import { decisionSourceName } from "@/lib/source-label";
import { Button } from "@/components/ui/button";
import { SourceReader } from "@/components/SourceReader";

interface Source {
  source_id: string;
  reference: string;
  source_url: string | null;
  verification: string;
  excerpt: string;
}

interface Page {
  verification_pending?: number;
  /** Konu çok geniş: eşleşen kayıtların yalnız bir bölümü tarandı, liste eksik olabilir. */
  partial?: boolean;
  total: number | null;
  search_text: string;
  required_phrase: string;
  has_more: boolean;
  next_offset: number | null;
  results: Source[];
}

const BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export function ResearchSources({
  question,
  autoLoad = false,
}: {
  question: string;
  autoLoad?: boolean;
}) {
  const [sources, setSources] = useState<Source[]>([]);
  const [page, setPage] = useState<Page | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  const autoStarted = useRef(false);

  const load = useCallback(
    async (offset: number) => {
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      setBusy(true);
      setError("");
      try {
        const params = new URLSearchParams({ q: question, limit: "10", offset: String(offset) });
        const response = await fetch(`${BASE}/api/ai/sources?${params}`, {
          credentials: "include",
          signal: controller.signal,
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail ?? "Kaynak araması tamamlanamadı.");
        if (controller.signal.aborted) return;
        const next = payload as Page;
        setPage(next);
        setSources((previous) => {
          const combined = new Map((offset === 0 ? [] : previous).map((s) => [s.source_id, s]));
          next.results
            .filter((s) => s.verification === "official")
            .forEach((s) => combined.set(s.source_id, s));
          return [...combined.values()];
        });
      } catch (e) {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "Kaynaklar alınamadı.");
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    },
    [question],
  );

  useEffect(() => {
    setSources([]);
    setPage(null);
    setError("");
    setBusy(false);
    autoStarted.current = false;
    return () => {
      request.current?.abort();
      autoStarted.current = false;
    };
  }, [question]);

  useEffect(() => {
    // Only the newly completed answer starts a single first page. Changing
    // loading state must not erase results or launch repeated portal requests.
    if (autoLoad && !autoStarted.current) {
      autoStarted.current = true;
      void load(0);
    }
  }, [autoLoad, load]);

  return (
    <section
      aria-label="Soruyla eşleşen korpus kaynakları"
      className="mt-3 rounded-xl border border-border bg-card text-foreground p-3 text-left"
    >
      <h4 className="text-sm font-semibold">
        Doğrulanmış araştırma kaynakları
        {page?.total ? ` · ${page.total.toLocaleString("tr-TR")} kaynak` : ""}
      </h4>
      <p className="text-xs text-muted-foreground mt-1">
        İlgili kayıtlar resmî kaynakla doğrulandıktan sonra gösterilir. Bu liste cevapta kullanılan
        atıflardan bağımsızdır; iki kaynakla sınırlı değildir.
      </p>
      {page && (
        <p className="text-xs text-muted-foreground mt-1">
          Arama: {page.search_text}
          {page.required_phrase ? ` · Birlikte aranan: “${page.required_phrase}”` : ""}
        </p>
      )}
      <div className="max-h-96 overflow-y-auto mt-2 space-y-3">
        {sources.map((source, index) => (
          <article key={source.source_id} className="border-t border-border pt-2 text-xs">
            <p className="font-medium">
              {index + 1}. {source.reference}
            </p>
            <span className="text-foreground/80">{decisionSourceName(source.source_url)}</span>
            <SourceReader
              sourceId={source.source_id}
              reference={source.reference}
              sourceUrl={source.source_url}
              excerpt={source.excerpt}
              className="ml-3 underline text-primary"
            >
              Kaynağı aç
            </SourceReader>
            <details className="mt-1">
              <summary className="cursor-pointer">Eşleşen metin parçası</summary>
              <p className="whitespace-pre-wrap mt-2 leading-relaxed">{source.excerpt}</p>
            </details>
          </article>
        ))}
      </div>
      {error && (
        <p role="alert" className="text-xs text-destructive mt-2">
          {error}
        </p>
      )}
      {!!page?.verification_pending && (
        <p role="status" className="text-xs text-amber-700 dark:text-amber-400 mt-2">
          Bu sayfadaki {page.verification_pending} adayın resmî doğrulaması tamamlanamadı; bu
          kayıtlar gösterilmiyor.
        </p>
      )}
      {page?.partial && (
        <p
          role="status"
          className="text-xs text-amber-700 dark:text-amber-400 mt-2"
          data-testid="research-partial"
        >
          Konu çok geniş: eşleşen kayıtların yalnız bir bölümü tarandı, liste eksik olabilir. Daha
          eksiksiz sonuç için aramayı daraltın (kanun maddesi, daire ya da yıl ekleyin).
        </p>
      )}
      {busy && (
        <p role="status" className="text-xs mt-2">
          Korpus kaynakları aranıyor…
        </p>
      )}
      {!busy && !error && !page && (
        <Button size="sm" variant="outline" className="mt-2" onClick={() => load(0)}>
          Bu sorunun kaynaklarını ara
        </Button>
      )}
      {!busy && !error && page?.total === 0 && (
        <p className="text-xs mt-2" data-testid="research-empty">
          Soru cümlesindeki sözcüklerin hepsini birlikte içeren kayıt bulunamadı; bu, korpusta hiç
          veri olmadığı anlamına gelmez. Cevaptaki atıflar bu aramadan bağımsızdır. Daha kısa bir
          konu ifadesiyle (ör. “kira artışı”) arayabilirsiniz.
        </p>
      )}
      {!busy && (error || page?.has_more) && (
        <Button
          size="sm"
          variant="outline"
          className="mt-2"
          onClick={() => load(page?.next_offset ?? 0)}
        >
          {error ? "Yeniden dene" : `Devamını getir (${sources.length} gösteriliyor)`}
        </Button>
      )}
    </section>
  );
}

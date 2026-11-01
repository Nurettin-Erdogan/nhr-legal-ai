import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useSearchParam } from "@/lib/router-hooks";
import {
  DEFAULT_FILTERS,
  MIN_QUERY_LENGTH,
  SearchError,
  citationOf,
  facetsOf,
  filterAndSort,
  highlightSegments,
  searchDecisions,
  sourceTypeLabel,
  verificationBadge,
  type Filters,
  type SearchHit,
  type SearchMode,
  type SearchPage,
} from "@/lib/decision-search";
import { toast } from "sonner";
import { citationSuffix } from "@/lib/source-label";
import { SourceReader } from "@/components/SourceReader";
import { Copy, Loader2, Search } from "lucide-react";

const PAGE_SIZE = 10;
const MAX_RESULTS = 200;

function Highlighted({ content, query }: { content: string; query: string }) {
  return (
    <>
      {highlightSegments(content, query).map((segment, index) =>
        segment.match ? (
          <mark
            key={index}
            className="rounded bg-amber-200/70 px-0.5 text-foreground dark:bg-amber-500/30"
          >
            {segment.text}
          </mark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </>
  );
}

function Card({ hit, query }: { hit: SearchHit; query: string }) {
  const badge = verificationBadge(hit.verification, hit.sourceUrl, hit.courtName, hit.sourceType);
  const meta = [
    hit.sourceType === "legislation"
      ? [hit.lawName, hit.articleNo && `m. ${hit.articleNo}`, hit.articleTitle]
          .filter(Boolean)
          .join(" · ")
      : [
          hit.chamber,
          hit.docketNo && `E. ${hit.docketNo}`,
          hit.decisionNo && `K. ${hit.decisionNo}`,
        ]
          .filter(Boolean)
          .join(" · "),
    hit.decisionDate,
  ].filter(Boolean);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(
        `${citationOf(hit)}${citationSuffix(hit.verification, hit.sourceUrl)}`,
      );
      toast.success("Atıf kopyalandı");
    } catch {
      toast.error("Panoya kopyalanamadı");
    }
  };

  return (
    <article
      className="rounded-xl border bg-card p-4 space-y-2"
      data-testid="decision-card"
      data-verification={hit.verification}
    >
      <div className="flex flex-wrap items-start gap-2">
        <h3 className="flex-1 min-w-0 font-semibold leading-snug">{hit.title}</h3>
        <Badge variant="outline">{sourceTypeLabel(hit.sourceType)}</Badge>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {meta.map((part) => (
          <span key={String(part)}>{part}</span>
        ))}
        <span className="font-medium text-foreground/80" data-testid="decision-source-tag">
          {badge.label}
        </span>
      </div>
      {hit.excerpt && (
        <p className="text-sm leading-relaxed text-foreground/90">
          <Highlighted content={hit.excerpt} query={query} />
        </p>
      )}
      <div className="flex flex-wrap gap-2 pt-1">
        <SourceReader
          sourceId={hit.id}
          reference={citationOf(hit)}
          sourceUrl={hit.sourceUrl}
          excerpt={hit.excerpt}
          className="rounded-md border px-3 py-2 text-xs font-medium hover:bg-muted"
        >
          Kaynağı aç
        </SourceReader>
        <Button size="sm" variant="ghost" onClick={() => void copy()}>
          <Copy className="h-3.5 w-3.5 mr-1.5" /> Atıf kopyala
        </Button>
      </div>
    </article>
  );
}

/**
 * Karar/mevzuat arama sonuç listesi: karar kartları (mahkeme, daire, esas-karar no, tarih, eşleşen pasaj), doğrulama rozeti,
 * süzgeçler ve tam metin. Veri `/api/legal/search`tan gelir; AI cevabı değil, kaynakların kendisidir.
 */
export function DecisionSearch({
  examples = [],
  placeholder,
  narrativeExamples = [],
  initialMode = "keyword",
}: {
  examples?: string[];
  placeholder?: string;
  narrativeExamples?: string[];
  initialMode?: SearchMode;
}) {
  const [mode, setMode] = useState<SearchMode>(initialMode);
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [page, setPage] = useState<SearchPage | null>(null);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  const run = useCallback(async (text: string, offset: number, searchMode: SearchMode) => {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setError("");
    try {
      const next = await searchDecisions(text, {
        limit: PAGE_SIZE,
        offset,
        mode: searchMode,
        signal: abort.signal,
      });
      if (abort.signal.aborted) return;
      setPage(next);
      setHits((previous) => {
        const known = new Map((offset === 0 ? [] : previous).map((hit) => [hit.id, hit]));
        for (const hit of next.hits) known.set(hit.id, hit);
        return [...known.values()];
      });
    } catch (e) {
      if (abort.signal.aborted) return;
      setError(e instanceof SearchError || e instanceof Error ? e.message : "Arama tamamlanamadı.");
    } finally {
      if (!abort.signal.aborted) setBusy(false);
    }
  }, []);

  const submit = (text = query) => {
    const clean = text.trim();
    if (clean.length < MIN_QUERY_LENGTH[mode]) {
      setError(
        mode === "narrative"
          ? "Olayı en az 10 karakterle, bir iki cümleyle anlatın."
          : "Arama için en az 2 karakter yazın.",
      );
      return;
    }
    setQuery(clean);
    setSubmitted(clean);
    setFilters(DEFAULT_FILTERS);
    setHits([]);
    setPage(null);
    void run(clean, 0, mode);
  };

  // Üst çubuktaki genel aramadan gelen terim ("?q=…") sayfa açılırken ve terim değiştikçe aranır.
  const urlQuery = useSearchParam("q");
  useEffect(() => {
    if (urlQuery.trim()) submit(urlQuery);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlQuery]);

  const switchMode = (next: SearchMode) => {
    if (next === mode) return;
    controller.current?.abort();
    setMode(next);
    setSubmitted("");
    setHits([]);
    setPage(null);
    setError("");
    setBusy(false);
    setFilters(DEFAULT_FILTERS);
  };
  const activeExamples = mode === "narrative" ? narrativeExamples : examples;

  const facets = useMemo(() => facetsOf(hits), [hits]);
  const shown = useMemo(() => filterAndSort(hits, filters), [hits, filters]);
  // Sunucu derin sayfalamayı 200 sonuçla sınırlar (daha fazlası yavaş aday taraması demek): daha fazlası için aramayı daraltın.
  const hasMore = !!page && hits.length < Math.min(page.total, MAX_RESULTS) && page.hits.length > 0;
  const hiddenByFilter = hits.length - shown.length;
  const set = <K extends keyof Filters>(key: K, value: Filters[K]) =>
    setFilters((current) => ({ ...current, [key]: value }));

  return (
    <section
      className="rounded-xl border bg-card p-4 sm:p-5 space-y-4 mb-6"
      aria-label="Karar ve mevzuat arama"
      data-testid="decision-search"
    >
      <div
        role="tablist"
        aria-label="Arama türü"
        className="flex flex-wrap gap-1 rounded-lg bg-muted p-1 w-fit text-sm"
      >
        {(["keyword", "narrative"] as const).map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={mode === value}
            onClick={() => switchMode(value)}
            className={`rounded-md px-3 py-1.5 ${mode === value ? "bg-background font-medium shadow-sm" : "text-muted-foreground"}`}
          >
            {value === "keyword" ? "Anahtar kelime" : "Olayı anlat (deneysel)"}
          </button>
        ))}
      </div>
      {mode === "narrative" && (
        <p className="text-xs text-muted-foreground" data-testid="narrative-note">
          Olayı bir iki cümleyle anlatın; sohbet asistanının kullandığı arama benzer karar ve
          maddeleri listeler. Sonuçlar eksik ya da konu dışı olabilir: her sonuçtaki doğrulama
          rozetine ve eşleşen pasaja bakın. Yapay zekâ cevabı değil, kaynakların kendisidir.
        </p>
      )}
      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={
            mode === "narrative"
              ? "Olayı anlatın (örn. işçi haklı nedenle işten ayrıldı, son 3 maaşı ödenmedi; hangi haklara sahip?)"
              : (placeholder ??
                "Konu, kavram ya da kanun maddesi yazın (örn. kıdem tazminatı, ihtiyati tedbir, 4857 sayılı Kanun 25)")
          }
          aria-label={mode === "narrative" ? "Olay anlatımı" : "Aranacak ifade"}
          maxLength={mode === "narrative" ? 1500 : 300}
        />
        <Button type="submit" disabled={busy} className="sm:w-32">
          {busy ? (
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <Search className="h-4 w-4 mr-2" />
          )}
          Ara
        </Button>
      </form>

      {!submitted && activeExamples.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {activeExamples.map((example) => (
            <button
              key={example}
              type="button"
              className="rounded-full border px-3 py-1 text-xs text-muted-foreground hover:bg-accent"
              onClick={() => submit(example)}
            >
              {example}
            </button>
          ))}
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
      {busy && !hits.length && (
        <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />{" "}
          {mode === "narrative"
            ? "Olay çözümleniyor ve korpus taranıyor… ilk aramada 20-40 saniye sürebilir."
            : "Korpus taranıyor… yaygın konularda 10-20 saniye sürebilir."}
        </p>
      )}

      {page && (
        <div className="space-y-3">
          <div
            className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm"
            role="status"
            aria-live="polite"
          >
            <span className="font-medium" data-testid="decision-total">
              {page.total === 0
                ? "Eşleşme yok"
                : `${page.partial && mode === "keyword" ? "En az " : ""}${page.total.toLocaleString("tr-TR")} sonuç`}
            </span>
            {hits.length > 0 && (
              <span className="text-muted-foreground">{hits.length} gösteriliyor</span>
            )}
          </div>
          {page.partial && (
            <p
              className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-800 dark:text-amber-300"
              data-testid="decision-partial"
            >
              {mode === "narrative"
                ? "Bu liste en iyi eşleşen yaklaşık 60 kaynakla sınırlıdır; korpusun tamamı taranmadı."
                : "Konu çok geniş: eşleşen kayıtların yalnız bir bölümü tarandı, liste eksik olabilir. Daha eksiksiz sonuç için aramayı daraltın (kanun maddesi, daire ya da yıl ekleyin)."}
            </p>
          )}
          {page.total === 0 && (
            <p className="text-xs text-muted-foreground">
              Bu koşullarla eşleşme bulunamadı; bu, korpusta hiç veri olmadığı anlamına gelmez. Daha
              az ya da daha genel sözcüklerle deneyin.
            </p>
          )}

          {hits.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <select
                aria-label="Mercii"
                className="h-8 rounded-md border bg-background px-2"
                value={filters.authority}
                onChange={(event) => set("authority", event.target.value)}
              >
                <option value="">Tüm merciler</option>
                {facets.authorities.map((entry) => (
                  <option key={entry.value} value={entry.value}>
                    {entry.value} ({entry.count})
                  </option>
                ))}
              </select>
              <select
                aria-label="Yıl"
                className="h-8 rounded-md border bg-background px-2"
                value={filters.year}
                onChange={(event) => set("year", event.target.value)}
              >
                <option value="">Tüm yıllar</option>
                {facets.years.map((entry) => (
                  <option key={entry.value} value={entry.value}>
                    {entry.value} ({entry.count})
                  </option>
                ))}
              </select>
              {facets.types.length > 1 && (
                <select
                  aria-label="Tür"
                  className="h-8 rounded-md border bg-background px-2"
                  value={filters.sourceType}
                  onChange={(event) => set("sourceType", event.target.value)}
                >
                  <option value="">Karar ve mevzuat</option>
                  {facets.types.map((entry) => (
                    <option key={entry.value} value={entry.value}>
                      {sourceTypeLabel(entry.value)} ({entry.count})
                    </option>
                  ))}
                </select>
              )}
              <select
                aria-label="Sıralama"
                className="h-8 rounded-md border bg-background px-2"
                value={filters.sort}
                onChange={(event) => set("sort", event.target.value as Filters["sort"])}
              >
                <option value="relevance">İlgi sırası</option>
                <option value="newest">En yeni önce</option>
              </select>
            </div>
          )}
          {hiddenByFilter > 0 && (
            <p className="text-xs text-muted-foreground" role="status">
              Süzgeçler {hiddenByFilter} sonucu gizliyor.{" "}
              <button
                type="button"
                className="underline"
                onClick={() => setFilters(DEFAULT_FILTERS)}
              >
                Süzgeçleri temizle
              </button>
            </p>
          )}

          <div className="space-y-3">
            {shown.map((hit) => (
              <Card key={hit.id} hit={hit} query={submitted} />
            ))}
          </div>
          {hits.length > 0 && !shown.length && (
            <p className="text-sm text-muted-foreground">Süzgeçlere uyan sonuç yok.</p>
          )}

          {hasMore && (
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => void run(submitted, hits.length, mode)}
            >
              {busy ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
              Daha fazla göster
            </Button>
          )}
        </div>
      )}
    </section>
  );
}

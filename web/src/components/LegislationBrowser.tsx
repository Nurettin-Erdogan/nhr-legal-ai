import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Copy,
  ExternalLink,
  Loader2,
  MessageSquare,
  Search,
  ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";
import { Link } from "@/lib/router-compat";
import { useSearchParam } from "@/lib/router-hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  loadSourceDetail,
  isHttpUrl,
  highlightSegments,
  type SourceDetail,
} from "@/lib/decision-search";
import {
  LegislationError,
  TYPE_FILTERS,
  TYPE_LABELS,
  articleLabel,
  citationFor,
  dateTr,
  filterArticles,
  findArticle,
  loadLaw,
  searchLaws,
  type ArticleEntry,
  type LawDetail,
  type LawPage,
  type LawSummary,
  type LegislationType,
} from "@/lib/legislation";

const EXAMPLES = [
  "İş Kanunu",
  "Türk Borçlar Kanunu",
  "4857 m. 18",
  "Hukuk Muhakemeleri",
  "Anayasa",
];

function ArticleReader({
  law,
  article,
  onPrevious,
  onNext,
  query,
}: {
  law: LawDetail;
  article: ArticleEntry;
  onPrevious?: () => void;
  onNext?: () => void;
  query: string;
}) {
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    setDetail(null);
    setError("");
    loadSourceDetail(article.id, abort.signal)
      .then((value) => {
        if (!abort.signal.aborted) setDetail(value);
      })
      .catch((e) => {
        if (!abort.signal.aborted)
          setError(e instanceof Error ? e.message : "Madde metni alınamadı.");
      });
    return () => abort.abort();
  }, [article.id]);

  const citation = citationFor(law, article);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(citation);
      toast.success("Atıf kopyalandı");
    } catch {
      toast.error("Panoya kopyalanamadı");
    }
  };

  return (
    <article className="space-y-3 rounded-xl border bg-card p-4" data-testid="article-reader">
      <div className="flex flex-wrap items-start gap-2">
        <h3 className="min-w-0 flex-1 font-semibold leading-snug">{citation}</h3>
        <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 dark:text-emerald-400">
          <ShieldCheck className="h-3.5 w-3.5" /> Resmî kaynaklarla doğrulandı
        </span>
      </div>
      {article.articleTitle && (
        <p className="text-sm text-muted-foreground">{article.articleTitle}</p>
      )}
      {article.versionDate && (
        <p className="text-xs text-muted-foreground">
          Güncel sürüm tarihi: {dateTr(article.versionDate)}
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {!detail && !error && (
        <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Madde metni yükleniyor…
        </p>
      )}
      {detail && (
        <div
          className="max-h-[28rem] overflow-y-auto text-sm leading-relaxed"
          data-testid="article-text"
        >
          {detail.chunks.length ? (
            detail.chunks.map((chunk, index) => (
              <p key={index} className="mb-3 whitespace-pre-wrap last:mb-0">
                {highlightSegments(chunk, query).map((segment, i) =>
                  segment.match ? (
                    <mark key={i} className="rounded bg-amber-200/70 px-0.5 dark:bg-amber-500/30">
                      {segment.text}
                    </mark>
                  ) : (
                    <span key={i}>{segment.text}</span>
                  ),
                )}
              </p>
            ))
          ) : (
            <p className="text-muted-foreground">Bu madde için metin yok.</p>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-2 pt-1">
        <Button size="sm" variant="outline" onClick={onPrevious} disabled={!onPrevious}>
          <ChevronLeft className="mr-1 h-3.5 w-3.5" /> Önceki madde
        </Button>
        <Button size="sm" variant="outline" onClick={onNext} disabled={!onNext}>
          Sonraki madde <ChevronRight className="ml-1 h-3.5 w-3.5" />
        </Button>
        <Button size="sm" variant="ghost" onClick={() => void copy()}>
          <Copy className="mr-1.5 h-3.5 w-3.5" /> Atıf kopyala
        </Button>
        {detail && isHttpUrl(detail.sourceUrl) && (
          <Button size="sm" variant="ghost" asChild>
            <a href={detail.sourceUrl} target="_blank" rel="noreferrer">
              <ExternalLink className="mr-1.5 h-3.5 w-3.5" /> Resmî kaynak
            </a>
          </Button>
        )}
        <Button size="sm" variant="ghost" asChild>
          <Link to="/dashboard/ai">
            <MessageSquare className="mr-1.5 h-3.5 w-3.5" /> Asistana sor
          </Link>
        </Button>
      </div>
    </article>
  );
}

/**
 * Mevzuat gezgini: kanun/yönetmelik ara (ad, numara ya da "4857 m. 18"), madde dizinine göz at, maddeyi oku, atıf kopyala.
 * Yalnız resmî doğrulanmış güncel mevzuat listelenir; doğrulanmamış mevzuat burada görünmez.
 */
export function LegislationBrowser() {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<LegislationType | "">("");
  const [page, setPage] = useState<LawPage | null>(null);
  const [laws, setLaws] = useState<LawSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [law, setLaw] = useState<LawDetail | null>(null);
  const [lawBusy, setLawBusy] = useState(false);
  const [lawError, setLawError] = useState("");
  const [articleFilter, setArticleFilter] = useState("");
  const [articleId, setArticleId] = useState("");
  const searchAbort = useRef<AbortController | null>(null);
  const lawAbort = useRef<AbortController | null>(null);

  const search = useCallback(
    async (text: string, selectedKind: LegislationType | "", offset = 0) => {
      searchAbort.current?.abort();
      const abort = new AbortController();
      searchAbort.current = abort;
      setBusy(true);
      setError("");
      try {
        const next = await searchLaws(text, { kind: selectedKind, offset, signal: abort.signal });
        if (abort.signal.aborted) return undefined;
        setPage(next);
        setLaws((previous) => (offset === 0 ? next.results : [...previous, ...next.results]));
        return next;
      } catch (e) {
        if (!abort.signal.aborted)
          setError(e instanceof Error ? e.message : "Arama tamamlanamadı.");
        return undefined;
      } finally {
        if (!abort.signal.aborted) setBusy(false);
      }
    },
    [],
  );

  const openLaw = useCallback(async (lawNo: string, articleNo?: string) => {
    lawAbort.current?.abort();
    const abort = new AbortController();
    lawAbort.current = abort;
    setLawBusy(true);
    setLawError("");
    setArticleFilter("");
    setArticleId("");
    try {
      const detail = await loadLaw(lawNo, abort.signal);
      if (abort.signal.aborted) return;
      setLaw(detail);
      const target = articleNo ? findArticle(detail.articles, articleNo) : undefined;
      if (target) setArticleId(target.id);
      else if (articleNo)
        setLawError(`Madde ${articleNo} bu mevzuatın doğrulanmış maddeleri arasında bulunamadı.`);
    } catch (e) {
      if (!abort.signal.aborted) {
        setLaw(null);
        setLawError(
          e instanceof LegislationError || e instanceof Error ? e.message : "Mevzuat açılamadı.",
        );
      }
    } finally {
      if (!abort.signal.aborted) setLawBusy(false);
    }
  }, []);

  useEffect(() => {
    void search("", "");
    return () => {
      searchAbort.current?.abort();
      lawAbort.current?.abort();
    };
  }, [search]);

  const submit = async (text = query, selectedKind = kind) => {
    setQuery(text);
    const result = await search(text, selectedKind);
    if (result?.articleReference && result.results[0]?.lawNo === result.articleReference.lawNo) {
      void openLaw(result.articleReference.lawNo, result.articleReference.articleNo);
    }
  };

  // Üst çubuktaki genel aramadan gelen terim ("?q=…") sayfa açılırken ve terim değiştikçe aranır.
  const urlQuery = useSearchParam("q");
  useEffect(() => {
    if (urlQuery.trim()) void submit(urlQuery.trim(), "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlQuery]);

  const visible = law ? filterArticles(law.articles, articleFilter) : [];
  const index = law ? law.articles.findIndex((article) => article.id === articleId) : -1;
  const current = law && index >= 0 ? law.articles[index] : undefined;
  const hasMore = !!page && laws.length < page.total;

  return (
    <div className="grid gap-4 lg:grid-cols-[22rem_1fr]" data-testid="legislation-browser">
      <section className="space-y-3" aria-label="Mevzuat listesi">
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Kanun adı, numarası ya da “4857 m. 18”"
            aria-label="Mevzuat ara"
            maxLength={200}
          />
          <Button type="submit" disabled={busy} aria-label="Ara">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          </Button>
        </form>
        <div className="flex flex-wrap gap-1.5 text-xs" role="group" aria-label="Mevzuat türü">
          {(["", ...TYPE_FILTERS] as const).map((value) => (
            <button
              key={value || "all"}
              type="button"
              aria-pressed={kind === value}
              onClick={() => {
                setKind(value);
                void submit(query, value);
              }}
              className={`rounded-full border px-2.5 py-1 ${kind === value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent"}`}
            >
              {value ? TYPE_LABELS[value] : "Tümü"}
            </button>
          ))}
        </div>
        {!query && (
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                className="rounded-full border px-2.5 py-1 text-xs text-muted-foreground hover:bg-accent"
                onClick={() => void submit(example)}
              >
                {example}
              </button>
            ))}
          </div>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {page && (
          <p className="text-xs text-muted-foreground" role="status" data-testid="law-total">
            {page.total.toLocaleString("tr-TR")} mevzuat · yalnız resmî doğrulanmış güncel metinler
          </p>
        )}
        <ul className="max-h-[32rem] space-y-1.5 overflow-y-auto" data-testid="law-list">
          {laws.map((item) => (
            <li key={item.lawNo}>
              <button
                type="button"
                onClick={() => void openLaw(item.lawNo)}
                data-selected={law?.lawNo === item.lawNo}
                className={`w-full rounded-lg border p-2.5 text-left text-sm hover:bg-accent ${law?.lawNo === item.lawNo ? "border-primary bg-accent" : ""}`}
              >
                <span className="block font-medium leading-snug">{item.lawName}</span>
                <span className="text-xs text-muted-foreground">
                  {TYPE_LABELS[item.legislationType]} · No {item.lawNo} ·{" "}
                  {item.articles.toLocaleString("tr-TR")} madde
                </span>
              </button>
            </li>
          ))}
          {page && laws.length === 0 && !busy && (
            <li className="text-sm text-muted-foreground">
              Eşleşen doğrulanmış mevzuat yok. Başka bir ad ya da numara deneyin.
            </li>
          )}
        </ul>
        {hasMore && (
          <Button
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => void search(query, kind, laws.length)}
          >
            Daha fazla göster
          </Button>
        )}
      </section>

      <section className="space-y-3" aria-label="Mevzuat içeriği">
        {!law && !lawBusy && !lawError && (
          <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
            Soldan bir mevzuat seçin ya da “4857 m. 18” gibi bir madde atfı yazın.
          </p>
        )}
        {lawBusy && (
          <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Mevzuat açılıyor…
          </p>
        )}
        {lawError && (
          <p
            role="alert"
            className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm"
          >
            {lawError}
          </p>
        )}
        {law && (
          <>
            <header className="space-y-1">
              <h2 className="text-lg font-semibold leading-snug" data-testid="law-title">
                {law.lawName}
              </h2>
              <p className="text-xs text-muted-foreground">
                {TYPE_LABELS[law.legislationType]} · No {law.lawNo}
                {law.gazetteDate ? ` · Resmî Gazete ${dateTr(law.gazetteDate)}` : ""} ·{" "}
                {law.articles.length.toLocaleString("tr-TR")} doğrulanmış madde
              </p>
              {law.truncated && (
                <p className="text-xs text-amber-700 dark:text-amber-400">
                  Madde sayısı çok fazla: dizin ilk maddelerle sınırlandı.
                </p>
              )}
            </header>
            {current && (
              <ArticleReader
                law={law}
                article={current}
                query={articleFilter}
                onPrevious={index > 0 ? () => setArticleId(law.articles[index - 1].id) : undefined}
                onNext={
                  index < law.articles.length - 1
                    ? () => setArticleId(law.articles[index + 1].id)
                    : undefined
                }
              />
            )}
            <div className="space-y-2">
              <Input
                value={articleFilter}
                onChange={(event) => setArticleFilter(event.target.value)}
                placeholder="Madde ara: numara (18) ya da başlıkta geçen sözcük"
                aria-label="Madde ara"
              />
              <p className="text-xs text-muted-foreground" data-testid="article-count">
                {visible.length.toLocaleString("tr-TR")} madde gösteriliyor
              </p>
              <ul
                className="max-h-80 divide-y overflow-y-auto rounded-lg border"
                data-testid="article-list"
              >
                {visible.slice(0, 400).map((article) => (
                  <li key={article.id}>
                    <button
                      type="button"
                      onClick={() => setArticleId(article.id)}
                      data-selected={article.id === articleId}
                      className={`w-full px-3 py-2 text-left text-sm hover:bg-accent ${article.id === articleId ? "bg-accent font-medium" : ""}`}
                    >
                      {articleLabel(article)}
                    </button>
                  </li>
                ))}
                {visible.length > 400 && (
                  <li className="px-3 py-2 text-xs text-muted-foreground">
                    İlk 400 madde gösteriliyor; aramayı daraltın.
                  </li>
                )}
                {visible.length === 0 && (
                  <li className="px-3 py-2 text-sm text-muted-foreground">
                    Bu ifadeyle madde bulunamadı.
                  </li>
                )}
              </ul>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

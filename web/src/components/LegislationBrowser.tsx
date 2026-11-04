import { useCallback, useEffect, useRef, useState } from "react";
import {
  BookOpen,
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
import { readableParagraphs } from "@/lib/source-reader";
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

const SEARCH_DELAY_MS = 300;

/** Türe göre rozet rengi: listede bir bakışta kanun mu yönetmelik mi anlaşılır. */
const TYPE_STYLES: Record<LegislationType, string> = {
  law: "bg-blue-500/10 text-blue-700 dark:text-blue-300",
  decree: "bg-violet-500/10 text-violet-700 dark:text-violet-300",
  regulation: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  communique: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
  constitution: "bg-rose-500/10 text-rose-700 dark:text-rose-300",
  other: "bg-slate-500/10 text-slate-700 dark:text-slate-300",
};

function TypeBadge({ type }: { type: LegislationType }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${TYPE_STYLES[type] ?? TYPE_STYLES.other}`}
    >
      {TYPE_LABELS[type]}
    </span>
  );
}

function Highlighted({ text, query }: { text: string; query: string }) {
  return (
    <>
      {highlightSegments(text, query).map((segment, i) =>
        segment.match ? (
          <mark key={i} className="rounded bg-amber-200/70 px-0.5 dark:bg-amber-500/30">
            {segment.text}
          </mark>
        ) : (
          <span key={i}>{segment.text}</span>
        ),
      )}
    </>
  );
}

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
    <article className="min-w-0 rounded-2xl border bg-card shadow-sm" data-testid="article-reader">
      <div className="space-y-2 border-b px-5 py-4 sm:px-7">
        <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
          <h3 className="min-w-0 flex-1 text-xl font-semibold leading-snug">{citation}</h3>
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
      </div>
      <div className="px-5 py-5 sm:px-7 sm:py-6">
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
            className="max-w-[68ch] text-[15px] leading-7 sm:text-base sm:leading-8"
            data-testid="article-text"
          >
            {detail.rawText ? (
              // Resmî metin sabit genişlikte satır kırılmış gelir; satırlar birleştirilir, fıkra/bent başlangıçları paragraf olur.
              readableParagraphs(detail.rawText).map((paragraph, index) => (
                <p
                  key={index}
                  className={`mb-4 last:mb-0 ${paragraph.heading ? "pt-1 font-semibold" : ""}`}
                >
                  <Highlighted text={paragraph.text} query={query} />
                </p>
              ))
            ) : detail.chunks.length ? (
              detail.chunks.map((chunk, index) => (
                <p key={index} className="mb-4 whitespace-pre-wrap last:mb-0">
                  <Highlighted text={chunk} query={query} />
                </p>
              ))
            ) : (
              <p className="text-muted-foreground">Bu madde için metin yok.</p>
            )}
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t bg-secondary/30 px-5 py-3 sm:px-7">
        <Button size="sm" variant="outline" onClick={onPrevious} disabled={!onPrevious}>
          <ChevronLeft className="mr-1 h-3.5 w-3.5" /> Önceki
        </Button>
        <Button size="sm" variant="outline" onClick={onNext} disabled={!onNext}>
          Sonraki <ChevronRight className="ml-1 h-3.5 w-3.5" />
        </Button>
        <span className="hidden text-xs text-muted-foreground md:inline">
          ← → tuşlarıyla da gezebilirsin
        </span>
        <div className="ml-auto flex flex-wrap gap-1">
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
      </div>
    </article>
  );
}

/**
 * Mevzuat gezgini: kanun/yönetmelik ara (ad, numara ya da "4857 m. 18"), madde dizinine göz at, maddeyi oku, atıf kopyala.
 * Yalnız resmî doğrulanmış güncel mevzuat listelenir; doğrulanmamış mevzuat burada görünmez.
 * Arama yazarken kendiliğinden yapılır; bir mevzuat açılınca ilk madde (ya da atıf yapılan madde) hemen okunur.
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
  const lastSearch = useRef<string | null>(null);
  const articleListRef = useRef<HTMLUListElement>(null);

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
      // Madde belirtilmediyse okuyucu boş kalmasın: ilk madde açılır.
      else if (detail.articles[0]) setArticleId(detail.articles[0].id);
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

  /** Aynı (metin, tür) ikilisi art arda aranmaz; "4857 m. 18" gibi atıf yazılınca o madde doğrudan açılır. */
  const runSearch = useCallback(
    async (text: string, selectedKind: LegislationType | "", force = false) => {
      const key = `${selectedKind}|${text.trim()}`;
      if (!force && lastSearch.current === key) return;
      lastSearch.current = key;
      const result = await search(text.trim(), selectedKind);
      if (result?.articleReference && result.results[0]?.lawNo === result.articleReference.lawNo) {
        void openLaw(result.articleReference.lawNo, result.articleReference.articleNo);
      }
    },
    [search, openLaw],
  );

  // Yazarken kısa bir beklemeden sonra aranır; türü değiştirince hemen.
  useEffect(() => {
    const timer = window.setTimeout(() => void runSearch(query, kind), SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [query, kind, runSearch]);

  useEffect(
    () => () => {
      searchAbort.current?.abort();
      lawAbort.current?.abort();
    },
    [],
  );

  // Üst çubuktaki genel aramadan gelen terim ("?q=…") sayfa açılırken ve terim değiştikçe aranır.
  const urlQuery = useSearchParam("q");
  useEffect(() => {
    if (urlQuery.trim()) {
      setKind("");
      setQuery(urlQuery.trim());
    }
  }, [urlQuery]);

  const visible = law ? filterArticles(law.articles, articleFilter) : [];
  const index = law ? law.articles.findIndex((article) => article.id === articleId) : -1;
  const current = law && index >= 0 ? law.articles[index] : undefined;
  const hasMore = !!page && laws.length < page.total;

  const previousId = law && index > 0 ? law.articles[index - 1].id : undefined;
  const nextId =
    law && index >= 0 && index < law.articles.length - 1 ? law.articles[index + 1].id : undefined;

  // Okurken ← → ile madde değiştirilir (bir yazı alanındayken değil).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (event.key === "ArrowLeft" && previousId) setArticleId(previousId);
      else if (event.key === "ArrowRight" && nextId) setArticleId(nextId);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [previousId, nextId]);

  // Seçili madde dizinde her zaman görünür kalsın.
  useEffect(() => {
    const list = articleListRef.current;
    const selected = list?.querySelector<HTMLElement>('[data-selected="true"]');
    if (!list || !selected) return;
    const top = selected.offsetTop;
    if (top < list.scrollTop || top + selected.offsetHeight > list.scrollTop + list.clientHeight)
      list.scrollTop = Math.max(0, top - list.clientHeight / 2);
  }, [articleId, visible.length]);

  return (
    <div
      className="grid items-start gap-6 lg:grid-cols-[21rem_1fr]"
      data-testid="legislation-browser"
    >
      <section className="space-y-3 lg:sticky lg:top-4" aria-label="Mevzuat listesi">
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void runSearch(query, kind, true);
          }}
        >
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Kanun adı, no ya da 4857 m. 18"
              aria-label="Mevzuat ara"
              maxLength={200}
              className="pl-9"
            />
          </div>
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
              onClick={() => setKind(value)}
              className={`rounded-full border px-2.5 py-1 transition-colors ${kind === value ? "border-primary bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent"}`}
            >
              {value ? TYPE_LABELS[value] : "Tümü"}
            </button>
          ))}
        </div>
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
        <ul
          className="max-h-[calc(100vh-17rem)] min-h-40 space-y-1.5 overflow-y-auto pr-1"
          data-testid="law-list"
        >
          {laws.map((item) => (
            <li key={item.lawNo}>
              <button
                type="button"
                onClick={() => void openLaw(item.lawNo)}
                data-selected={law?.lawNo === item.lawNo}
                className={`w-full rounded-xl border p-3 text-left text-sm transition-colors hover:bg-accent ${law?.lawNo === item.lawNo ? "border-primary bg-accent shadow-sm" : ""}`}
              >
                <span className="block line-clamp-3 font-medium leading-snug">
                  <Highlighted text={item.lawName} query={query} />
                </span>
                <span className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                  <TypeBadge type={item.legislationType} />
                  <span>No {item.lawNo}</span>
                  <span>· {item.articles.toLocaleString("tr-TR")} madde</span>
                </span>
              </button>
            </li>
          ))}
          {page && laws.length === 0 && !busy && (
            <li className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">
              Eşleşen doğrulanmış mevzuat yok. Başka bir ad ya da numara deneyin.
            </li>
          )}
          {hasMore && (
            <li>
              <Button
                variant="outline"
                size="sm"
                className="w-full"
                disabled={busy}
                onClick={() => void search(query.trim(), kind, laws.length)}
              >
                Daha fazla göster
              </Button>
            </li>
          )}
        </ul>
      </section>

      <section className="min-w-0 space-y-4" aria-label="Mevzuat içeriği">
        {!law && !lawBusy && !lawError && (
          <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed px-6 py-14 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
              <BookOpen className="h-6 w-6" />
            </span>
            <p className="text-base font-semibold">Mevzuatı oku, maddeyi doğrudan aç</p>
            <p className="max-w-md text-sm text-muted-foreground">
              Listeden bir mevzuat seç ya da “4857 m. 18” gibi bir madde atfı yaz; madde hemen açılır.
              Metinler yalnız resmî kaynaklarla doğrulanmış güncel sürümlerdir.
            </p>
            <div className="flex flex-wrap justify-center gap-1.5">
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  className="rounded-full border px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent"
                  onClick={() => {
                    setKind("");
                    setQuery(example);
                  }}
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
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
            <header className="space-y-2 rounded-2xl border bg-card px-5 py-4 shadow-sm sm:px-7">
              <h2 className="text-xl font-semibold leading-snug" data-testid="law-title">
                {law.lawName}
              </h2>
              <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                <TypeBadge type={law.legislationType} />
                <span>No {law.lawNo}</span>
                {law.gazetteDate && <span>· Resmî Gazete {dateTr(law.gazetteDate)}</span>}
                <span>· {law.articles.length.toLocaleString("tr-TR")} doğrulanmış madde</span>
              </p>
              {law.truncated && (
                <p className="text-xs text-amber-700 dark:text-amber-400">
                  Madde sayısı çok fazla: dizin ilk maddelerle sınırlandı.
                </p>
              )}
            </header>
            <div className="grid items-start gap-4 xl:grid-cols-[17rem_1fr]">
              <div className="space-y-2 xl:sticky xl:top-4 xl:order-first">
                <Input
                  value={articleFilter}
                  onChange={(event) => setArticleFilter(event.target.value)}
                  placeholder="Madde ara: numara (18) ya da başlık"
                  aria-label="Madde ara"
                />
                <p className="text-xs text-muted-foreground" data-testid="article-count">
                  {visible.length.toLocaleString("tr-TR")} madde gösteriliyor
                </p>
                <ul
                  ref={articleListRef}
                  className="relative max-h-72 divide-y overflow-y-auto rounded-xl border bg-card xl:max-h-[calc(100vh-18rem)]"
                  data-testid="article-list"
                >
                  {visible.slice(0, 400).map((article) => (
                    <li key={article.id}>
                      <button
                        type="button"
                        onClick={() => setArticleId(article.id)}
                        data-selected={article.id === articleId}
                        className={`w-full px-3 py-2 text-left text-sm transition-colors hover:bg-accent ${article.id === articleId ? "bg-accent font-medium text-primary" : ""}`}
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
              {current ? (
                <ArticleReader
                  law={law}
                  article={current}
                  query={articleFilter}
                  onPrevious={previousId ? () => setArticleId(previousId) : undefined}
                  onNext={nextId ? () => setArticleId(nextId) : undefined}
                />
              ) : (
                <p className="rounded-2xl border border-dashed p-8 text-center text-sm text-muted-foreground">
                  Dizinden bir madde seç.
                </p>
              )}
            </div>
          </>
        )}
      </section>
    </div>
  );
}

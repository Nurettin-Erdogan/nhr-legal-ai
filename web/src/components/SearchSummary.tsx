import { verificationNotice, type SearchSummaryData } from "../lib/search-summary";

export function SearchSummary({
  summary,
  citedCount,
  compact = false,
}: {
  summary: SearchSummaryData;
  citedCount?: number;
  compact?: boolean;
}) {
  const notice = verificationNotice(summary);
  const counts = [
    ["Aday belge", summary.candidate_documents],
    ["Kaynak kontrolünü geçen", summary.verified_documents],
    ["Modele verilen", summary.selected_documents],
    ...(citedCount === undefined ? [] : [["Atıf yapılan belge", citedCount]]),
  ] as Array<[string, number]>;
  return (
    <section
      aria-label="Bu sorunun kaynak taraması"
      className="mt-3 border-t border-border pt-3 text-xs space-y-2"
    >
      <p className="font-medium">Bu sorunun kaynak taraması</p>
      <dl
        className={
          compact ? "flex flex-wrap gap-x-4 gap-y-1" : "grid grid-cols-2 sm:grid-cols-4 gap-2"
        }
      >
        {counts.map(([label, count]) => (
          <div
            key={label}
            className={compact ? "flex gap-1" : "rounded-lg border border-border p-2"}
          >
            <dt className="text-muted-foreground">{label}</dt>
            <dd
              className={
                compact ? "font-medium tabular-nums" : "mt-1 text-base font-semibold tabular-nums"
              }
            >
              {count.toLocaleString("tr-TR")}
            </dd>
          </div>
        ))}
      </dl>
      <p className="text-muted-foreground">
        {compact
          ? "Sayılar yalnız bu araştırmaya aittir; tüm korpusu kapsamaz."
          : "Bunlar bu istekte değerlendirilen adaylardır; korpustaki bütün ilgili belgelerin toplamı değildir. Atıf sayısı, bulunan belge sayısı değildir."}
      </p>
      {summary.retrieval_strategy === "verified_statute" && (
        <p className="text-muted-foreground">
          {compact
            ? "Cevap doğrulanmış madde üzerinden hazırlandı; geniş korpus taraması bu sayılara dahil değildir."
            : "Cevap ilgili güncel ve doğrulanmış madde üzerinden hazırlandı. Geniş korpus taraması bu sayılara dahil değildir; ayrı araştırmanın durumu sorunun altındaki kaynak panelinde gösterilir."}
        </p>
      )}
      {summary.retrieval_partial &&
        (summary.retrieval_limit === "sampled" ? (
          <p className="text-muted-foreground">
            Çok sayıda eşleşen karar olduğundan karar araması örneklemeyle yapıldı; ilgili bazı
            kararlar listede olmayabilir.
          </p>
        ) : (
          <p className="text-amber-700 dark:text-amber-400">
            Aramanın bir bölümü zaman aşımına uğradı; araştırma eksik olabilir.
          </p>
        ))}
      {notice && <p className="text-amber-700 dark:text-amber-400">{notice}</p>}
    </section>
  );
}

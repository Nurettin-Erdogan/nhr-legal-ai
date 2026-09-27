import { verificationNotice, type SearchSummaryData } from "../lib/search-summary";

export function SearchSummary({ summary, citedCount }: {
  summary: SearchSummaryData;
  citedCount?: number;
}) {
  const notice = verificationNotice(summary);
  const counts = [
    ["Aday belge", summary.candidate_documents],
    ["Kaynak kontrolünü geçen", summary.verified_documents],
    ["Modele verilen", summary.selected_documents],
    ...(citedCount === undefined ? [] : [["Atıf yapılan belge", citedCount]]),
  ] as Array<[string, number]>;
  return (
    <section aria-label="Bu sorunun kaynak taraması" className="mt-3 border-t border-border pt-3 text-xs space-y-2">
      <p className="font-medium">Bu sorunun kaynak taraması</p>
      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {counts.map(([label, count]) => <div key={label} className="rounded-lg border border-border p-2">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="mt-1 text-base font-semibold tabular-nums">{count.toLocaleString("tr-TR")}</dd>
        </div>)}
      </dl>
      <p className="text-muted-foreground">Bunlar bu istekte değerlendirilen adaylardır; korpustaki bütün ilgili belgelerin toplamı değildir. Atıf sayısı, bulunan belge sayısı değildir.</p>
      {summary.retrieval_partial && <p className="text-amber-700 dark:text-amber-400">Aramanın bir bölümü zaman aşımına uğradı; araştırma eksik olabilir.</p>}
      {notice && <p className="text-amber-700 dark:text-amber-400">{notice}</p>}
    </section>
  );
}

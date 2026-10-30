import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { Link } from "@/lib/router-compat";
import type { DetailTab, DetailTable, DosyaDetail } from "@/lib/uyap-bridge";
import { detailWarnings, filterRows, orderedTabs, tabTitle } from "@/lib/uyap-detail-view";
import { loadCaseDetail, type StoredCaseDetail } from "@/lib/uyap-sync-api";
import { summarizeDetail } from "@/lib/uyap-case-summary";

/** Dosya durum özeti: yalnız UYAP'ın yazdığı metin ve kayıt sayıları; aşama tahmini ya da yorum yok. */
const StatusSummary = ({ detail }: { detail: DosyaDetail }) => {
  const summary = summarizeDetail(detail);
  if (!summary.facts.length && !summary.parties && !summary.safahat) return null;
  return (
    <section
      className="rounded-lg border bg-secondary/30 p-4 space-y-3"
      aria-label="Dosya durumu özeti"
      data-testid="uyap-status-summary"
    >
      <h3 className="font-semibold">Dosya durumu özeti</h3>
      <dl className="grid sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2 text-sm">
        {summary.facts.map((fact) => (
          <div key={fact.label}>
            <dt className="text-xs text-muted-foreground">{fact.label}</dt>
            <dd className="break-words">{fact.value}</dd>
          </div>
        ))}
        {summary.parties && (
          <div>
            <dt className="text-xs text-muted-foreground">Taraflar</dt>
            <dd>{summary.parties}</dd>
          </div>
        )}
        {summary.safahat && (
          <div>
            <dt className="text-xs text-muted-foreground">Safahat</dt>
            <dd>
              {summary.safahat.count} kayıt
              {summary.safahat.first ? ` · ilk ${summary.safahat.first}` : ""}
              {summary.safahat.last ? ` · son ${summary.safahat.last}` : ""}
            </dd>
          </div>
        )}
      </dl>
      {summary.safahat && summary.safahat.recent.length > 0 && (
        <div>
          <p className="text-xs text-muted-foreground mb-1">Son safahat kayıtları</p>
          <ul className="space-y-0.5 text-sm">
            {summary.safahat.recent.map((item, index) => (
              <li key={index}>
                <span className="text-muted-foreground">{item.date}</span> {item.text}
              </li>
            ))}
          </ul>
        </div>
      )}
      {summary.actionTypes.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Safahatta en sık:{" "}
          {summary.actionTypes.map((item) => `${item.label} (${item.count})`).join(", ")}
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        Bu özet UYAP'ın yazdığı metinlerden ve kayıt sayılarından oluşur; aşama tahmini ya da hukuki
        yorum içermez.
      </p>
    </section>
  );
};

const dateTime = (value: string): string => {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? ""
    : parsed.toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" });
};

const Pairs = ({ tab }: { tab: DetailTab }) => (
  <dl className="grid sm:grid-cols-2 gap-x-6 gap-y-3" data-testid={`uyap-detail-pairs-${tab.key}`}>
    {tab.pairs.map((pair) => (
      <div key={pair.label}>
        <dt className="text-xs text-muted-foreground">{pair.label}</dt>
        <dd className="text-sm mt-0.5 break-words">{pair.value || "—"}</dd>
      </div>
    ))}
  </dl>
);

const Table = ({
  tab,
  table,
  searchable,
}: {
  tab: DetailTab;
  table: DetailTable;
  searchable: boolean;
}) => {
  const [query, setQuery] = useState("");
  const rows = useMemo(() => filterRows(table.rows, query), [table.rows, query]);
  if (!table.headers.length && !table.rows.length) return null;
  return (
    <div className="space-y-2" data-testid={`uyap-detail-table-${tab.key}`}>
      {(table.title || searchable) && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          {table.title && <h4 className="text-sm font-medium">{table.title}</h4>}
          {searchable && table.rows.length > 8 && (
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Bu tabloda ara"
              aria-label={`${tabTitle(tab)} içinde ara`}
              className="h-8 w-56 rounded-md border border-input bg-background px-2 text-sm"
            />
          )}
        </div>
      )}
      {table.rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">UYAP bu tabloda kayıt göstermiyor.</p>
      ) : (
        <div className="max-h-[28rem] overflow-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-muted text-left text-xs text-muted-foreground">
              <tr>
                {table.headers.map((header, index) => (
                  <th key={`${header}-${index}`} className="px-3 py-2 font-medium">
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map((row, index) => (
                <tr key={index} className="align-top">
                  {row.map((cell, column) => (
                    <td key={column} className="px-3 py-2 break-words">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        {query
          ? `${rows.length} / ${table.rows.length} kayıt gösteriliyor`
          : `${table.rows.length} kayıt`}
        {table.declared !== null && table.declared !== table.rows.length
          ? ` (UYAP ${table.declared} yazıyor)`
          : ""}
      </p>
    </div>
  );
};

/** Saklanan UYAP dosya bilgilerinin gösterimi. Değerler UYAP'ın yazdığı metindir; yorum ya da hesap içermez. */
export const UyapDetailView = ({
  detail,
  fetchedAt,
  complete,
}: {
  detail: DosyaDetail;
  fetchedAt: string;
  complete: boolean;
}) => {
  const warnings = detailWarnings(detail);
  return (
    <div className="space-y-6" data-testid="uyap-detail">
      <div
        role={complete ? "status" : "alert"}
        className={`flex items-start gap-2 rounded-lg border p-3 text-sm ${complete ? "border-emerald-500/30 bg-emerald-500/5" : "border-amber-500/30 bg-amber-500/5"}`}
      >
        {complete ? (
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
        ) : (
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
        )}
        <div>
          <p className="font-medium">
            {complete
              ? "UYAP'taki bilgilerin tamamı alındı"
              : "UYAP bilgileri eksik alınmış olabilir"}
            {fetchedAt ? ` · ${dateTime(fetchedAt)}` : ""}
          </p>
          {warnings.length > 0 && (
            <ul className="mt-1 list-disc pl-4 text-xs">
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <StatusSummary detail={detail} />
      {orderedTabs(detail).map((tab) => (
        <section key={tab.key} className="space-y-3" aria-label={tabTitle(tab)}>
          <h3 className="font-semibold">{tabTitle(tab)}</h3>
          {tab.pairs.length > 0 && <Pairs tab={tab} />}
          {tab.tables.map((table, index) => (
            <Table
              key={`${table.title}-${index}`}
              tab={tab}
              table={table}
              searchable={tab.key === "safahat" || tab.key === "taraflar"}
            />
          ))}
          {tab.pairs.length === 0 &&
            tab.tables.every((table) => !table.headers.length && !table.rows.length) && (
              <p className="text-sm text-muted-foreground">UYAP bu bölümde bilgi göstermiyor.</p>
            )}
        </section>
      ))}
      <p className="text-xs text-muted-foreground">
        Bu bilgiler UYAP'ın yazdığı metindir; JurisAI yorum yapmaz, toplama ya da hukuki sonuç
        üretmez. Güncel hâli için UYAP Dosyalarım sayfasından yeniden aktarın.
      </p>
    </div>
  );
};

/** Davanın UYAP dosya bilgileri (taraflar, safahat, dosya hesabı, tahsilat/reddiyat). Kayıt yoksa nasıl çekileceğini söyler. */
export const UyapCaseDetail = ({ caseId }: { caseId: string }) => {
  const [stored, setStored] = useState<StoredCaseDetail | null | undefined>(undefined);
  useEffect(() => {
    const controller = new AbortController();
    setStored(undefined);
    void loadCaseDetail(caseId, controller.signal).then(
      (value) => !controller.signal.aborted && setStored(value),
    );
    return () => controller.abort();
  }, [caseId]);
  if (stored === undefined)
    return (
      <p role="status" className="text-sm text-muted-foreground">
        UYAP bilgileri yükleniyor…
      </p>
    );
  if (stored === null)
    return (
      <p className="text-sm text-muted-foreground" data-testid="uyap-detail-empty">
        Bu dava için UYAP'tan dosya bilgisi (taraflar, safahat, dosya hesabı) çekilmemiş. UYAP'a
        giriş yapıp{" "}
        <Link to="/dashboard/uyap" className="underline">
          UYAP Dosyalarım
        </Link>{" "}
        sayfasında "Tüm dosyaları aktar"a bas.
      </p>
    );
  return (
    <UyapDetailView
      detail={stored.detail}
      fetchedAt={stored.fetchedAt}
      complete={stored.complete}
    />
  );
};

import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, RefreshCw, Search } from "lucide-react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Link, useNavigate } from "@/lib/router-compat";
import { cn } from "@/lib/utils";
import {
  KIND_LABELS,
  closedOffice,
  countBadges,
  dateTr,
  filterFiles,
  formatLira,
  loadExecution,
  receiptLine,
  receiptNote,
  shortStatus,
  verificationLabel,
  type ExecutionData,
  type KindFilter,
} from "@/lib/execution";
import { accountLine } from "@/lib/uyap-detail-view";

const KIND_FILTERS: Array<{ key: KindFilter; label: string }> = [
  { key: "all", label: "Tümü" },
  { key: "takip", label: "İcra daireleri" },
  { key: "mahkeme", label: "İcra mahkemeleri" },
];

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-card-elite">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1.5 font-serif text-2xl font-semibold">{value}</div>
      {note && <div className="mt-1 text-xs text-muted-foreground">{note}</div>}
    </div>
  );
}

const ExecutionPage = () => {
  const navigate = useNavigate();
  const [data, setData] = useState<ExecutionData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<KindFilter>("all");

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError("");
    try {
      setData(await loadExecution(signal));
    } catch (cause) {
      if (signal?.aborted) return;
      setError(cause instanceof Error ? cause.message : "İcra dosyaları yüklenemedi.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const visible = useMemo(() => (data ? filterFiles(data.files, query, kind) : []), [data, query, kind]);
  const summary = data?.summary;

  return (
    <DashboardLayout
      title="İcra Takibi"
      subtitle="UYAP'tan aktarılan icra dosyaları ve evrakları"
      actions={
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading} aria-label="Yenile">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
        </Button>
      }
    >
      {error && (
        <p role="alert" className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </p>
      )}

      {loading && !data && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" /> İcra dosyaları yükleniyor…
        </p>
      )}

      {data && data.files.length === 0 && !error && (
        <section role="status" className="max-w-2xl rounded-xl border border-border bg-card p-6" data-testid="execution-empty">
          <h2 className="text-lg font-semibold">Henüz icra dosyası yok</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            İcra dosyaları UYAP'tan aktarıldığında burada listelenir; adı "İcra Dairesi" ya da "İcra Hukuk Mahkemesi" olan her dosya otomatik tanınır.
          </p>
          <Link to="/dashboard/uyap" className="mt-3 inline-block text-sm text-primary underline">
            UYAP'a Bağlan sayfasına git
          </Link>
        </section>
      )}

      {data && data.files.length > 0 && summary && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="execution-summary">
            <Stat
              label="İcra dosyası"
              value={String(summary.files)}
              note={`${summary.documents} evrak · ${summary.verifiedComplete}/${summary.files} dosya UYAP ile eksiksiz doğrulandı`}
            />
            <Stat
              label="Tahsilat makbuzları"
              value={summary.tahsilat.read > 0 ? formatLira(summary.tahsilat.total) : "—"}
              note={receiptNote(summary.tahsilat)}
            />
            <Stat
              label="Masraf makbuzları"
              value={summary.masraf.read > 0 ? formatLira(summary.masraf.total) : "—"}
              note={receiptNote(summary.masraf)}
            />
            <Stat
              label="Reddiyat makbuzları"
              value={String(data.files.reduce((sum, file) => sum + (file.counts.reddiyat ?? 0), 0))}
              note="tutar makbuz biçimi nedeniyle okunmuyor"
            />
          </div>
          <p className="mt-3 text-xs text-muted-foreground" role="note">
            Tutarlar makbuz metninden okunur, hesaplanmaz: tek ve açık bir tutar okunamayan makbuz toplama girmez ve yukarıda sayıyla belirtilir.
            Belge taranmış görüntüyse ya da henüz okunmadıysa tutar görünmez. Önemli kararlardan önce makbuzun aslına bakın.
          </p>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <div className="relative min-w-[220px] max-w-sm flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Dosya no ya da daire ara…"
                aria-label="İcra dosyası ara"
                className="h-10 w-full rounded-lg border border-transparent bg-secondary/60 pl-10 pr-4 text-sm outline-none focus:border-primary/40"
              />
            </div>
            <div className="flex items-center gap-1.5 text-xs" role="group" aria-label="Tür">
              {KIND_FILTERS.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  aria-pressed={kind === item.key}
                  onClick={() => setKind(item.key)}
                  className={cn(
                    "rounded-full border px-3 py-1.5 font-medium transition-colors",
                    kind === item.key ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-muted-foreground hover:text-foreground",
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-4 overflow-hidden rounded-2xl border border-border bg-card shadow-card-elite">
            {visible.length === 0 ? (
              <p className="p-6 text-center text-sm text-muted-foreground">Aramayla eşleşen icra dosyası yok.</p>
            ) : (
              <table className="w-full text-sm" data-testid="execution-table">
                <thead>
                  <tr className="bg-secondary/40 text-left text-xs uppercase tracking-wider text-muted-foreground">
                    <th className="px-3 py-3 font-medium sm:px-6">Dosya</th>
                    <th className="hidden px-6 py-3 font-medium lg:table-cell">Evraklar</th>
                    <th className="hidden px-6 py-3 font-medium md:table-cell">Tahsilat</th>
                    <th className="hidden px-6 py-3 font-medium sm:table-cell">Son evrak</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((file) => (
                    <tr
                      key={file.case_id}
                      className="cursor-pointer border-t border-border transition hover:bg-secondary/30"
                      onClick={() => navigate(`/dashboard/cases/${file.case_id}`)}
                    >
                      <td className="px-3 py-4 sm:px-6">
                        <Link
                          to={`/dashboard/cases/${file.case_id}`}
                          className="font-medium hover:underline"
                          onClick={(event: React.MouseEvent) => event.stopPropagation()}
                        >
                          {file.file_no ?? "Numarasız dosya"}
                        </Link>
                        <div className="mt-0.5 text-xs text-muted-foreground">
                          {file.court}
                          {closedOffice(file.court) && " · daire kapatılmış"}
                        </div>
                        <div className="mt-0.5 text-xs text-muted-foreground">
                          {KIND_LABELS[file.kind]} · {file.documents} evrak
                          {file.uyap?.durum ? ` · UYAP: ${shortStatus(file.uyap.durum)}` : ""}
                          {file.uyap?.rol ? ` · ${file.uyap.rol}` : ""}
                        </div>
                        {(() => {
                          const verification = verificationLabel(file.uyap);
                          return (
                            <div
                              className={cn(
                                "mt-0.5 text-xs",
                                verification.tone === "ok" && "text-emerald-600",
                                verification.tone === "warn" && "text-amber-600",
                                verification.tone === "none" && "text-muted-foreground",
                              )}
                              data-testid="execution-verification"
                            >
                              {verification.text}
                            </div>
                          );
                        })()}
                        {file.detail && (
                          <div className="mt-0.5 text-xs" data-testid="execution-account">
                            <span className="text-muted-foreground">UYAP dosya hesabı: </span>
                            {accountLine(file.detail.account) || <span className="text-muted-foreground">yazılı bilgi yok</span>}
                            {" · "}
                            <Link
                              to={`/dashboard/cases/${file.case_id}?tab=uyap`}
                              className="underline"
                              onClick={(event: React.MouseEvent) => event.stopPropagation()}
                            >
                              UYAP bilgileri{file.detail.complete ? "" : " (eksik)"}
                            </Link>
                          </div>
                        )}
                        <div className="mt-1 text-xs text-muted-foreground md:hidden">Tahsilat: {receiptLine(file.receipts.tahsilat)}</div>
                      </td>
                      <td className="hidden px-6 py-4 lg:table-cell">
                        <div className="flex flex-wrap gap-1.5">
                          {countBadges(file.counts, data.labels).map((badge) => (
                            <span key={badge.key} className="rounded-full border border-border bg-secondary/50 px-2 py-0.5 text-xs">
                              {badge.label} <span className="font-medium">{badge.count}</span>
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="hidden px-6 py-4 text-xs md:table-cell">{receiptLine(file.receipts.tahsilat)}</td>
                      <td className="hidden px-6 py-4 text-xs sm:table-cell">{dateTr(file.last_date)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/execution")({
  component: ExecutionPage,
});

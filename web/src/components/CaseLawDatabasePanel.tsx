import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Database, Loader2, RefreshCw, ShieldCheck, TriangleAlert } from "lucide-react";
import { getCorpusStats, type CorpusStats } from "@/lib/legal-api";

const number = new Intl.NumberFormat("tr-TR");

function format(value: number | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? number.format(value) : "—";
}

function SourceRow({
  label,
  official,
  archive = 0,
}: {
  label: string;
  official: number;
  archive?: number;
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-border/60 py-2 last:border-0">
      <span className="text-sm font-medium">{label}</span>
      <div className="flex flex-wrap justify-end gap-2 text-xs">
        <span className="text-emerald-700 dark:text-emerald-400">{format(official)} resmî</span>
        {archive > 0 && (
          <span className="text-amber-700 dark:text-amber-400">{format(archive)} doğrulanmadı</span>
        )}
      </div>
    </div>
  );
}

export const CaseLawDatabasePanel = () => {
  const [stats, setStats] = useState<CorpusStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadStats = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setStats(await getCorpusStats());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Korpus bilgisi alınamadı.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStats();
    const timer = window.setInterval(() => void loadStats(), 30_000);
    return () => window.clearInterval(timer);
  }, [loadStats]);

  if (loading && !stats) {
    return (
      <Card className="mb-5 flex items-center gap-3 p-5 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Gerçek hukuk korpusu okunuyor…
      </Card>
    );
  }

  if (error && !stats) {
    return (
      <Card className="mb-5 flex items-center justify-between gap-4 border-destructive/30 p-5">
        <span className="text-sm text-destructive">{error}</span>
        <Button size="sm" variant="outline" onClick={() => void loadStats()}>
          Tekrar dene
        </Button>
      </Card>
    );
  }

  if (!stats) return null;

  const courtTotal = stats.decision_count + stats.seed_count;
  const embeddingTotal = stats.embeddings.ready + stats.embeddings.pending;
  const embeddingPercent = embeddingTotal
    ? Math.min(100, (stats.embeddings.ready / embeddingTotal) * 100)
    : 0;

  return (
    <Card className="mb-5 border-primary/20 bg-gradient-to-br from-primary/5 to-background p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-primary/10 p-2.5">
            <Database className="h-5 w-5 text-primary" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-semibold">NHR Türk Hukuku Korpusu</h2>
              <Badge variant="secondary">{format(courtTotal)} yargı kararı</Badge>
              <Badge variant="outline">canlı</Badge>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              PostgreSQL üzerindeki gerçek veriler gösterilir; sayaçlar 30 saniyede bir yenilenir.
            </p>
          </div>
        </div>
        <Button size="sm" variant="outline" onClick={() => void loadStats()} disabled={loading}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Yenile
        </Button>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border bg-card p-4">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" /> Resmî doğrulanmış karar
          </div>
          <div className="mt-2 text-2xl font-semibold tabular-nums">
            {format(stats.decision_count)}
          </div>
        </div>
        <div className="rounded-xl border bg-card p-4">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <TriangleAlert className="h-3.5 w-3.5 text-amber-600" /> Doğrulanmamış arşiv
          </div>
          <div className="mt-2 text-2xl font-semibold tabular-nums">{format(stats.seed_count)}</div>
        </div>
        <div className="rounded-xl border bg-card p-4">
          <div className="text-xs text-muted-foreground">Mevzuat maddesi</div>
          <div className="mt-2 text-2xl font-semibold tabular-nums">
            {format(stats.legislation_verification.bedesten)}
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground">
            {format(stats.legislation_count)} çift doğrulanmış
          </div>
        </div>
        <div className="rounded-xl border bg-card p-4">
          <div className="text-xs text-muted-foreground">Aranabilir metin parçası</div>
          <div className="mt-2 text-2xl font-semibold tabular-nums">
            {format(stats.chunk_count)}
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.2fr_1fr]">
        <div className="rounded-xl border bg-card px-4 py-2">
          <SourceRow
            label="Yargıtay"
            official={stats.court_decisions.yargitay}
            archive={stats.third_party.yargitay}
          />
          <SourceRow
            label="Danıştay"
            official={stats.court_decisions.danistay}
            archive={stats.third_party.danistay}
          />
          <SourceRow
            label="AYM"
            official={stats.court_decisions.anayasa_mahkemesi}
            archive={stats.third_party.aym_norm_denetimi}
          />
          <SourceRow
            label="İstinaf / Emsal"
            official={stats.court_decisions.istinaf_emsal}
            archive={stats.third_party.istinaf_emsal}
          />
          <SourceRow label="KDK" official={stats.administrative.kamu_denetciligi_kurumu} />
          <SourceRow label="Sayıştay" official={stats.administrative.sayistay} />
          <SourceRow
            label="Uyuşmazlık Mahkemesi"
            official={stats.administrative.uyusmazlik_mahkemesi}
          />
        </div>

        <div className="rounded-xl border bg-card p-4">
          <div className="flex items-center justify-between gap-3 text-sm">
            <span className="font-medium">Embedding ilerlemesi</span>
            <span className="tabular-nums text-muted-foreground">
              %{embeddingPercent.toFixed(1)}
            </span>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${embeddingPercent}%` }}
            />
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
            <div>
              <div className="text-muted-foreground">Hazır</div>
              <div className="mt-1 font-semibold tabular-nums">
                {format(stats.embeddings.ready)}
              </div>
            </div>
            <div>
              <div className="text-muted-foreground">Bekleyen</div>
              <div className="mt-1 font-semibold tabular-nums">
                {format(stats.embeddings.pending)}
              </div>
            </div>
          </div>
          <div className="mt-4 border-t pt-3 text-xs text-muted-foreground">
            Son karar tarihi: {stats.latest_decision_date ?? "—"}
          </div>
        </div>
      </div>

      <div className="mt-4 flex items-start gap-2 rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-300">
        <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        Üçüncü taraf hazır corpus ayrı tutulur ve resmî doğrulama yapılmadan resmî kaynak olarak
        gösterilmez.
      </div>
    </Card>
  );
};

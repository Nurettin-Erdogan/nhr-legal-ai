import { useEffect, useState, useSyncExternalStore } from "react";
import { useAuth } from "@/components/AuthContext";
import { loadAuditRuns } from "@/lib/uyap-sync-api";
import { getSyncState, subscribeSync } from "@/lib/uyap-sync-store";
import { fullyVerified, reportText } from "@/lib/uyap-sync-all";
import type { StoredAuditRun } from "@/lib/uyap-run-report";

/** Available without an extension or portal session. Historical reports never start transfers. */
export const UyapRunHistory = () => {
  const { user } = useAuth();
  const userId = user?.id;
  const { savedVersion } = useSyncExternalStore(subscribeSync, getSyncState, getSyncState);
  const [loaded, setLoaded] = useState<{ ownerId: string; runs: StoredAuditRun[] | null }>();
  // Do not flash the previous account's private report during an account switch.
  const history = loaded?.ownerId === userId ? loaded?.runs : undefined;
  useEffect(() => {
    setLoaded(undefined);
    const controller = new AbortController();
    if (userId)
      void loadAuditRuns(controller.signal).then((r) => {
        if (!controller.signal.aborted) setLoaded({ ownerId: userId, runs: r });
      });
    return () => controller.abort();
  }, [userId, savedVersion]);
  return (
    <section className="rounded-2xl border bg-card p-5 space-y-3" data-testid="uyap-run-history">
      <h2 className="font-semibold">Kaydedilmiş UYAP denetimleri</h2>
      <p className="text-xs text-muted-foreground">
        Son 5 koşu burada gösterilir; tam raporlar hesabında saklanır. Tarihli sonuçlardır; açık
        UYAP oturumunun güncel durumu değildir. Belge içeriği bu raporlarda tutulmaz.
      </p>
      {history === undefined ? (
        <p className="text-sm">Raporlar yükleniyor…</p>
      ) : history === null ? (
        <p role="alert" className="text-sm text-amber-600">
          Kaydedilmiş raporlar okunamadı; rapor yok olarak kabul edilmedi. Sayfayı yenileyerek
          tekrar deneyebilirsin.
        </p>
      ) : !history.length ? (
        <p className="text-sm text-muted-foreground">
          Henüz tam koşu raporu kaydedilmedi. İlk yeni denetimden itibaren burada görünür.
        </p>
      ) : (
        history.map((h) => (
          <details key={h.id} className="rounded-lg border p-3" data-testid="uyap-saved-run">
            <summary className="cursor-pointer text-sm font-medium">
              {h.updatedAt ? new Date(h.updatedAt).toLocaleString("tr-TR") : "Kaydedilmiş koşu"} ·{" "}
              {h.verifyOnly ? "Denetim" : "Aktarım"} · {h.run.summary.files} dosya
              {h.finished
                ? ` · ${h.run.reports.filter(fullyVerified).length}/${h.run.summary.files} evrak ve bilgi doğrulandı · ${h.run.summary.incomplete} eksik, ${h.run.summary.failed} okunamadı, ${h.run.summary.pending} işlenmedi`
                : " · Yarım kalmış koşu kaydı (tamamlandı sayılmaz)"}
            </summary>
            {!h.listComplete && (
              <p className="text-xs text-amber-600 mt-2">
                Bu koşuda dosya listesinin tamamı doğrulanmamıştı.
              </p>
            )}
            {h.saveNote?.kind === "warn" && (
              <p className="text-xs text-amber-600 mt-2">{h.saveNote.text}</p>
            )}
            <pre
              className="mt-3 whitespace-pre-wrap break-words text-xs font-sans"
              data-testid="uyap-saved-run-text"
            >
              {reportText(h.run)}
            </pre>
          </details>
        ))
      )}
    </section>
  );
};

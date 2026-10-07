import { useEffect, useState, useSyncExternalStore } from "react";
import { toast } from "sonner";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCopy,
  Loader2,
  RefreshCw,
  Square,
} from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import type { DosyaListe } from "@/lib/uyap-bridge";
import { loadSyncStatus, type SyncStatus } from "@/lib/uyap-sync-api";
import {
  fullyVerified,
  reportText,
  retryKeysFor,
  summarize,
  type FileOutcome,
} from "@/lib/uyap-sync-all";
import {
  getSyncState,
  onSyncFinished,
  startSync,
  stopSync,
  subscribeSync,
} from "@/lib/uyap-sync-store";

// Koşu bittiğinde kullanıcı başka bir sayfada da olsa bildirim görür (modül düzeyinde bir kez kaydedilir).
onSyncFinished(({ run, pull, saveWarning }) => {
  const s = run.summary;
  if (
    s.allComplete &&
    run.reports.every(fullyVerified) &&
    !saveWarning &&
    !run.stoppedBecause &&
    !run.aborted
  )
    toast.success(
      pull
        ? `UYAP: ${s.files} dosyanın evrakları ve bilgileri eksiksiz aktarıldı.`
        : `UYAP: ${s.files} dosyanın evrakları ve bilgileri eksiksiz doğrulandı.`,
    );
  else
    toast.warning(
      `UYAP işlemi bitti: ${s.complete + s.empty}/${s.files} dosyanın evrakları doğrulandı. Dosya bilgileri ve kayıt uyarıları için UYAP raporunu kontrol et.`,
    );
});

const OUTCOME_LABEL: Record<FileOutcome, string> = {
  complete: "Evraklar eksiksiz",
  empty: "Evrak yok",
  incomplete: "Evrak eksik",
  failed: "Okunamadı",
  pending: "İşlenmedi",
};
const OUTCOME_CLASS: Record<FileOutcome, string> = {
  complete: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  empty: "border-border bg-muted text-muted-foreground",
  incomplete: "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  failed: "border-destructive/40 bg-destructive/10 text-destructive",
  pending: "border-border bg-muted text-muted-foreground",
};

interface Props {
  liste: DosyaListe;
  /** Başka bir işlem (tek dosya paneli, liste yenileme) sürerken başlatılamaz. */
  disabled: boolean;
  /** Koşu sürerken üst bileşen listeyi ve tek dosya düğmelerini kilitler. */
  onRunningChange: (running: boolean) => void;
}

/**
 * UYAP'taki bütün dosyaların bütün evraklarını sırayla aktarır ve her dosyanın eksiksizliğini sunucudaki kayıtla doğrular.
 * "Eksiksiz" yalnız aktarımdan sonra yeniden okunan UYAP ağacındaki her evrak JurisAI'da kayıtlıysa yazılır.
 */
export const UyapSyncAll = ({ liste, disabled, onRunningChange }: Props) => {
  const [confirming, setConfirming] = useState<Set<string> | "all" | null>(null);
  // Koşunun durumu depoda durur: başka sayfaya geçip dönünce ilerleme ve rapor yerindedir, koşu arka planda sürer.
  const { running, progress, live, run, verifyOnly, saveNote, savedVersion } = useSyncExternalStore(
    subscribeSync,
    getSyncState,
    getSyncState,
  );
  const [status, setStatus] = useState<SyncStatus | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void loadSyncStatus(controller.signal).then(
      (value) => !controller.signal.aborted && setStatus(value),
    );
    return () => controller.abort();
  }, [savedVersion]);

  useEffect(() => onRunningChange(running), [running, onRunningChange]);

  // Sekme kapanır ya da sayfa yenilenirse koşu yarıda kalır: kullanıcı uyarılır. (Yeniden başlatınca aktarılanlar yeniden çekilmez.)
  useEffect(() => {
    if (!running) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [running]);

  const start = (only?: Set<string>, pull = true) => startSync(liste, only, pull);

  const copy = async () => {
    if (!run) return;
    try {
      await navigator.clipboard.writeText(reportText(run));
      toast.success("Rapor panoya kopyalandı.");
    } catch {
      toast.error("Rapor kopyalanamadı.");
    }
  };

  const shown = run ? run.reports : live;
  const summary = run ? run.summary : summarize(live);
  const retryKeys = run
    ? saveNote?.kind === "warn"
      ? new Set(run.reports.map((report) => report.key))
      : retryKeysFor(run.reports)
    : new Set<string>();
  const everything =
    !running &&
    !!run &&
    run.summary.allComplete &&
    run.reports.every(fullyVerified) &&
    saveNote?.kind !== "warn" &&
    !run.stoppedBecause &&
    !run.aborted &&
    run.reports.length === liste.items.length &&
    liste.complete;
  const percent =
    progress && progress.total ? Math.round((progress.index / progress.total) * 100) : 0;
  const pendingCount = confirming === "all" ? liste.items.length : (confirming?.size ?? 0);

  return (
    <div className="rounded-lg border p-4 space-y-3" data-testid="uyap-sync-all">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-medium text-sm">Tüm dosyaları aktar</h3>
        {!running && !run && status && status.summary.files > 0 && (
          <Badge variant="outline" data-testid="uyap-sync-status">
            Önceki kayıtlı evrak denetimi: {status.summary.complete}/{status.summary.files} dosya
            {status.summary.missing > 0 ? ` · ${status.summary.missing} evrak eksik` : ""}
          </Badge>
        )}
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed">
        Listedeki her dosyanın bütün evrakları sırayla JurisAI hesabına aktarılır. Her dosyadan
        sonra UYAP evrak ağacı yeniden okunur ve ağaçtaki her evrakın JurisAI'da kayıtlı olduğu
        doğrulanır; kayıtlı olmayan tek bir evrak varsa dosya "eksik" yazılır. Daha önce aktarılan
        evraklar yeniden çekilmez. İşlem dosya sayısına göre saatler sürebilir: UYAP sekmesini ve bu
        sayfayı kapatma.
      </p>
      {!liste.complete && (
        <p className="text-xs text-amber-600" role="alert">
          Dosya listesinin tamamı doğrulanamadı: aktarım yalnız listede görünen {liste.items.length}{" "}
          dosyayı kapsar; sonuç "bütün dosyalar" olarak kabul edilmemeli.
        </p>
      )}

      {!running && (
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() => setConfirming("all")}
            disabled={disabled || liste.items.length === 0}
            data-testid="uyap-sync-all-start"
          >
            Tüm dosyaları aktar ({liste.items.length} dosya)
          </Button>
          <Button
            variant="outline"
            onClick={() => void start(undefined, false)}
            disabled={disabled || liste.items.length === 0}
            data-testid="uyap-sync-verify"
            title="Hiçbir evrak aktarılmaz: UYAP'taki evraklar JurisAI'daki kayıtlarla karşılaştırılır"
          >
            Yalnız denetle (aktarmadan)
          </Button>
          {run && retryKeys.size > 0 && (
            <Button
              variant="outline"
              onClick={() => setConfirming(retryKeys)}
              disabled={disabled}
              data-testid="uyap-sync-retry"
            >
              <RefreshCw className="h-4 w-4 mr-2" /> Eksik kalan {retryKeys.size} dosyayı yeniden
              dene
            </Button>
          )}
          {run && (
            <Button variant="ghost" onClick={() => void copy()}>
              <ClipboardCopy className="h-4 w-4 mr-2" /> Raporu kopyala
            </Button>
          )}
        </div>
      )}

      {running && progress && (
        <div className="space-y-2" role="status" data-testid="uyap-sync-progress">
          <div className="flex items-center gap-2 text-sm">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            <span className="font-medium">
              Dosya {Math.min(progress.index + 1, progress.total)}/{progress.total}
            </span>
            <span className="truncate text-muted-foreground">{progress.name}</span>
          </div>
          <Progress value={percent} />
          <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>{progress.phase}</span>
            <Button
              size="sm"
              variant="outline"
              onClick={() => stopSync()}
              disabled={progress.index >= progress.total}
              data-testid="uyap-sync-stop"
            >
              <Square className="h-3.5 w-3.5 mr-2" /> Durdur
            </Button>
          </div>
        </div>
      )}

      {run && (
        <div
          role={everything ? "status" : "alert"}
          className={`rounded-lg border p-3 text-sm ${everything ? "border-emerald-500/30 bg-emerald-500/5" : "border-amber-500/30 bg-amber-500/5"}`}
          data-testid="uyap-sync-result"
        >
          <p className="flex items-center gap-2 font-medium">
            {everything ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-amber-600" />
            )}
            {everything
              ? `Bütün dosyalar eksiksiz: ${summary.files} dosya, ${summary.stored} evrak JurisAI'da doğrulandı${summary.empty ? ` (${summary.empty} dosyada UYAP evrak göstermiyor)` : ""}.`
              : `Evrak doğrulaması: ${summary.complete + summary.empty}/${summary.files} dosya tamamlandı; ${summary.incomplete} eksik, ${summary.failed} okunamadı, ${summary.pending} işlenmedi. Dosya bilgileri ayrıca aşağıda gösterilir.`}
          </p>
          <p className="mt-1 text-xs text-muted-foreground" data-testid="uyap-sync-detail-summary">
            Dosya bilgileri (taraflar, safahat, dosya hesabı, tahsilat): {summary.detailComplete}{" "}
            dosyada eksiksiz
            {summary.detailPartial ? `, ${summary.detailPartial} dosyada eksik` : ""}
            {summary.detailFailed ? `, ${summary.detailFailed} dosyada okunamadı` : ""};{" "}
            {summary.detailSaved} dosya JurisAI'a kaydedildi.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            UYAP'ta bulunan {summary.found} evraktan {summary.stored} tanesi JurisAI'da kayıtlı;{" "}
            {verifyOnly
              ? "bu bir denetimdi, hiçbir evrak aktarılmadı"
              : `bu çalışmada ${summary.sent} evrak gönderildi`}
            {summary.missing > 0 ? `, ${summary.missing} evrak eksik` : ""}.
          </p>
          {run.stoppedBecause && <p className="mt-1 text-xs">Durduruldu: {run.stoppedBecause}</p>}
          {run.aborted && <p className="mt-1 text-xs">Sen durdurdun; kalan dosyalar işlenmedi.</p>}
          {saveNote && (
            <p
              className={`mt-1 text-xs ${saveNote.kind === "warn" ? "text-amber-700 dark:text-amber-300" : "text-muted-foreground"}`}
            >
              {saveNote.text}
            </p>
          )}
        </div>
      )}

      {shown.length > 0 && (
        <ul className="divide-y rounded-lg border text-sm" data-testid="uyap-sync-report">
          {shown.map((report) => (
            <li
              key={report.key}
              className="flex flex-wrap items-start gap-3 p-3"
              data-outcome={report.outcome}
            >
              <span
                className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium ${OUTCOME_CLASS[report.outcome]}`}
              >
                {OUTCOME_LABEL[report.outcome]}
              </span>
              <div className="min-w-0 flex-1">
                <div className="font-medium">
                  {report.esas || "Dosya"}{" "}
                  <span className="font-normal text-muted-foreground">· {report.birim}</span>
                </div>
                <div className="text-xs text-muted-foreground">
                  {report.outcome === "empty"
                    ? "UYAP bu dosyada evrak bulunmadığını bildiriyor; aktarılacak evrak yok"
                    : report.outcome === "pending" && report.found === 0
                      ? "Henüz okunmadı"
                      : `${report.stored}/${report.found} evrak JurisAI'da${report.declared ? ` · UYAP sayısı: ${report.declared}` : ""}${report.sent ? ` · ${report.sent} gönderildi` : ""}`}
                </div>
                {report.detail && report.detail.state !== "skipped" && (
                  <div className="text-xs text-muted-foreground" data-testid="uyap-sync-detail">
                    Dosya bilgileri:{" "}
                    {report.detail.state === "complete"
                      ? `eksiksiz okundu (${report.detail.tabs} sekme)${report.detail.saved ? " ve kaydedildi" : ""}`
                      : report.detail.state === "partial"
                        ? `eksik (${report.detail.tabs} sekme okundu)${report.detail.saved ? ", kaydedildi" : ""}`
                        : "okunamadı"}
                  </div>
                )}
                {[
                  ...report.problems,
                  ...(report.detail && (report.detail.state !== "complete" || !report.detail.saved)
                    ? report.detail.problems
                    : []),
                ].length > 0 && (
                  <ul className="mt-1 list-disc pl-4 text-xs text-amber-700 dark:text-amber-300">
                    {[
                      ...report.problems,
                      ...(report.detail &&
                      (report.detail.state !== "complete" || !report.detail.saved)
                        ? report.detail.problems
                        : []),
                    ].map((problem) => (
                      <li key={problem}>{problem}</li>
                    ))}
                  </ul>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      <AlertDialog open={confirming !== null} onOpenChange={(open) => !open && setConfirming(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {pendingCount} dosyanın bütün evrakları aktarılsın mı?
            </AlertDialogTitle>
            <AlertDialogDescription>
              Eklenti, açık UYAP oturumunda bu dosyaları sırayla açıp evraklarını JurisAI hesabına
              aktarır. Evraklar yalnız senin hesabında saklanır. Daha önce aktarılanlar atlanır.
              İşlem uzun sürebilir; istediğin an durdurabilir, sonra kaldığı yerden devam
              edebilirsin.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Vazgeç</AlertDialogCancel>
            <AlertDialogAction
              data-testid="uyap-sync-confirm"
              onClick={() => {
                const target = confirming;
                setConfirming(null);
                void start(target === "all" || target === null ? undefined : target);
              }}
            >
              Aktarımı başlat
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

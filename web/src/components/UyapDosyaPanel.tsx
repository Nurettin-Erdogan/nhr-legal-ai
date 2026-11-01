import { useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import {
  defaultSelection,
  groupTreeItems,
  pullOutcome,
  startPullJob,
  startTreeJob,
  stopJob,
  waitForJob,
  type BridgeDosya,
  type JobStatus,
  type RunInfo,
  type TreeResult,
} from "@/lib/uyap-bridge";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";

type Phase = "loading" | "select" | "pulling" | "done" | "error";

interface Props {
  dosya: BridgeDosya;
  onClose: () => void;
}

/**
 * Bir UYAP dosyasının evrak ağacını JurisAI içinde gösterir, seçtiklerini JurisAI'ya aktarır.
 * Ağacı açma ve evrak çekme işini eklenti UYAP sekmesinde yürütür; bu panel yalnız ilerlemeyi gösterir ve seçimi yapar.
 */
export const UyapDosyaPanel = ({ dosya, onClose }: Props) => {
  const [phase, setPhase] = useState<Phase>("loading");
  const [phaseText, setPhaseText] = useState("UYAP sekmesine bağlanılıyor");
  const [error, setError] = useState<{ message: string; code?: string } | null>(null);
  const [tree, setTree] = useState<TreeResult | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [run, setRun] = useState<RunInfo | null>(null);
  const [scan, setScan] = useState(0);
  const [allowPartial, setAllowPartial] = useState(false);
  const [starting, setStarting] = useState(false);
  const job = useRef<{ tabId: number; jobId: string } | null>(null);
  const abort = useRef<AbortController | null>(null);

  // Ağaç işi: dosya açılır, ağaç açılır, daha önce aktarılanlar sorulur.
  useEffect(() => {
    setPhase("loading");
    setError(null);
    setAllowPartial(false);
    setRun(null);
    const controller = new AbortController();
    abort.current = controller;
    void (async () => {
      const started = await startTreeJob(dosya.key, dosya.yargiTuru);
      if (controller.signal.aborted) return;
      if (!started.ok) {
        setError({ message: started.error, code: started.code });
        setPhase("error");
        return;
      }
      job.current = { tabId: started.tabId, jobId: started.jobId };
      const finished = await waitForJob(started.tabId, started.jobId, {
        withTree: true,
        signal: controller.signal,
        onUpdate: (status: JobStatus) => setPhaseText(status.job.phase || "Evrak ağacı okunuyor"),
      });
      if (controller.signal.aborted) return;
      if (!finished.ok) {
        setError({ message: finished.error, code: finished.code });
        setPhase("error");
        return;
      }
      const { status } = finished;
      if (status.job.state === "error" || !status.tree) {
        setError({ message: status.job.error || "Evrak ağacı okunamadı.", code: status.job.code });
        setPhase("error");
        return;
      }
      setTree(status.tree);
      setSelected(defaultSelection(status.tree.items, status.tree.known));
      setPhase("select");
    })();
    return () => controller.abort();
  }, [dosya.key, dosya.yargiTuru, scan]);

  const groups = useMemo(() => (tree ? groupTreeItems(tree.items) : []), [tree]);
  const known = useMemo(() => new Set(tree?.known ?? []), [tree]);
  const mainCount = tree ? tree.items.filter((item) => !item.isEk).length : 0;
  const newCount = tree ? tree.items.filter((item) => !known.has(item.id)).length : 0;

  const toggle = (id: string, on: boolean) =>
    setSelected((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  const toggleGroup = (ids: string[], on: boolean) =>
    setSelected((current) => {
      const next = new Set(current);
      for (const id of ids) {
        if (on) next.add(id);
        else next.delete(id);
      }
      return next;
    });

  const startPull = async () => {
    if (!job.current || !tree || !selected.size || starting) return;
    setStarting(true);
    setError(null);
    const { tabId } = job.current;
    const started = await startPullJob(tabId, [...selected], "upload");
    setStarting(false);
    if (!started.ok) {
      setError({ message: started.error, code: started.code });
      return;
    }
    job.current = { tabId, jobId: started.jobId };
    setRun({
      mode: "upload",
      chosen: started.total,
      total: started.total,
      done: 0,
      current: "",
      phase: "Başlıyor",
    });
    setPhase("pulling");
    const controller = new AbortController();
    abort.current = controller;
    const finished = await waitForJob(tabId, started.jobId, {
      signal: controller.signal,
      onUpdate: (status) => status.run && setRun(status.run),
    });
    if (controller.signal.aborted) return;
    if (!finished.ok) {
      setError({ message: finished.error, code: finished.code });
      setPhase("error");
      return;
    }
    if (finished.status.run) setRun(finished.status.run);
    if (finished.status.job.state === "error") {
      setError({
        message: finished.status.job.error || "Aktarım başarısız.",
        code: finished.status.job.code,
      });
      setPhase("error");
      return;
    }
    setPhase("done");
  };

  const stop = async () => {
    if (job.current) await stopJob(job.current.tabId, job.current.jobId);
  };

  const close = () => {
    abort.current?.abort();
    onClose();
  };

  const percent = run && run.total ? Math.min(100, Math.round((run.done / run.total) * 100)) : 0;
  const counts = tree?.counts;
  const incomplete =
    !!counts &&
    ((!counts.matches && !counts.explained) ||
      counts.withoutId > 0 ||
      counts.unopened > 0 ||
      counts.emptyOpened > 0);
  const outcome = run ? pullOutcome(run) : "partial";
  const rescan = () => setScan((value) => value + 1);

  return (
    <Dialog open onOpenChange={(open) => !open && phase !== "pulling" && close()}>
      <DialogContent
        className="max-w-3xl max-h-[90vh] flex flex-col gap-3"
        data-testid="uyap-dosya-panel"
      >
        <DialogHeader>
          <DialogTitle>{dosya.esas || dosya.cells[0] || "UYAP dosyası"}</DialogTitle>
          <DialogDescription>
            {dosya.birim || "Evrakları seç ve JurisAI hesabına aktar."}
          </DialogDescription>
        </DialogHeader>

        {phase === "loading" && (
          <div className="py-8 text-center space-y-2" data-testid="uyap-panel-loading">
            <Loader2 className="h-6 w-6 animate-spin mx-auto text-primary" />
            <p className="text-sm font-medium">{phaseText}…</p>
            <p className="text-xs text-muted-foreground">
              Eklenti UYAP sekmesinde dosyayı açıp evrak ağacını okuyor. Büyük dosyalarda birkaç
              dakika sürebilir; UYAP sekmesini kapatma.
            </p>
            <Button variant="outline" size="sm" onClick={close}>
              Vazgeç
            </Button>
          </div>
        )}

        {phase === "error" && error && (
          <div className="space-y-3">
            <div
              role="alert"
              className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm flex gap-2"
            >
              <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0 text-destructive" />
              <span>{error.message}</span>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={rescan}>
                Yeniden tara ve kalanları seç
              </Button>
              <Button variant="outline" onClick={close}>
                Kapat
              </Button>
            </div>
          </div>
        )}

        {phase === "select" && tree && counts && (
          <>
            <div className="text-sm space-y-1" data-testid="uyap-panel-summary">
              <div className="flex flex-wrap gap-2 items-center">
                <Badge variant="secondary">{tree.items.length} evrak</Badge>
                <span className="text-muted-foreground">
                  {mainCount} asıl · {tree.items.length - mainCount} ek
                </span>
                {tree.knownChecked && tree.known.length > 0 && (
                  <Badge variant="outline">{tree.known.length} tanesi JurisAI'da zaten var</Badge>
                )}
              </div>
              <p
                className={
                  counts.matches || counts.explained
                    ? "text-xs text-emerald-600"
                    : "text-xs text-destructive"
                }
              >
                UYAP klasör sayıları: {counts.declaredTotal} evrak · bulunan: {counts.foundTotal}
                {counts.eks ? ` · ayrıca ${counts.eks} ek` : ""}
                {counts.matches
                  ? " ✓ sayılar tutuyor"
                  : counts.explained
                    ? ` ✓ fark ${counts.declaredTotal - counts.foundTotal} evrağın iki klasörde birden görünmesinden (tek kez çekilir)`
                    : ` ⚠ sayılar tutmuyor${counts.gapList.length ? ` — fark: ${counts.gapList.slice(0, 4).join("; ")}` : ""}`}
              </p>
              <p className="text-xs text-muted-foreground">
                Aynı evrak ya da ek UYAP'ta birden çok klasörde/evrakta görünüyorsa bir kez
                listelenir ve bir kez çekilir.
              </p>
              {!tree.knownChecked && (
                <p className="text-xs text-amber-600">
                  Mevcut evrak kontrolü başarısız; yeniden aktarımların tamamının atlanacağı garanti
                  edilemez.
                </p>
              )}
              {incomplete && (
                <div role="alert" className="rounded-md border border-amber-500/30 p-2 space-y-2">
                  <p>
                    Tarama eksik olabilir. Önce yeniden tara; devam edersen yalnız bulunan evraklar
                    aktarılır.
                  </p>
                  <Button size="sm" variant="outline" onClick={rescan}>
                    Ağacı yeniden tara
                  </Button>
                  <label className="flex items-center gap-2 text-xs">
                    <Checkbox
                      checked={allowPartial}
                      onCheckedChange={(value) => setAllowPartial(value === true)}
                    />
                    Eksik taramaya rağmen bulunanları aktarmayı seçiyorum.
                  </label>
                </div>
              )}
            </div>

            <div className="flex flex-wrap gap-2 text-xs">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setSelected(new Set(tree.items.map((item) => item.id)))}
              >
                Tümünü seç
              </Button>
              <Button size="sm" variant="outline" onClick={() => setSelected(new Set())}>
                Hiçbirini seçme
              </Button>
              <Button
                size="sm"
                variant="outline"
                data-testid="uyap-select-main"
                onClick={() => setSelected(defaultSelection(tree.items, tree.known, true))}
              >
                Yalnızca asıl evraklar
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setSelected(defaultSelection(tree.items, tree.known))}
              >
                Yalnızca yeni olanlar ({newCount})
              </Button>
            </div>

            <div
              className="overflow-y-auto rounded-lg border p-2 min-h-[160px] flex-1"
              data-testid="uyap-tree-list"
            >
              {groups.map((group) => {
                const ids = group.items.map((item) => item.id);
                const on = ids.filter((id) => selected.has(id)).length;
                return (
                  <div key={group.label} className="mb-2">
                    <label className="flex items-center gap-2 text-sm font-semibold text-primary py-1">
                      <Checkbox
                        checked={on === ids.length ? true : on === 0 ? false : "indeterminate"}
                        onCheckedChange={(value) => toggleGroup(ids, value === true)}
                      />
                      <span className="truncate">📁 {group.label}</span>
                      {group.declared !== null && (
                        <span
                          className={`text-xs font-normal ${group.declared === group.items.length ? "text-muted-foreground" : "text-destructive"}`}
                        >
                          UYAP: {group.declared}, bulunan: {group.items.length}
                        </span>
                      )}
                    </label>
                    <ul className="pl-6 space-y-0.5">
                      {group.items.map((item) => (
                        <li key={item.id}>
                          <label className="flex items-center gap-2 text-sm">
                            <Checkbox
                              checked={selected.has(item.id)}
                              onCheckedChange={(value) => toggle(item.id, value === true)}
                            />
                            <span className="truncate">
                              {item.isEk ? `↳ ${item.title}` : item.title}
                            </span>
                            {known.has(item.id) && (
                              <Badge variant="outline" className="text-[10px]">
                                JurisAI'da var
                              </Badge>
                            )}
                          </label>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </div>

            <p className="text-[11px] text-amber-700 dark:text-amber-400 rounded-md bg-amber-500/5 border border-amber-500/30 p-2">
              Müvekkil verisi içerebilir; yalnızca yetkili olduğun dosyalarda devam et. UYAP'a
              istekler yavaş gönderilir (her evrak için birkaç saniye); UYAP sekmesini kapatma,
              başka sekmelerde çalışabilirsin.
            </p>
            {error && (
              <div
                role="alert"
                className="rounded-lg border border-destructive/30 bg-destructive/5 p-2 text-sm"
              >
                {error.message}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium" data-testid="uyap-selected-count">
                {selected.size} / {tree.items.length} evrak seçili
              </span>
              <span className="flex-1" />
              <Button variant="outline" onClick={close}>
                İptal
              </Button>
              <Button
                disabled={starting || !selected.size || (incomplete && !allowPartial)}
                onClick={() => void startPull()}
                data-testid="uyap-start-pull"
              >
                Seçilenleri JurisAI'ya aktar
              </Button>
            </div>
          </>
        )}

        {phase === "pulling" && run && (
          <div className="space-y-3" data-testid="uyap-panel-pulling">
            <Progress value={percent} />
            <div className="text-sm flex flex-wrap gap-x-3 gap-y-1">
              <span className="font-medium">
                {run.done} / {run.total} evrak
              </span>
              <span className="text-muted-foreground">{run.phase || "Aktarılıyor"}</span>
            </div>
            {run.current && (
              <p className="text-xs text-muted-foreground truncate">Şimdi: {run.current}</p>
            )}
            {run.stats && (
              <div className="flex flex-wrap gap-2 text-xs">
                <Badge variant="outline">Aktarılan: {run.stats.sent}</Badge>
                {run.stats.known > 0 && (
                  <Badge variant="outline">Zaten vardı (tıklanmadı): {run.stats.known}</Badge>
                )}
                {run.stats.duplicates > 0 && (
                  <Badge variant="outline">Zaten vardı: {run.stats.duplicates}</Badge>
                )}
                {run.stats.sameContent > 0 && (
                  <Badge variant="outline">Aynı içerik: {run.stats.sameContent}</Badge>
                )}
                {run.stats.failed > 0 && (
                  <Badge variant="destructive">Hata: {run.stats.failed}</Badge>
                )}
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              UYAP sekmesini kapatma; bu pencereyi açık tutman şart değil, ama aktarım bitmeden
              sekmeyi kapatırsan durur.
            </p>
            <Button variant="outline" onClick={() => void stop()}>
              Durdur
            </Button>
          </div>
        )}

        {phase === "done" && run && (
          <div className="space-y-3" data-testid="uyap-panel-done">
            <div className="flex gap-2 items-start text-sm">
              {outcome === "complete" ? (
                <CheckCircle2 className="h-5 w-5 text-emerald-600 shrink-0" />
              ) : (
                <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0" />
              )}
              <div>
                <p className="font-medium">
                  {outcome === "stopped"
                    ? "Aktarım durduruldu"
                    : outcome === "partial"
                      ? "Aktarım eksik kaldı"
                      : "Seçilen evrakların aktarımı tamamlandı"}
                </p>
                <p className="text-muted-foreground text-xs mt-1">{run.result?.summary}</p>
              </div>
            </div>
            {run.stats && run.stats.errors.length > 0 && (
              <ul className="text-xs text-destructive list-disc pl-5">
                {run.stats.errors.map((message, index) => (
                  <li key={`${index}:${message}`}>{message}</li>
                ))}
              </ul>
            )}
            <div className="flex gap-2">
              <Button variant="outline" onClick={rescan}>
                Yeniden tara ve kalanları seç
              </Button>
              <Button asChild>
                <a href="/dashboard/files">Dosyalar sayfasına git</a>
              </Button>
              <Button variant="outline" onClick={close}>
                Kapat
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};

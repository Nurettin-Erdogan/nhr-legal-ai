import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/AuthContext";
import { Button } from "@/components/ui/button";
import {
  cancelDocumentJob,
  loadDocumentJob,
  listDocumentJobs,
  resumeDocumentJob,
  type DocumentJob,
} from "@/lib/document-jobs";
import { Loader2 } from "lucide-react";
const labels = {
  queued: "Sırada",
  running: "İşleniyor",
  done: "Tamamlandı",
  partial: "Kısmen tamamlandı",
  failed: "Tamamlanamadı",
  cancelled: "Durduruldu",
};

export function DocumentJobPanel({
  jobId,
  module,
  onCompleted,
}: {
  jobId?: string;
  module?: string;
  onCompleted?: (job: DocumentJob) => void;
}) {
  const owner = useAuth().user?.id;
  const [selected, setSelected] = useState(jobId);
  const [job, setJob] = useState<DocumentJob>();
  const [jobs, setJobs] = useState<DocumentJob[]>([]);
  const [error, setError] = useState("");
  const [loadedFor, setLoadedFor] = useState<string>();
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const currentOwner = useRef(owner);
  currentOwner.current = owner;
  const callback = useRef(onCompleted);
  callback.current = onCompleted;
  const delivered = useRef(new Set<string>());
  useEffect(() => {
    if (jobId) setSelected(jobId);
  }, [jobId]);
  useEffect(() => {
    let active = true;
    setJobs([]);
    setJob(undefined);
    setError("");
    setLoadedFor(undefined);
    delivered.current.clear();
    if (!owner) return;
    void listDocumentJobs()
      .then((rows) => {
        if (!active) return;
        const shown = rows.filter((row) => !module || row.module === module);
        setJobs(shown);
        setLoadedFor(owner);
        if (!jobId) setSelected(shown.find((row) => ["queued", "running"].includes(row.state))?.id);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [owner, module, jobId]);
  useEffect(() => {
    if (!owner || !selected) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const next = await loadDocumentJob(selected);
        if (!active) return;
        setJob(next);
        setLoadedFor(owner);
        setError("");
        if (["queued", "running"].includes(next.state)) timer = setTimeout(refresh, 2500);
        else if (next.output_id && next.output && !delivered.current.has(next.output_id)) {
          delivered.current.add(next.output_id);
          callback.current?.(next);
        }
      } catch (e) {
        if (active) {
          setError(e instanceof Error ? e.message : "İş durumu alınamadı.");
          timer = setTimeout(refresh, 5000);
        }
      }
    };
    void refresh();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [selected, owner, revision]);
  const shown = loadedFor === owner ? job : undefined;
  const running = shown && ["queued", "running"].includes(shown.state);
  const action = async (resume: boolean) => {
    if (!shown) return;
    const initiatedBy = owner;
    setBusy(true);
    try {
      if (resume) await resumeDocumentJob(shown.id);
      else await cancelDocumentJob(shown.id);
      if (currentOwner.current === initiatedBy) setRevision((value) => value + 1);
    } catch (e) {
      if (currentOwner.current === initiatedBy)
        setError(e instanceof Error ? e.message : "İşlem yapılamadı.");
    } finally {
      if (currentOwner.current === initiatedBy) setBusy(false);
    }
  };
  return (
    <section
      className="space-y-3 rounded-xl border border-border bg-card p-4"
      aria-label="Belge iş kuyruğu"
    >
      <h3 className="font-semibold">Belge iş kuyruğu</h3>
      <p className="text-xs text-muted-foreground">
        İlerleme sunucuda saklanır. Sayfadan ayrılabilirsiniz; sunucu yeniden başlarsa bu panel işi
        kaldığı bölümden sürdürür.
      </p>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {shown && (
        <div className="space-y-2" role="status">
          <p className="flex gap-2 text-sm">
            {running && <Loader2 className="h-4 w-4 animate-spin" />}
            {labels[shown.state]} · {shown.progress.done}/{shown.progress.total} belge
          </p>
          <progress
            className="w-full"
            max={shown.progress.total || 1}
            value={shown.progress.done}
          />
          {shown.progress.documents.slice(-1).map((document, index) => (
            <p key={index} className="text-xs text-muted-foreground">
              {document.file_name} · {document.windows_done}/{document.windows_total} bölüm okundu
            </p>
          ))}
          {shown.state === "partial" && (
            <p className="text-sm text-amber-600">
              Bazı bölümler tamamlanamadı. Sonuçtaki bölüm uyarılarını inceleyin veya yeniden
              deneyin.
            </p>
          )}
          {shown.error && <p className="text-sm text-destructive">{shown.error}</p>}
          {running ? (
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void action(false)}>
              Durdur
            </Button>
          ) : (
            shown.state !== "done" && (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => void action(true)}>
                Kalanları yeniden dene
              </Button>
            )
          )}
        </div>
      )}
      {!!jobs.length && (
        <details>
          <summary className="cursor-pointer text-sm">Son belge işleri</summary>
          <ul className="mt-2 space-y-1">
            {jobs.slice(0, 5).map((item) => (
              <li key={item.id}>
                <Button variant="ghost" size="sm" onClick={() => setSelected(item.id)}>
                  {labels[item.state]} · {item.progress.done}/{item.progress.total} belge
                </Button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

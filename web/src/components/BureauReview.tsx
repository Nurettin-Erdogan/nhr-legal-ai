import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Button } from "@/components/ui/button";
import { DocumentJobPanel } from "@/components/DocumentJobPanel";
import { CaseDocumentAsk } from "@/components/CaseDocumentAsk";
import { DocumentWorkflowActions } from "@/components/DocumentWorkflowActions";
import { Link } from "@/lib/router-compat";
import {
  bureauSummaryInput,
  loadBureauReview,
  loadCasePreparation,
  preparationNote,
  type BureauProposal,
  type BureauReview as Review,
} from "@/lib/bureau-assistant";
import { loadDocumentJob, startDocumentJob, type DocumentJob } from "@/lib/document-jobs";

export function BureauReview({
  proposal,
  onApprove,
}: {
  proposal: BureauProposal;
  onApprove: (proposal: BureauProposal) => void;
}) {
  const [data, setData] = useState<Review>();
  const [error, setError] = useState("");
  const [jobError, setJobError] = useState("");
  const [starting, setStarting] = useState(false);
  const [jobId, setJobId] = useState<string>();
  const [job, setJob] = useState<DocumentJob>();
  const [revision, setRevision] = useState(0);
  const [selectedIds, setSelectedIds] = useState<string[] | undefined>();
  const [showConversation, setShowConversation] = useState(false);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    const controller = new AbortController();
    const request =
      proposal.kind === "hearing" && proposal.case_id
        ? loadCasePreparation(proposal.case_id, controller.signal)
        : loadBureauReview(proposal.key, controller.signal);
    void request
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "Belgeler alınamadı.");
      });
    return () => {
      active.current = false;
      controller.abort();
    };
  }, [proposal.key, proposal.kind, proposal.case_id]);
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await loadDocumentJob(jobId);
        if (cancelled) return;
        setJob(next);
        setJobError("");
        if (["queued", "running"].includes(next.state)) timer = setTimeout(poll, 2500);
      } catch (e) {
        if (!cancelled) setJobError(e instanceof Error ? e.message : "İş durumu alınamadı.");
      }
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId, revision]);
  const ready = data?.documents.filter((d) => d.ready) ?? [];
  const selected = selectedIds ?? ready.map((d) => d.id);
  const selectedReady = ready.filter((d) => selected.includes(d.id));
  const [copyMessage, setCopyMessage] = useState("");
  const copy = async () => {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(
        preparationNote(data, job?.output ?? undefined, selected),
      );
      if (active.current) setCopyMessage("Hazırlık notu kopyalandı.");
    } catch {
      if (active.current) setCopyMessage("Panoya kopyalanamadı; tarayıcı iznini kontrol edin.");
    }
  };
  const start = async () => {
    if (starting || jobId || !selectedReady.length || !data) return;
    setStarting(true);
    setJobError("");
    try {
      const id = await startDocumentJob(bureauSummaryInput(data, selected));
      if (active.current) setJobId(id);
    } catch (e) {
      if (active.current) setJobError(e instanceof Error ? e.message : "Özet başlatılamadı.");
    } finally {
      if (active.current) setStarting(false);
    }
  };
  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        {proposal.case_title} · {proposal.source_label}
      </p>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {!data && !error && <p role="status">Kaynak belgeler yükleniyor…</p>}
      {data && (
        <>
          {data.preparation && (
            <section className="space-y-3 rounded-lg border bg-muted/30 p-4">
              <h3 className="font-semibold">Dosya hazırlık notu</h3>
              <dl className="grid gap-2 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-muted-foreground">Mahkeme</dt>
                  <dd>{data.preparation.court || "Kayıtlı değil"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Dosya numarası</dt>
                  <dd>{data.preparation.case_no || "Kayıtlı değil"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Kayıtlı duruşma</dt>
                  <dd>
                    {new Date(data.preparation.hearing_at).toLocaleString("tr-TR", {
                      timeZone: "Europe/Istanbul",
                    })}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Belge durumu</dt>
                  <dd>
                    {data.preparation.ready_documents}/{data.preparation.total_documents} belge
                    okunabilir
                  </dd>
                </div>
              </dl>
              <h4 className="text-sm font-medium">Dosyanın açık görevleri</h4>
              {data.preparation.tasks.length ? (
                <ul className="list-disc space-y-1 pl-5 text-sm">
                  {data.preparation.tasks.map((t) => (
                    <li key={t.id}>
                      {t.title}
                      {t.due_date
                        ? ` · Kayıtlı son tarih: ${new Date(t.due_date).toLocaleString("tr-TR", { timeZone: "Europe/Istanbul" })}`
                        : " · Son tarih kayıtlı değil"}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">Kayıtlı açık görev yok.</p>
              )}
              {data.preparation.tasks_limited && (
                <p className="text-xs text-amber-600">İlk 20 açık görev gösteriliyor.</p>
              )}
              <h4 className="text-sm font-medium">Hazırlık kontrol listesi</h4>
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {data.preparation.checklist.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
              <Button variant="outline" onClick={() => void copy()}>
                Hazırlık notunu kopyala
              </Button>
              {copyMessage && (
                <p role="status" className="text-sm">
                  {copyMessage}
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                Bu bölüm kayıtlı bilgileri düzenler; belgeden hukuki süre veya dava stratejisi
                çıkarmaz.
              </p>
            </section>
          )}
          <section className="space-y-3">
            <h3 className="font-semibold">Kaynak belgeler</h3>
            {!data.documents.length && (
              <p className="text-sm text-muted-foreground">
                Bu dosyaya bağlı belge yok. Belge olmadan hazırlık özeti üretilmez.
              </p>
            )}
            {data.limited && (
              <p className="text-sm text-amber-600">
                En yeni 10 belge gösteriliyor; bu çalışma dosyanın tamamını kapsamaz.
              </p>
            )}
            {data.documents.map((d) => (
              <article key={d.id} className="rounded-lg border p-3">
                <label className="flex items-start gap-2 break-words text-sm font-medium">
                  <input
                    type="checkbox"
                    aria-label={`${d.file_name} belgesini seç`}
                    checked={d.ready && selected.includes(d.id)}
                    disabled={!d.ready || starting || !!jobId}
                    onChange={(event) =>
                      setSelectedIds(
                        event.target.checked
                          ? [...selected, d.id]
                          : selected.filter((id) => id !== d.id),
                      )
                    }
                  />
                  {d.file_name}
                </label>
                <p className="mt-1 text-xs text-muted-foreground">
                  Kullanıcı belgesi{d.ocr ? " · OCR ile okundu; aslıyla kontrol edin" : ""}
                </p>
                {d.ready ? (
                  <details className="mt-2 text-sm">
                    <summary className="cursor-pointer">
                      Metinden başlangıç bölümünü göster (özet değildir)
                    </summary>
                    <p className="mt-2 whitespace-pre-wrap break-words">{d.excerpt}</p>
                  </details>
                ) : (
                  <p className="mt-2 text-sm text-muted-foreground">
                    Belge henüz okunabilir durumda değil; özet kapsamına alınmayacak.
                  </p>
                )}
              </article>
            ))}
          </section>
          <section className="space-y-3 rounded-lg border p-4">
            <h3 className="font-semibold">
              {proposal.kind === "hearing"
                ? "Duruşma hazırlığı · belge özeti"
                : "Belgeye dayalı kısa özet"}
            </h3>
            <p className="text-xs text-muted-foreground">
              Yalnız seçtiğiniz okunabilir {selectedReady.length} belge yapılandırılmış AI
              sağlayıcısıyla işlenir. Başlatınca çalışma kaydedilir; görev veya takvim kaydı
              oluşturulmaz.
            </p>
            <Button
              disabled={!selectedReady.length || starting || !!jobId}
              onClick={() => void start()}
            >
              {starting ? "Başlatılıyor…" : jobId ? "Özet işi başlatıldı" : "Özeti oluştur"}
            </Button>
            {jobError && (
              <div role="alert" className="space-y-2 text-sm text-destructive">
                <p>{jobError}</p>
                {jobId && (
                  <Button variant="outline" onClick={() => setRevision((v) => v + 1)}>
                    Durumu yeniden kontrol et
                  </Button>
                )}
              </div>
            )}
            {job && (
              <p role="status" className="text-sm">
                {
                  {
                    queued: "Sırada",
                    running: "İşleniyor",
                    done: "Tamamlandı",
                    partial: "Kısmen tamamlandı",
                    failed: "Başarısız",
                    cancelled: "Durduruldu",
                  }[job.state]
                }{" "}
                · {job.progress.done}/{job.progress.total} belge
              </p>
            )}
            {job?.error && (
              <p role="alert" className="text-sm text-destructive">
                {job.error}
              </p>
            )}
            {job?.state === "partial" && (
              <p className="text-sm text-amber-600">
                Tüm bölümler işlenemedi; çıktıdaki kapsam uyarılarını kontrol edin.
              </p>
            )}
            {job?.output && (
              <div className="prose prose-sm max-w-none break-words dark:prose-invert">
                <ReactMarkdown components={{ img: () => null }}>{job.output}</ReactMarkdown>
              </div>
            )}
            {jobId && (
              <p className="text-xs text-muted-foreground">
                İş kimliği: {jobId}. Kaydedilen çalışmaya Büro Asistanı’ndaki “Belge çalışmaları”
                bölümünden erişebilirsiniz.
              </p>
            )}
          </section>
          <section className="space-y-3 rounded-lg border p-4">
            <h3 className="font-semibold">Dosyayla çalışmaya devam et</h3>
            <p className="text-xs text-muted-foreground">
              Taslak için yukarıdaki seçili belgeler taşınır; yeni iş kendiliğinden başlatılmaz.
              Dava sohbeti ise yalnız seçili belgelerle sınırlı değil, davanın erişilebilir
              kayıtlarıyla çalışır.
            </p>
            <div className="flex flex-wrap gap-3">
              <DocumentWorkflowActions
                ids={selectedReady.map((d) => d.id)}
                caseId={data.proposal.case_id ?? undefined}
                modes={["draft"]}
              />
              {data.proposal.case_id && (
                <Button
                  variant="outline"
                  aria-expanded={showConversation}
                  onClick={() => setShowConversation((value) => !value)}
                >
                  {showConversation ? "Dosya sohbetini gizle" : "Bu dava hakkında sor"}
                </Button>
              )}
            </div>
            {showConversation && data.proposal.case_id && (
              <CaseDocumentAsk key={data.proposal.case_id} caseId={data.proposal.case_id} />
            )}
          </section>
          <section className="space-y-3 rounded-lg border border-primary/20 bg-primary/5 p-4">
            <h3 className="font-semibold">Önerilen işlem</h3>
            <p className="text-sm">{data.suggested_action}</p>
            {data.action_available !== false ? (
              <Button onClick={() => onApprove(data.proposal)}>İşlemi incele ve onayla</Button>
            ) : (
              <p className="text-sm text-muted-foreground">
                Bu tarih için yeni takvim önerisi yok: işlem daha önce yapılmış, öneri kapatılmış
                veya tarih artık öneri aralığında olmayabilir. Hazırlık notunu incelemeye devam
                edebilirsiniz.
              </p>
            )}
            <Link to={proposal.source_url} className="ml-3 text-sm text-primary">
              Dosyayı aç
            </Link>
          </section>
        </>
      )}
    </div>
  );
}

export function BureauWorkHistory() {
  const [open, setOpen] = useState(false);
  const [output, setOutput] = useState("");
  return (
    <section className="space-y-4 rounded-2xl border border-border bg-card p-5">
      <Button variant="outline" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        Belge çalışmaları · {open ? "Gizle" : "Kaydedilen özetleri ve kuyruğu aç"}
      </Button>
      {open && (
        <>
          <p className="text-xs text-muted-foreground">
            Hesabınızdaki son belge özeti işleri. Devam eden işi izleyebilir, durdurabilir veya
            kaydedilen sonucu açabilirsiniz.
          </p>
          <DocumentJobPanel
            module="auto_summary"
            onJobChange={(job) =>
              setOutput(job && ["done", "partial"].includes(job.state) ? (job.output ?? "") : "")
            }
          />
          {output && (
            <div className="prose prose-sm max-w-none break-words dark:prose-invert">
              <ReactMarkdown components={{ img: () => null }}>{output}</ReactMarkdown>
            </div>
          )}
        </>
      )}
    </section>
  );
}

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { CaseDocPicker } from "@/components/CaseDocPicker";
import { FileUploadDialog } from "@/components/FileUploadDialog";
import { DocumentWorkflowActions } from "@/components/DocumentWorkflowActions";
import {
  getProjectDocuments,
  linkProjectDocuments,
  unlinkProjectDocument,
  type ProjectDocumentPage,
  type ProjectDocument,
} from "@/lib/project-documents";
import { Link } from "@/lib/router-compat";
import { toast } from "sonner";
import { Loader2, Plus, RefreshCw, Unlink } from "lucide-react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";

export function ProjectDocuments({ projectId }: { projectId: string }) {
  const { user } = useAuth();
  return <ProjectDocumentsPanel key={`${user?.id}:${projectId}`} projectId={projectId} />;
}

function ProjectDocumentsPanel({ projectId }: { projectId: string }) {
  const [data, setData] = useState<ProjectDocumentPage>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showPicker, setShowPicker] = useState(false);
  const [toLink, setToLink] = useState<string[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [removing, setRemoving] = useState<ProjectDocument>();
  const alive = useRef(true),
    sequence = useRef(0);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const load = useCallback(async () => {
    const current = ++sequence.current;
    setLoading(true);
    setError("");
    try {
      const next = await getProjectDocuments(projectId);
      if (!alive.current || current !== sequence.current) return;
      setData(next);
      setSelected((previous) =>
        previous.filter((id) =>
          next.documents.some((doc) => doc.id === id && doc.status === "ready"),
        ),
      );
    } catch (error) {
      if (alive.current && current === sequence.current) {
        setData(undefined);
        setSelected([]);
        setError(error instanceof Error ? error.message : "Belgeler yüklenemedi.");
      }
    } finally {
      if (alive.current && current === sequence.current) setLoading(false);
    }
  }, [projectId]);
  useEffect(() => {
    void load();
  }, [load]);
  const attach = async () => {
    if (busy || !toLink.length) return;
    setBusy(true);
    try {
      const result = await linkProjectDocuments(projectId, toLink);
      if (!alive.current) return;
      toast.success(
        `${result.linked} belge bağlandı; ${result.already_linked} belge zaten bağlıydı.`,
      );
      setToLink([]);
      setShowPicker(false);
      await load();
    } catch (error) {
      if (alive.current) toast.error(error instanceof Error ? error.message : "Bağlanamadı.");
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  const detach = async () => {
    if (!removing || busy) return;
    setBusy(true);
    try {
      await unlinkProjectDocument(projectId, removing.id);
      if (!alive.current) return;
      toast.success("Yalnız proje bağlantısı kaldırıldı; dosya silinmedi.");
      setRemoving(undefined);
      await load();
    } catch (error) {
      if (alive.current)
        toast.error(error instanceof Error ? error.message : "Bağlantı kaldırılamadı.");
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  const docs = (data?.documents ?? []).filter((doc) =>
    `${doc.file_name} ${doc.doc_type ?? ""} ${doc.uyap_file_no ?? ""}`
      .toLocaleLowerCase("tr-TR")
      .includes(query.toLocaleLowerCase("tr-TR")),
  );
  const ready = docs.filter((doc) => doc.status === "ready");
  return (
    <section className="space-y-4" aria-label="Proje belgeleri">
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => setShowPicker((value) => !value)} disabled={busy}>
          <Plus className="h-4 w-4" />
          Arşivden belge bağla
        </Button>
        <Button variant="outline" onClick={() => void load()} disabled={loading || busy}>
          <RefreshCw className="h-4 w-4" />
          Yenile
        </Button>
        <FileUploadDialog
          projectId={projectId}
          label="Belge yükle"
          onUploaded={() => void load()}
        />
        <Link to="/dashboard/files" className="text-sm text-muted-foreground underline">
          Tüm dosyalar
        </Link>
      </div>
      <p className="text-xs text-muted-foreground">
        Bağlamak dosyayı taşımaz veya çoğaltmaz. Bağlı davanın evrakları da bu projede kullanılır;
        aynı belge yalnız bir kez listelenir.
      </p>
      {showPicker && (
        <div className="rounded-xl border p-3 space-y-3">
          <CaseDocPicker value={toLink} onChange={setToLink} max={2000} />
          <Button onClick={() => void attach()} disabled={busy || !toLink.length}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {toLink.length} belgeyi projeye bağla
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {loading && (
        <p role="status" className="text-sm flex gap-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          Proje belgeleri yükleniyor…
        </p>
      )}
      {data && (
        <>
          <p className="text-sm">
            {data.total} belge · {data.ready} aranabilir · {data.pending} bekliyor ·{" "}
            {data.failed.length} okunamadı
          </p>
          <Input
            aria-label="Proje belgelerinde filtrele"
            placeholder="Belge adı, türü veya dosya numarası…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={loading || busy || !ready.length}
              onClick={() => {
                if (ready.length > 2000)
                  return toast.error("Bir işlemde en fazla 2000 belge seçin.");
                setSelected(ready.map((doc) => doc.id));
              }}
            >
              Filtredeki aranabilirleri seç ({ready.length})
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setSelected([])}>
              Seçimi kaldır
            </Button>
            <DocumentWorkflowActions
              ids={selected}
              officeProjectId={projectId}
              disabled={busy || loading}
            />
          </div>
          <ul className="divide-y rounded-xl border">
            {docs.map((doc) => (
              <li key={doc.id} className="p-3 flex flex-wrap items-center gap-3">
                <Checkbox
                  aria-label={`${doc.file_name} belgesini seç`}
                  checked={selected.includes(doc.id)}
                  disabled={doc.status !== "ready" || busy || loading}
                  onCheckedChange={(checked) => {
                    if (checked && !selected.includes(doc.id) && selected.length >= 2000)
                      return toast.error("Bir işlemde en fazla 2000 belge seçin.");
                    setSelected((previous) =>
                      checked
                        ? [...new Set([...previous, doc.id])]
                        : previous.filter((id) => id !== doc.id),
                    );
                  }}
                />
                <div className="flex-1 min-w-40">
                  <p className="text-sm break-all">{doc.file_name}</p>
                  <p className="text-xs text-muted-foreground">
                    {doc.direct_linked
                      ? doc.case_id === data.case_id && data.case_id
                        ? "Projeye bağlı ve dava üzerinden"
                        : "Projeye doğrudan bağlı"
                      : "Bağlı davadan"}{" "}
                    ·{" "}
                    {doc.status === "ready"
                      ? "Aranabilir"
                      : doc.status === "failed"
                        ? "Okunamadı"
                        : "Metni işleniyor"}
                    {doc.ocr ? " · OCR: aslıyla kontrol edin" : ""}
                  </p>
                  {doc.error && <p className="text-xs text-destructive">{doc.error}</p>}
                </div>
                {doc.direct_linked && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={() => setRemoving(doc)}
                  >
                    <Unlink className="h-4 w-4" />
                    Bağlantıyı kaldır
                  </Button>
                )}
              </li>
            ))}
            {!docs.length && (
              <li className="p-6 text-sm text-muted-foreground">
                {data.total
                  ? "Filtreyle eşleşen belge yok."
                  : "Henüz proje belgesi yok. Arşivden belge bağlayın."}
              </li>
            )}
          </ul>
        </>
      )}
      <AlertDialog
        open={!!removing}
        onOpenChange={(open) => {
          if (!open && !busy) setRemoving(undefined);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Proje bağlantısı kaldırılsın mı?</AlertDialogTitle>
            <AlertDialogDescription>
              {removing?.file_name} dosyası silinmez. Belge bağlı davadan da geliyorsa projede
              görünmeye devam eder.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Vazgeç</AlertDialogCancel>
            <AlertDialogAction
              disabled={busy}
              onClick={(event) => {
                event.preventDefault();
                void detach();
              }}
            >
              Yalnız bağlantıyı kaldır
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}

import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { CaseDetailView } from "@/components/CaseDetailView";
import { CaseDocumentActions } from "@/components/CaseDocumentActions";
import { CaseDocumentAsk } from "@/components/CaseDocumentAsk";
import { CaseDocumentCompare } from "@/components/CaseDocumentCompare";
import { CaseDocumentSummary } from "@/components/CaseDocumentSummary";
import { CaseNotesEditor, CaseTaskComposer } from "@/components/CaseQuickActions";
import { DocumentTrash } from "@/components/DocumentTrash";
import { trashDocument } from "@/lib/document-trash";
import { Button } from "@/components/ui/button";
import { useParams, useSearchParam, Link } from "@/lib/router-compat";
import { loadCaseDetail, type CaseDetailData } from "@/lib/case-detail";
import { db } from "@/lib/db";
import { ArrowLeft, RefreshCw } from "lucide-react";

/** Adresteki "?tab=…" değeri (genel aramadan gelen bağlantı) hangi sekmeyi açar. */
const TAB_BY_PARAM: Record<string, "Evraklar" | "Görevler" | "Notlar" | "Takvim"> = {
  evraklar: "Evraklar",
  gorevler: "Görevler",
  notlar: "Notlar",
  takvim: "Takvim",
};

const CaseDetail = () => {
  const { id } = useParams<{ id: string }>();
  const urlTab = useSearchParam("tab");
  const [result, setResult] = useState<{ id: string; data?: CaseDetailData; error?: string }>();
  const [revision, setRevision] = useState(0);
  const [downloading, setDownloading] = useState<string>();
  const [downloadError, setDownloadError] = useState("");
  const [savedCase, setSavedCase] = useState<string>();
  const [trashing, setTrashing] = useState<string>();
  const [trashKey, setTrashKey] = useState(0);
  const generation = useRef(0);
  const current = result?.id === id ? result : undefined;
  const data = current?.data;

  useEffect(() => {
    let active = true;
    ++generation.current;
    // Aynı davanın yeniden yüklenmesinde (Yenile, çöpe taşıma, belge ekleme) önceki veri ekranda
    // kalır: aksi halde görünüm yeniden kurulur ve açık sekme "Özet"e geri atardı.
    setResult((previous) => (previous?.id === id ? previous : undefined));
    setDownloadError("");
    setDownloading(undefined);
    loadCaseDetail(id)
      .then((data) => {
        if (active) setResult({ id, data });
      })
      .catch((error) => {
        if (active)
          setResult({ id, error: error instanceof Error ? error.message : "Dava yüklenemedi." });
      });
    return () => {
      active = false;
      ++generation.current;
    };
  }, [id, revision]);

  const download = async (documentId: string) => {
    const document = data?.documents.rows.find((row) => row.id === documentId);
    if (!document || downloading) return;
    const version = generation.current;
    setDownloading(documentId);
    setDownloadError("");
    try {
      const response = await db.storage.from("case-files").download(document.storage_path);
      if (version !== generation.current) return;
      if (response.error || !response.data)
        throw new Error(response.error?.message || "Dosya indirilemedi.");
      const url = URL.createObjectURL(response.data);
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = document.file_name;
      window.document.body.appendChild(anchor);
      try {
        anchor.click();
      } finally {
        anchor.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (error) {
      if (version === generation.current)
        setDownloadError(error instanceof Error ? error.message : "Dosya indirilemedi.");
    } finally {
      if (version === generation.current) setDownloading(undefined);
    }
  };

  // Silme iki adımlıdır: belge önce çöp kutusuna taşınır (geri alınabilir, aranmaz).
  const moveToTrash = async (documentId: string) => {
    if (trashing) return;
    setTrashing(documentId);
    setDownloadError("");
    try {
      await trashDocument(documentId);
      setRevision((n) => n + 1);
      setTrashKey((n) => n + 1);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : "Belge çöp kutusuna taşınamadı.");
    } finally {
      setTrashing(undefined);
    }
  };

  return (
    <DashboardLayout
      title={data?.record.title ?? "Dava detayı"}
      subtitle={
        data
          ? `Dosya: ${data.record.case_no || data.record.esas_no || "Numara belirtilmemiş"}`
          : "Kayıtlı dava bilgileri"
      }
      actions={
        <div className="flex gap-2">
          <Link to="/dashboard/cases">
            <Button variant="outline" size="sm">
              <ArrowLeft className="h-4 w-4" />
              Listeye Dön
            </Button>
          </Link>
          <Button
            variant="outline"
            size="sm"
            disabled={!current}
            onClick={() => setRevision((n) => n + 1)}
          >
            <RefreshCw className="h-4 w-4" />
            Yenile
          </Button>
        </div>
      }
    >
      {!current && (
        <p role="status" className="text-sm text-muted-foreground">
          Dava bilgileri yükleniyor…
        </p>
      )}
      {current?.error && (
        <div role="alert" className="rounded-xl border border-destructive p-4 text-destructive">
          {current.error}
        </div>
      )}
      {data && (
        <>
          {savedCase === id && (
            <p role="status" className="mb-3 text-sm">
              Belge davaya kaydedildi. Evrak listesi güncellendi.
            </p>
          )}
          <CaseDetailView
            key={`${id}:${urlTab}`}
            data={data}
            onDownload={download}
            downloading={downloading}
            downloadError={downloadError}
            initialTab={savedCase === id ? "Evraklar" : (TAB_BY_PARAM[urlTab] ?? "Özet")}
            documentAsk={<CaseDocumentAsk key={id} caseId={id} />}
            documentCompare={<CaseDocumentCompare key={id} caseId={id} />}
            caseSummary={<CaseDocumentSummary key={id} caseId={id} />}
            notesEditor={<CaseNotesEditor key={id} caseId={id} initial={data.record.notes} onSaved={() => setRevision((n) => n + 1)} />}
            taskComposer={<CaseTaskComposer key={id} caseId={id} onSaved={() => setRevision((n) => n + 1)} />}
            trashing={trashing}
            onTrash={(documentId) => void moveToTrash(documentId)}
            documentTrash={
              <DocumentTrash
                key={`trash:${id}`}
                caseId={id}
                refreshKey={trashKey}
                onChanged={() => setRevision((n) => n + 1)}
              />
            }
            documentActions={
              <CaseDocumentActions
                key={`actions:${id}`}
                caseId={id}
                clientId={data.record.client_id}
                onSaved={() => {
                  setSavedCase(id);
                  setRevision((n) => n + 1);
                }}
              />
            }
          />
        </>
      )}
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/cases/$id")({
  component: CaseDetail,
});

import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { DocumentTrash } from "@/components/DocumentTrash";
import { FileUploadDialog } from "@/components/FileUploadDialog";
import { UyapSyncDialog } from "@/components/UyapSyncDialog";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { supabase } from "@/integrations/supabase/client";
import { inMemoryAccessToken } from "@/lib/auth-api";
import { restoreDocument, trashDocument } from "@/lib/document-trash";
import { linkCaseDocument } from "@/lib/case-documents";
import { humanSize, isUyapSource } from "@/lib/uyap";
import { toast } from "sonner";
import { Download, FileText, Loader2, RefreshCw, Search, Trash2, FolderSearch, FolderPlus } from "lucide-react";

interface DocRow {
  id: string;
  file_name: string;
  storage_path: string;
  size_bytes: number | null;
  source: string;
  uyap_file_no: string | null;
  uyap_birim: string | null;
  case_id: string | null;
  doc_type: string | null;
  doc_date: string | null;
  created_at: string;
}

interface SyncRow {
  id: string;
  status: string;
  archive_name: string | null;
  found_count: number;
  inserted_count: number;
  skipped_count: number;
  error_message: string | null;
  created_at: string;
}

interface CaseChoice { id: string; title: string; esas_no: string | null; court: string | null }

const Files = () => {
  const pageSize = 50;
  const [docs, setDocs] = useState<DocRow[]>([]);
  const [runs, setRuns] = useState<SyncRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [loadError, setLoadError] = useState("");
  const requestId = useRef(0);
  const [linkingDoc, setLinkingDoc] = useState<DocRow | null>(null);
  const [cases, setCases] = useState<CaseChoice[]>([]);
  const [chosenCaseId, setChosenCaseId] = useState("");
  const [linkError, setLinkError] = useState("");
  const [linkBusy, setLinkBusy] = useState(false);
  const [trashKey, setTrashKey] = useState(0);

  const load = useCallback(async () => {
    const currentRequest = ++requestId.current;
    setLoading(true);
    setLoadError("");
    const query = new URLSearchParams({ q: searchTerm, offset: String(page * pageSize), limit: String(pageSize) });
    const base = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");
    const [documents, r] = await Promise.all([
      fetch(`${base}/api/office/case-documents/search?${query}`, {
        credentials: "include",
        headers: inMemoryAccessToken() ? { Authorization: `Bearer ${inMemoryAccessToken()}` } : {},
      }).then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(body?.detail ?? `Belge listesi yüklenemedi (${response.status})`);
        }
        return response.json() as Promise<{ rows: DocRow[]; total: number }>;
      }).catch((error) => ({ error: error instanceof Error ? error.message : "Belge listesi yüklenemedi" })),
      supabase
        .from("uyap_sync_runs")
        .select(
          "id, status, archive_name, found_count, inserted_count, skipped_count, error_message, created_at",
        )
        .order("created_at", { ascending: false })
        .limit(5),
    ]);
    if (currentRequest !== requestId.current) return;
    if ("error" in documents) {
      setLoadError(documents.error);
      setDocs([]);
      setTotal(0);
    } else if (!Array.isArray(documents.rows) || !Number.isFinite(documents.total)) {
      setLoadError("Belge listesi beklenmeyen biçimde döndü");
      setDocs([]);
      setTotal(0);
    } else {
      setDocs(documents.rows);
      setTotal(documents.total);
    }
    if (r.error) toast.error(r.error.message);
    setRuns((r.data ?? []) as SyncRow[]);
    setLoading(false);
  }, [page, searchTerm]);

  useEffect(() => {
    const timer = window.setTimeout(() => setSearchTerm(q.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [q]);

  useEffect(() => {
    void load();
  }, [load]);

  const download = async (row: DocRow) => {
    const { data, error } = await supabase.storage
      .from("case-files")
      .createSignedUrl(row.storage_path, 60, { download: row.file_name });
    if (error || !data) {
      toast.error("İndirme bağlantısı oluşturulamadı");
      return;
    }
    window.open(data.signedUrl, "_blank", "noopener");
  };

  // Silme iki adımlıdır: önce çöp kutusuna taşınır (geri alınabilir, aranmaz); kalıcı silme çöp
  // kutusundan yapılır. Dosya diskte kalır, yalnız kalıcı silmede kaldırılır.
  const remove = async (row: DocRow) => {
    try {
      await trashDocument(row.id);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Belge çöp kutusuna taşınamadı");
      return;
    }
    toast.success(`"${row.file_name}" çöp kutusuna taşındı`, {
      action: {
        label: "Geri al",
        onClick: () => {
          void restoreDocument(row.id).then(load, () => toast.error("Belge geri alınamadı"));
        },
      },
    });
    setDocs((prev) => prev.filter((d) => d.id !== row.id));
    setTotal((count) => Math.max(0, count - 1));
    setTrashKey((n) => n + 1);
    if (docs.length === 1 && page > 0) setPage((current) => current - 1);
    else void load();
  };

  const openCaseLink = async (row: DocRow) => {
    setLinkingDoc(row);
    setChosenCaseId("");
    setLinkError("");
    const result = await supabase.from("cases")
      .select("id,title,esas_no,court")
      .order("created_at", { ascending: false })
      .limit(1000);
    if (result.error) setLinkError(result.error.message);
    else setCases((result.data ?? []) as CaseChoice[]);
  };

  const saveCaseLink = async () => {
    if (!linkingDoc || !chosenCaseId) return;
    setLinkBusy(true);
    setLinkError("");
    try {
      await linkCaseDocument(chosenCaseId, linkingDoc.id);
      toast.success("Belge davaya bağlandı");
      setLinkingDoc(null);
      void load();
    } catch (error) {
      setLinkError(error instanceof Error ? error.message : "Belge bağlanamadı");
    } finally {
      setLinkBusy(false);
    }
  };

  return (
    <DashboardLayout
      title="Dosyalar"
      subtitle="Belge yükleme ve UYAP benzeri güvenli dosya senkronizasyonu"
      actions={
        <div className="flex items-center gap-2">
          <Button size="sm" variant="ghost" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
          <UyapSyncDialog onSynced={load} />
          <FileUploadDialog onUploaded={load} />
        </div>
      }
    >
      {runs.length > 0 && (
        <div className="mb-6 rounded-2xl border border-border bg-card p-4">
          <h2 className="text-sm font-semibold mb-3">Son senkronizasyonlar</h2>
          <ul className="space-y-2 text-xs">
            {runs.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-2">
                <Badge variant={r.status === "completed" ? "outline" : "destructive"}>
                  {r.status}
                </Badge>
                <span className="font-medium">{r.archive_name ?? "-"}</span>
                <span className="text-muted-foreground">
                  {r.inserted_count} eklendi · {r.skipped_count} atlandı · {r.found_count} bulundu
                </span>
                <span className="text-muted-foreground ml-auto">
                  {new Date(r.created_at).toLocaleString("tr-TR")}
                </span>
                {r.error_message && (
                  <span className="text-destructive w-full">{r.error_message}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mb-6 max-w-md relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <input
          value={q}
          onChange={(e) => { setQ(e.target.value); setPage(0); }}
          placeholder="Tüm belgelerde ad, dosya no, birim veya tür ara..."
          className="w-full h-11 pl-10 pr-4 rounded-lg bg-card border border-border focus:border-primary/50 outline-none text-sm transition"
        />
      </div>

      <div className="rounded-2xl bg-card border border-border overflow-hidden">
        {loading ? (
          <div className="p-10 flex justify-center text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : loadError ? (
          <div className="p-10 text-sm text-destructive" role="alert">{loadError}</div>
        ) : docs.length === 0 ? (
          <div className="p-12 text-center text-sm text-muted-foreground">
            <FolderSearch className="h-8 w-8 mx-auto mb-3 opacity-40" />
            {searchTerm ? "Aramanızla eşleşen belge yok." : "Henüz belge yok. Dosya yükleyin veya UYAP arşivinizi senkronize edin."}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground bg-secondary/40 uppercase tracking-wider">
                  <th className="font-medium px-6 py-4">Belge</th>
                  <th className="font-medium px-6 py-4">Dosya No / Birim</th>
                  <th className="font-medium px-6 py-4">Tür</th>
                  <th className="font-medium px-6 py-4">Kaynak</th>
                  <th className="font-medium px-6 py-4 text-right">İşlem</th>
                </tr>
              </thead>
              <tbody>
            {docs.map((d) => (
                  <tr
                    key={d.id}
                    className="border-t border-border hover:bg-secondary/30 transition"
                  >
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div className="h-9 w-9 rounded-lg bg-secondary flex items-center justify-center shrink-0">
                          <FileText className="h-4 w-4 text-primary" />
                        </div>
                        <div className="min-w-0">
                          <div className="font-medium truncate max-w-[260px]">{d.file_name}</div>
                          <div className="text-xs text-muted-foreground">
                            {humanSize(d.size_bytes)} ·{" "}
                            {new Date(d.created_at).toLocaleDateString("tr-TR")}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="font-mono text-xs">{d.uyap_file_no ?? "-"}</div>
                      <div className="text-xs text-muted-foreground truncate max-w-[220px]">
                        {d.uyap_birim ?? ""}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-xs">
                      {d.doc_type ?? "-"}
                      {d.doc_date && <div className="text-muted-foreground">{d.doc_date}</div>}
                    </td>
                    <td className="px-6 py-4">
                      <Badge
                          variant={isUyapSource(d.source) ? "default" : "outline"}
                        className="text-[10px]"
                      >
                          {isUyapSource(d.source) ? "UYAP" : "Elle"}
                      </Badge>
                    </td>
                    <td className="px-6 py-4 text-right whitespace-nowrap">
                      {!d.case_id && (
                        <Button size="sm" variant="ghost" title="Davaya bağla" aria-label="Davaya bağla" onClick={() => void openCaseLink(d)}>
                          <FolderPlus className="h-4 w-4" />
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" onClick={() => void download(d)}>
                        <Download className="h-4 w-4" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        title="Çöp kutusuna taşı"
                        aria-label="Çöp kutusuna taşı"
                        onClick={() => void remove(d)}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {!loadError && !loading && total > 0 && (
        <div className="mt-3 flex items-center justify-between text-sm text-muted-foreground">
          <span>{total} belgeden {page * pageSize + 1}–{page * pageSize + docs.length} gösteriliyor</span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Önceki</Button>
            <Button size="sm" variant="outline" disabled={(page + 1) * pageSize >= total} onClick={() => setPage((p) => p + 1)}>Sonraki</Button>
          </div>
        </div>
      )}
      <DocumentTrash refreshKey={trashKey} onChanged={() => void load()} />
      <Dialog open={!!linkingDoc} onOpenChange={(open) => { if (!open) setLinkingDoc(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Belgeyi davaya bağla</DialogTitle>
            <DialogDescription>Dosya numarası tek başına güvenilir eşleşme değildir. Doğru davayı ve mahkemeyi sen seç; bundan sonra belge dava kapsamlı AI aramasında kullanılabilir.</DialogDescription>
          </DialogHeader>
          {linkingDoc && <p className="text-sm break-all">{linkingDoc.file_name}</p>}
          <select value={chosenCaseId} onChange={(event) => setChosenCaseId(event.target.value)} className="w-full rounded-md border bg-background p-2 text-sm" aria-label="Dava seç">
            <option value="">Dava seç...</option>
            {cases.map((item) => <option key={item.id} value={item.id}>{item.esas_no ?? "-"} · {item.court ?? "-"} · {item.title}</option>)}
          </select>
          {cases.length === 0 && !linkError && <p className="text-sm text-muted-foreground">Henüz kayıtlı dava yok. Önce <a className="underline" href="/dashboard/cases">Davalar</a> sayfasında dava oluştur.</p>}
          {cases.length === 1000 && <p className="text-sm text-amber-600">İlk 1000 dava gösteriliyor; aradığın dava yoksa dava sayfasından belgeyi bağla.</p>}
          {linkError && <p role="alert" className="text-sm text-destructive">{linkError}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setLinkingDoc(null)}>Vazgeç</Button>
            <Button disabled={!chosenCaseId || linkBusy} onClick={() => void saveCaseLink()}>{linkBusy ? "Bağlanıyor..." : "Davaya bağla"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/files")({
  component: Files,
});

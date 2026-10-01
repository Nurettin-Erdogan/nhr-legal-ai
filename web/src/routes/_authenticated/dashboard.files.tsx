import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { DocumentTrash } from "@/components/DocumentTrash";
import { FileUploadDialog } from "@/components/FileUploadDialog";
import { UyapSyncDialog } from "@/components/UyapSyncDialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { supabase } from "@/integrations/supabase/client";
import { restoreDocument, trashDocument } from "@/lib/document-trash";
import { humanSize } from "@/lib/uyap";
import { toast } from "sonner";
import { Download, FileText, Loader2, RefreshCw, Search, Trash2, FolderSearch } from "lucide-react";

interface DocRow {
  id: string;
  file_name: string;
  storage_path: string;
  size_bytes: number | null;
  source: string;
  uyap_file_no: string | null;
  uyap_birim: string | null;
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

const Files = () => {
  const [docs, setDocs] = useState<DocRow[]>([]);
  const [runs, setRuns] = useState<SyncRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [trashKey, setTrashKey] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    const [d, r] = await Promise.all([
      supabase
        .from("case_documents")
        .select(
          "id, file_name, storage_path, size_bytes, source, uyap_file_no, uyap_birim, doc_type, doc_date, created_at",
        )
        .order("created_at", { ascending: false })
        .limit(200),
      supabase
        .from("uyap_sync_runs")
        .select(
          "id, status, archive_name, found_count, inserted_count, skipped_count, error_message, created_at",
        )
        .order("created_at", { ascending: false })
        .limit(5),
    ]);
    if (d.error) toast.error(d.error.message);
    setDocs((d.data ?? []) as DocRow[]);
    setRuns((r.data ?? []) as SyncRow[]);
    setLoading(false);
  }, []);

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
    setTrashKey((n) => n + 1);
  };

  const filtered = docs.filter((d) => {
    const s = q.trim().toLowerCase();
    if (!s) return true;
    return [d.file_name, d.uyap_file_no, d.uyap_birim, d.doc_type]
      .filter(Boolean)
      .some((v) => v!.toLowerCase().includes(s));
  });

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
          onChange={(e) => setQ(e.target.value)}
          placeholder="Belge adı, dosya no veya birim ara..."
          className="w-full h-11 pl-10 pr-4 rounded-lg bg-card border border-border focus:border-primary/50 outline-none text-sm transition"
        />
      </div>

      <div className="rounded-2xl bg-card border border-border overflow-hidden">
        {loading ? (
          <div className="p-10 flex justify-center text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-12 text-center text-sm text-muted-foreground">
            <FolderSearch className="h-8 w-8 mx-auto mb-3 opacity-40" />
            Henüz belge yok. Dosya yükleyin veya UYAP arşivinizi senkronize edin.
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
                {filtered.map((d) => (
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
                        variant={d.source === "uyap" ? "default" : "outline"}
                        className="text-[10px]"
                      >
                        {d.source === "uyap" ? "UYAP" : "Elle"}
                      </Badge>
                    </td>
                    <td className="px-6 py-4 text-right whitespace-nowrap">
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
      <DocumentTrash refreshKey={trashKey} onChanged={() => void load()} />
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/files")({
  component: Files,
});

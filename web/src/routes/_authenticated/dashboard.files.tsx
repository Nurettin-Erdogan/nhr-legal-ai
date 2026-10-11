import { createFileRoute } from "@tanstack/react-router";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { useSearchParam } from "@/lib/router-compat";
import { DocumentTrash } from "@/components/DocumentTrash";
import { ContentMatchExcerpt } from "@/components/ContentMatchExcerpt";
import { FileUploadDialog } from "@/components/FileUploadDialog";
import { UyapSyncDialog } from "@/components/UyapSyncDialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { supabase } from "@/integrations/supabase/client";
import {
  listFileBrowser,
  loadAllFileBrowserDocuments,
  type FileBrowserDocument as DocRow,
  type FileBrowserFolder as DocumentFolder,
  type FileBrowserCategory as DocumentCategory,
  type ContentSearchCoverage,
  type FileBrowserFilters,
} from "@/lib/file-browser";
import { restoreDocument, trashDocument, trashDocuments } from "@/lib/document-trash";
import { linkCaseDocument } from "@/lib/case-documents";
import { humanSize, isUyapSource } from "@/lib/uyap";
import { toast } from "sonner";
import {
  Download,
  FileText,
  Loader2,
  RefreshCw,
  Search,
  Trash2,
  FolderSearch,
  FolderPlus,
  FolderOpen,
  Folder,
  ChevronDown,
  ChevronRight,
} from "lucide-react";

interface FolderContents {
  rows: DocRow[];
  loading: boolean;
  error?: string;
}

const folderTitle = (folder: DocumentFolder) => {
  if (!folder.file_no && !folder.birim)
    return folder.source === "uyap"
      ? "Dosya bilgisi eksik UYAP belgeleri"
      : "Diğer yüklenen belgeler";
  return `${folder.file_no ?? "Esas numarası eksik"} · ${folder.birim ?? "Birim bilgisi eksik"}`;
};

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

interface CaseChoice {
  id: string;
  title: string;
  esas_no: string | null;
  court: string | null;
}

const Files = () => {
  const [docs, setDocs] = useState<DocRow[]>([]);
  const [runs, setRuns] = useState<SyncRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [searchIn, setSearchIn] = useState<"metadata" | "content">("metadata");
  const [contentCoverage, setContentCoverage] = useState<ContentSearchCoverage | null>(null);
  const [total, setTotal] = useState(0);
  const [loadError, setLoadError] = useState("");
  const [source, setSource] = useState("all");
  const [category, setCategory] = useState("");
  const [folder, setFolder] = useState("");
  const [order, setOrder] = useState("recent");
  const [grouped, setGrouped] = useState(true);
  const [openedFolders, setOpenedFolders] = useState<Set<string>>(() => new Set());
  const [folderContents, setFolderContents] = useState<Record<string, FolderContents>>({});
  const [folders, setFolders] = useState<DocumentFolder[]>([]);
  const [categories, setCategories] = useState<DocumentCategory[]>([]);
  const requestId = useRef(0);
  const listRequest = useRef<AbortController | null>(null);
  const folderRequests = useRef(new Map<string, AbortController>());
  const selectionRequest = useRef<AbortController | null>(null);
  const selectionRequestId = useRef(0);
  const [linkingDoc, setLinkingDoc] = useState<DocRow | null>(null);
  const [cases, setCases] = useState<CaseChoice[]>([]);
  const [chosenCaseId, setChosenCaseId] = useState("");
  const [linkError, setLinkError] = useState("");
  const [linkBusy, setLinkBusy] = useState(false);
  const [trashKey, setTrashKey] = useState(0);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<Set<string>>(() => new Set());
  const [selectingAll, setSelectingAll] = useState(false);
  const [batchTrashBusy, setBatchTrashBusy] = useState(false);
  const [confirmingBatchTrash, setConfirmingBatchTrash] = useState(false);

  const fileBrowserFilters = useMemo<FileBrowserFilters>(
    () => ({
      q: searchIn === "content" && searchTerm.length < 2 ? "" : searchTerm,
      search_in: searchIn,
      source,
      category,
      folder,
      order,
    }),
    [searchTerm, searchIn, source, category, folder, order],
  );

  const load = useCallback(async () => {
    const currentRequest = ++requestId.current;
    listRequest.current?.abort();
    const controller = new AbortController();
    listRequest.current = controller;
    for (const request of folderRequests.current.values()) request.abort();
    folderRequests.current.clear();
    setFolderContents({});
    setLoading(true);
    setLoadError("");
    const [documents, r] = await Promise.all([
      (grouped
        ? listFileBrowser(fileBrowserFilters, controller.signal, true)
        : loadAllFileBrowserDocuments(fileBrowserFilters, controller.signal)
      ).catch((error) => ({
        error: error instanceof Error ? error.message : "Belge listesi yüklenemedi",
      })),
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
      setContentCoverage(null);
      setLoadError(documents.error);
      setDocs([]);
      setTotal(0);
      setFolders([]);
      setCategories([]);
    } else if (
      !Array.isArray(documents.rows) ||
      !Number.isFinite(documents.total) ||
      !Array.isArray(documents.folders) ||
      !Array.isArray(documents.categories)
    ) {
      setLoadError("Belge listesi beklenmeyen biçimde döndü");
      setContentCoverage(null);
      setDocs([]);
      setTotal(0);
      setFolders([]);
      setCategories([]);
    } else {
      setDocs(documents.rows);
      setTotal(documents.total);
      setFolders(documents.folders);
      setCategories(documents.categories);
      setContentCoverage(documents.content_coverage ?? null);
      if (searchIn === "content" && searchTerm.length >= 2)
        setOpenedFolders(
          new Set(
            documents.folders.filter((item) => item.matching_count > 0).map((item) => item.key),
          ),
        );
    }
    if (r.error) toast.error(r.error.message);
    setRuns((r.data ?? []) as SyncRow[]);
    setLoading(false);
  }, [grouped, fileBrowserFilters]);

  const documentGroups = useMemo(() => {
    if (!grouped) return [{ key: "all", folder: undefined, docs }];
    return folders
      .filter((item) => item.matching_count > 0)
      .map((item) => ({
        key: item.key,
        folder: item,
        docs: folderContents[item.key]?.rows ?? [],
      }));
  }, [docs, folders, grouped, folderContents]);

  const loadFolder = useCallback(
    async (key: string) => {
      if (folderRequests.current.has(key)) return;
      const controller = new AbortController();
      folderRequests.current.set(key, controller);
      const generation = requestId.current;
      setFolderContents((previous) => ({ ...previous, [key]: { rows: [], loading: true } }));
      try {
        const result = await loadAllFileBrowserDocuments(
          { ...fileBrowserFilters, folder: key },
          controller.signal,
        );
        if (generation === requestId.current && !controller.signal.aborted)
          setFolderContents((previous) => ({
            ...previous,
            [key]: { rows: result.rows, loading: false },
          }));
      } catch (error) {
        if (generation === requestId.current && !controller.signal.aborted)
          setFolderContents((previous) => ({
            ...previous,
            [key]: {
              rows: [],
              loading: false,
              error: error instanceof Error ? error.message : "Klasör yüklenemedi",
            },
          }));
      } finally {
        if (folderRequests.current.get(key) === controller) folderRequests.current.delete(key);
      }
    },
    [fileBrowserFilters],
  );

  useEffect(() => {
    if (!grouped || loading || loadError) return;
    for (const group of documentGroups)
      if (openedFolders.has(group.key) && !folderContents[group.key]) void loadFolder(group.key);
  }, [documentGroups, openedFolders, folderContents, grouped, loading, loadError, loadFolder]);

  useEffect(
    () => () => {
      listRequest.current?.abort();
      selectionRequest.current?.abort();
      for (const request of folderRequests.current.values()) request.abort();
      requestId.current++;
    },
    [],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => setSearchTerm(q.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [q]);

  // Üst çubuktaki genel aramadan gelen belge adı ("?q=…") arama kutusuna yazılır.
  const urlQuery = useSearchParam("q");
  useEffect(() => {
    if (urlQuery.trim()) setQ(urlQuery);
  }, [urlQuery]);

  useEffect(() => {
    void load();
  }, [load]);

  // Seçim yalnız mevcut arama/filtre sonucu içindir. Filtre değiştiğinde eski görünmeyen
  // belgeleri yanlışlıkla toplu silmeye katmamak için temizlenir.
  useEffect(() => {
    selectionRequest.current?.abort();
    selectionRequest.current = null;
    selectionRequestId.current++;
    setSelectedDocumentIds(new Set());
  }, [fileBrowserFilters]);

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
    setSelectedDocumentIds((previous) => {
      const next = new Set(previous);
      next.delete(row.id);
      return next;
    });
    setTotal((count) => Math.max(0, count - 1));
    setTrashKey((n) => n + 1);
    void load();
  };

  const openCaseLink = async (row: DocRow) => {
    setLinkingDoc(row);
    setChosenCaseId("");
    setLinkError("");
    const result = await supabase
      .from("cases")
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

  const toggleDocumentSelection = (documentId: string) => {
    setSelectedDocumentIds((previous) => {
      const next = new Set(previous);
      if (next.has(documentId)) next.delete(documentId);
      else next.add(documentId);
      return next;
    });
  };

  const selectAllFiltered = async () => {
    if (!total) return;
    const currentRequest = ++selectionRequestId.current;
    selectionRequest.current?.abort();
    const controller = new AbortController();
    selectionRequest.current = controller;
    setSelectingAll(true);
    try {
      const result = await loadAllFileBrowserDocuments(fileBrowserFilters, controller.signal);
      if (currentRequest !== selectionRequestId.current || controller.signal.aborted) return;
      setSelectedDocumentIds(new Set(result.rows.map((item) => item.id)));
    } catch (error) {
      if (currentRequest === selectionRequestId.current && !controller.signal.aborted)
        toast.error(error instanceof Error ? error.message : "Belgeler seçilemedi");
    } finally {
      if (currentRequest === selectionRequestId.current) setSelectingAll(false);
      if (selectionRequest.current === controller) selectionRequest.current = null;
    }
  };

  const moveSelectedToTrash = async () => {
    const ids = [...selectedDocumentIds];
    if (!ids.length) return;
    setBatchTrashBusy(true);
    try {
      // Sunucuda tek bir isteğin limiti vardır. Büyük arşivler de seçilebilsin diye
      // küçük, sıralı gruplar kullanılır; her grup RLS ve denetim kaydından geçer.
      let moved = 0;
      let unavailable = 0;
      for (let index = 0; index < ids.length; index += 500) {
        const result = await trashDocuments(ids.slice(index, index + 500));
        moved += result.trashed;
        unavailable += result.not_found;
      }
      if (moved) {
        toast.success(`${moved} belge çöp kutusuna taşındı. 30 gün içinde geri alabilirsin.`);
        setTrashKey((value) => value + 1);
      }
      if (unavailable) toast.warning(`${unavailable} belge artık aktif listede değildi.`);
      setSelectedDocumentIds(new Set());
      setConfirmingBatchTrash(false);
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Belgeler çöp kutusuna taşınamadı");
    } finally {
      setBatchTrashBusy(false);
    }
  };

  return (
    <DashboardLayout
      title="Dosyalar"
      subtitle="UYAP ve yüklenen belgeler · dava dosyaları, evrak türleri ve tarihler"
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

      <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="Arama kapsamı">
        <Button
          size="sm"
          variant={searchIn === "metadata" ? "default" : "outline"}
          aria-pressed={searchIn === "metadata"}
          onClick={() => setSearchIn("metadata")}
        >
          Belge adı ve dosya bilgileri
        </Button>
        <Button
          size="sm"
          variant={searchIn === "content" ? "default" : "outline"}
          aria-pressed={searchIn === "content"}
          onClick={() => setSearchIn("content")}
        >
          Belge içeriğinde ara
        </Button>
      </div>
      <div className="mb-3 max-w-lg relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <input
          value={q}
          aria-label={searchIn === "content" ? "Belge içeriğinde ara" : "Belgelerde ara"}
          maxLength={100}
          onChange={(e) => {
            setQ(e.target.value);
          }}
          placeholder={
            searchIn === "content"
              ? "Belgede geçen kelime veya ifadeyi yaz…"
              : "Tüm belgelerde ad, dosya no, birim veya tür ara..."
          }
          className="w-full h-11 pl-10 pr-4 rounded-lg bg-card border border-border focus:border-primary/50 outline-none text-sm transition"
        />
      </div>

      {searchIn === "content" && (
        <div
          className="mb-4 rounded-lg border border-border bg-card p-3 text-xs space-y-2"
          aria-live="polite"
        >
          <p>
            En az 2 karakter yazın. Yazdığınız ifade, işlenmiş belgelerin tüm metin parçalarında
            aranır; büyük/küçük harf ve satır sonları dikkate alınmaz. Her belgenin ilk eşleşmesi
            gösterilir. Bu bir AI yorumu değildir.
          </p>
          {contentCoverage && !loading && !loadError && (
            <>
              <p>
                {contentCoverage.total} belgenin {contentCoverage.ready} tanesi içerikten aranabilir
                · {total} belge listelendi.
              </p>
              {contentCoverage.ready < contentCoverage.total && (
                <p className="text-amber-600 dark:text-amber-400">
                  {contentCoverage.pending} işleniyor / OCR bekliyor / henüz işlenmedi ·{" "}
                  {contentCoverage.failed} okunamadı. Bu belgelerin içeriği sonuçlara dahil
                  değildir; sonuç bulunmaması tüm arşivde olmadığı anlamına gelmez.
                </p>
              )}
            </>
          )}
        </div>
      )}

      <div className="mb-6 rounded-2xl border border-border bg-card p-4 space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          {[
            ["all", "Tüm belgeler"],
            ["uyap", "UYAP belgeleri"],
            ["manual", "Diğer yüklenenler"],
          ].map(([value, label]) => (
            <Button
              key={value}
              size="sm"
              variant={source === value ? "default" : "outline"}
              aria-pressed={source === value}
              onClick={() => {
                setSource(value);
                setFolder("");
                setCategory("");
              }}
            >
              {label}
            </Button>
          ))}
          <div className="flex gap-2 ml-auto">
            <Button
              size="sm"
              variant={grouped ? "default" : "outline"}
              aria-pressed={grouped}
              onClick={() => setGrouped(true)}
            >
              <FolderOpen className="h-4 w-4 mr-1" />
              Dosyaya göre
            </Button>
            <Button
              size="sm"
              variant={!grouped ? "default" : "outline"}
              aria-pressed={!grouped}
              onClick={() => setGrouped(false)}
            >
              Düz liste
            </Button>
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-[2fr_1fr_1fr]">
          <label className="text-xs text-muted-foreground space-y-1 block">
            <span>Dava dosyası / birim</span>
            <select
              aria-label="Dava dosyası / birim"
              value={folder}
              onChange={(event) => {
                setFolder(event.target.value);
              }}
              className="block w-full min-w-0 rounded-lg border border-border bg-background p-2 text-sm text-foreground"
            >
              <option value="">Tüm dosyalar</option>
              {folder && !folders.some((item) => item.key === folder) && (
                <option value={folder}>Seçili dosya (eşleşen belge yok)</option>
              )}
              {folders.map((item) => (
                <option key={item.key} value={item.key}>
                  {folderTitle(item)} ({item.count})
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-muted-foreground space-y-1 block">
            <span>Evrak kategorisi</span>
            <select
              aria-label="Evrak kategorisi"
              value={category}
              onChange={(event) => {
                setCategory(event.target.value);
              }}
              className="block w-full rounded-lg border border-border bg-background p-2 text-sm text-foreground"
            >
              <option value="">Tüm kategoriler</option>
              {category && !categories.some((item) => item.id === category) && (
                <option value={category}>Seçili kategori (eşleşen belge yok)</option>
              )}
              {categories.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label} ({item.count})
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-muted-foreground space-y-1 block">
            <span>Sıralama</span>
            <select
              aria-label="Sıralama"
              value={order}
              onChange={(event) => {
                setOrder(event.target.value);
              }}
              className="block w-full rounded-lg border border-border bg-background p-2 text-sm text-foreground"
            >
              <option value="recent">Son yüklenen</option>
              <option value="date_desc">Kayıtlı evrak tarihi: yeni → eski</option>
              <option value="date_asc">Kayıtlı evrak tarihi: eski → yeni</option>
            </select>
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <p className="flex-1">
            Kategoriler kayıtlı evrak türüne, tür yoksa dosya adına göre otomatik belirlenir. Tarih
            sıralaması aktarımda kaydedilen tarihi kullanır. Seçimlerdeki sayılar arama ve kaynak
            filtresine uyan belgeleri gösterir.
          </p>
          {(q || source !== "all" || folder || category) && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setQ("");
                setSearchTerm("");
                setSource("all");
                setFolder("");
                setCategory("");
              }}
            >
              Filtreleri temizle
            </Button>
          )}
        </div>
      </div>

      <div className="rounded-2xl bg-card border border-border overflow-hidden">
        {!loading && !loadError && total > 0 && (
          <div
            className="flex flex-wrap items-center gap-2 border-b border-border bg-secondary/20 px-4 py-3"
            aria-label="Belge toplu işlemleri"
          >
            <span className="mr-auto text-sm font-medium">
              {selectedDocumentIds.size ? `${selectedDocumentIds.size} belge seçili` : "Belge seç"}
            </span>
            <Button
              size="sm"
              variant="outline"
              disabled={selectingAll || selectedDocumentIds.size === total}
              onClick={() => void selectAllFiltered()}
            >
              {selectingAll ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
              Tümünü seç ({total})
            </Button>
            {selectedDocumentIds.size > 0 && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={batchTrashBusy}
                  onClick={() => setSelectedDocumentIds(new Set())}
                >
                  Seçimi kaldır
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={batchTrashBusy}
                  onClick={() => setConfirmingBatchTrash(true)}
                >
                  <Trash2 className="mr-1 h-4 w-4" />
                  Seçilenleri sil
                </Button>
              </>
            )}
          </div>
        )}
        {loading ? (
          <div className="p-10 flex justify-center text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : loadError ? (
          <div className="p-10 text-sm text-destructive" role="alert">
            {loadError}
          </div>
        ) : total === 0 ? (
          <div className="p-12 text-center text-sm text-muted-foreground">
            <FolderSearch className="h-8 w-8 mx-auto mb-3 opacity-40" />
            {searchTerm || source !== "all" || folder || category
              ? "Seçtiğiniz filtrelerle eşleşen belge yok."
              : "Henüz belge yok. Dosya yükleyin veya UYAP arşivinizi senkronize edin."}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground bg-secondary/40 uppercase tracking-wider">
                  <th className="font-medium px-6 py-4">Belge</th>
                  <th className="font-medium px-6 py-4">Dosya No / Birim</th>
                  <th className="font-medium px-6 py-4">Kategori / Tür</th>
                  <th className="font-medium px-6 py-4">Kaynak</th>
                  <th className="font-medium px-6 py-4 text-right">İşlem</th>
                </tr>
              </thead>
              <tbody>
                {documentGroups.map((group) => (
                  <Fragment key={group.key}>
                    {grouped && group.folder && (
                      <tr className="border-t border-border bg-secondary/50">
                        <th
                          colSpan={5}
                          scope="colgroup"
                          className="px-6 py-3 text-left font-medium"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <button
                              type="button"
                              className="flex min-w-0 flex-1 flex-wrap items-center gap-2 rounded-md text-left hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                              aria-expanded={openedFolders.has(group.key)}
                              aria-label={`Klasör: ${folderTitle(group.folder)}`}
                              title={openedFolders.has(group.key) ? "Klasörü kapat" : "Klasörü aç"}
                              onClick={() =>
                                setOpenedFolders((previous) => {
                                  const next = new Set(previous);
                                  if (next.has(group.key)) next.delete(group.key);
                                  else next.add(group.key);
                                  return next;
                                })
                              }
                            >
                              {!openedFolders.has(group.key) ? (
                                <>
                                  <ChevronRight className="h-4 w-4 shrink-0" />
                                  <Folder className="h-4 w-4 shrink-0 text-primary" />
                                </>
                              ) : (
                                <>
                                  <ChevronDown className="h-4 w-4 shrink-0" />
                                  <FolderOpen className="h-4 w-4 shrink-0 text-primary" />
                                </>
                              )}
                              <span className="break-words">{folderTitle(group.folder)}</span>
                              <span className="text-xs text-muted-foreground font-normal">
                                {group.folder.matching_count} belge
                              </span>
                            </button>
                            {folder !== group.key && (
                              <Button
                                size="sm"
                                variant="ghost"
                                className="ml-auto"
                                onClick={() => {
                                  setFolder(group.key);
                                  setOpenedFolders((previous) => new Set(previous).add(group.key));
                                }}
                              >
                                Bu dosyayı göster
                              </Button>
                            )}
                          </div>
                        </th>
                      </tr>
                    )}
                    {grouped &&
                      openedFolders.has(group.key) &&
                      folderContents[group.key]?.loading && (
                        <tr>
                          <td colSpan={5} className="px-6 py-5 text-sm text-muted-foreground">
                            <span role="status" className="flex items-center gap-2">
                              <Loader2 className="h-4 w-4 animate-spin" />
                              Belgeler yükleniyor…
                            </span>
                          </td>
                        </tr>
                      )}
                    {grouped &&
                      openedFolders.has(group.key) &&
                      folderContents[group.key]?.error && (
                        <tr>
                          <td colSpan={5} className="px-6 py-4">
                            <div className="flex items-center gap-3">
                              <span role="alert" className="text-sm text-destructive">
                                {folderContents[group.key].error}
                              </span>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => void loadFolder(group.key)}
                              >
                                Yeniden dene
                              </Button>
                            </div>
                          </td>
                        </tr>
                      )}
                    {(!grouped || openedFolders.has(group.key)) &&
                      group.docs.map((d) => (
                        <tr
                          key={d.id}
                          className="border-t border-border hover:bg-secondary/30 transition"
                        >
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-3">
                              <input
                                type="checkbox"
                                className="h-4 w-4 shrink-0 accent-primary"
                                aria-label={`${d.file_name} belgesini seç`}
                                checked={selectedDocumentIds.has(d.id)}
                                onChange={() => toggleDocumentSelection(d.id)}
                              />
                              <div className="h-9 w-9 rounded-lg bg-secondary flex items-center justify-center shrink-0">
                                <FileText className="h-4 w-4 text-primary" />
                              </div>
                              <div className="min-w-0">
                                <div
                                  className="font-medium truncate max-w-[260px]"
                                  title={d.file_name}
                                >
                                  {d.file_name.replace(/^[a-f0-9]{12,64}[-_]/i, "")}
                                </div>
                                <div className="text-xs text-muted-foreground">
                                  {humanSize(d.size_bytes)} ·{" "}
                                  {new Date(d.created_at).toLocaleDateString("tr-TR")}
                                </div>
                                {searchIn === "content" && (
                                  <ContentMatchExcerpt match={d.content_match} />
                                )}
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
                            <Badge variant="outline" className="mb-1 whitespace-nowrap">
                              {categories.find((item) => item.id === d.category)?.label ??
                                "Diğer / türü belirsiz"}
                            </Badge>
                            <div>{d.doc_type ?? "Tür bilgisi yok"}</div>
                            {d.doc_date && (
                              <div className="text-muted-foreground">{d.doc_date}</div>
                            )}
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
                              <Button
                                size="sm"
                                variant="ghost"
                                title="Davaya bağla"
                                aria-label="Davaya bağla"
                                onClick={() => void openCaseLink(d)}
                              >
                                <FolderPlus className="h-4 w-4" />
                              </Button>
                            )}
                            <Button
                              size="sm"
                              variant="ghost"
                              title="Belgeyi indir"
                              aria-label="Belgeyi indir"
                              onClick={() => void download(d)}
                            >
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
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <DocumentTrash refreshKey={trashKey} onChanged={() => void load()} />
      <AlertDialog
        open={confirmingBatchTrash}
        onOpenChange={(open) => {
          if (!batchTrashBusy) setConfirmingBatchTrash(open);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {selectedDocumentIds.size} belge çöp kutusuna taşınsın mı?
            </AlertDialogTitle>
            <AlertDialogDescription>
              Belgeler arama ve dosya listesinden kaldırılır; 30 gün boyunca çöp kutusundan geri
              alınabilir. Kalıcı silme yapılmaz.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={batchTrashBusy}>Vazgeç</AlertDialogCancel>
            <AlertDialogAction
              disabled={batchTrashBusy || selectedDocumentIds.size === 0}
              onClick={(event) => {
                event.preventDefault();
                void moveSelectedToTrash();
              }}
            >
              {batchTrashBusy ? "Taşınıyor…" : "Çöp kutusuna taşı"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <Dialog
        open={!!linkingDoc}
        onOpenChange={(open) => {
          if (!open) setLinkingDoc(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Belgeyi davaya bağla</DialogTitle>
            <DialogDescription>
              Dosya numarası tek başına güvenilir eşleşme değildir. Doğru davayı ve mahkemeyi sen
              seç; bundan sonra belge dava kapsamlı AI aramasında kullanılabilir.
            </DialogDescription>
          </DialogHeader>
          {linkingDoc && <p className="text-sm break-all">{linkingDoc.file_name}</p>}
          <select
            value={chosenCaseId}
            onChange={(event) => setChosenCaseId(event.target.value)}
            className="w-full rounded-md border bg-background p-2 text-sm"
            aria-label="Dava seç"
          >
            <option value="">Dava seç...</option>
            {cases.map((item) => (
              <option key={item.id} value={item.id}>
                {item.esas_no ?? "-"} · {item.court ?? "-"} · {item.title}
              </option>
            ))}
          </select>
          {cases.length === 0 && !linkError && (
            <p className="text-sm text-muted-foreground">
              Henüz kayıtlı dava yok. Önce{" "}
              <a className="underline" href="/dashboard/cases">
                Davalar
              </a>{" "}
              sayfasında dava oluştur.
            </p>
          )}
          {cases.length === 1000 && (
            <p className="text-sm text-amber-600">
              İlk 1000 dava gösteriliyor; aradığın dava yoksa dava sayfasından belgeyi bağla.
            </p>
          )}
          {linkError && (
            <p role="alert" className="text-sm text-destructive">
              {linkError}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setLinkingDoc(null)}>
              Vazgeç
            </Button>
            <Button disabled={!chosenCaseId || linkBusy} onClick={() => void saveCaseLink()}>
              {linkBusy ? "Bağlanıyor..." : "Davaya bağla"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/files")({
  component: Files,
});

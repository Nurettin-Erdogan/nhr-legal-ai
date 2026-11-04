import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { useAuth } from "@/components/AuthContext";
import { FolderOpen, Loader2, RefreshCw } from "lucide-react";
import { docSourceLabel, docTextNote, type DocTextState } from "@/lib/case-doc-text";
import { getDocumentPickerPage } from "@/lib/document-picker";

export interface CaseDocRow {
  id: string;
  file_name: string;
  uyap_file_no: string | null;
  uyap_birim: string | null;
  doc_date: string | null;
  source: string;
  text_state: DocTextState;
}

interface Props {
  value: string[];
  onChange: (ids: string[]) => void;
  /** Kaç belge seçilebilir (varsayılan: sınırsız) */
  max?: number;
  caseId?: string;
  officeProjectId?: string;
}

/** UYAP / dosya deposundan AI'ya bağlam olarak verilecek belgeleri seçme paneli. */
export const CaseDocPicker = ({
  value,
  onChange,
  max = Infinity,
  caseId,
  officeProjectId,
}: Props) => {
  const { user } = useAuth();
  const ownerId = user?.id;
  const scope = `${ownerId ?? ""}:${caseId ?? ""}:${officeProjectId ?? ""}`;
  const [loadedScope, setLoadedScope] = useState("");
  const [docs, setDocs] = useState<CaseDocRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(0);

  const load = useCallback(
    async (quiet = false) => {
      const current = ++requestId.current;
      if (!ownerId) {
        setDocs([]);
        setLoadedScope("");
        setLoading(false);
        return;
      }
      if (!quiet) setLoading(true);
      setError("");
      try {
        const page = await getDocumentPickerPage({
          caseId,
          projectId: officeProjectId,
          query,
          offset,
        });
        if (current !== requestId.current) return;
        setLoadedScope(scope);
        setDocs(page.documents);
        setHasMore(page.has_more);
      } catch (error) {
        if (current === requestId.current) {
          setError(error instanceof Error ? error.message : "Belge listesi yüklenemedi.");
          setDocs([]);
        }
      } finally {
        if (current === requestId.current) setLoading(false);
      }
    },
    [caseId, scope, ownerId, officeProjectId, query, offset],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(q.trim());
      setOffset(0);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [q, scope]);

  useEffect(() => {
    load();
    const requests = requestId;
    return () => {
      ++requests.current;
    };
  }, [load]);

  // Yeni yüklenen belgenin metni arka planda okunur; okuma bitene kadar liste sessizce yenilenir.
  const scopedDocs = loadedScope === scope ? docs : [];
  const reading = scopedDocs.some((d) => d.text_state === "reading");
  useEffect(() => {
    if (!reading || loading) return;
    const timer = window.setTimeout(() => {
      if (document.visibilityState === "visible") void load(true);
    }, 10000);
    return () => window.clearTimeout(timer);
  }, [reading, docs, load, loading]);

  const toggle = (id: string) => {
    if (value.includes(id)) onChange(value.filter((v) => v !== id));
    else if (value.length >= max) return;
    else onChange([...value, id]);
  };

  const filtered = scopedDocs;

  const allSelected = filtered.length > 0 && filtered.every((d) => value.includes(d.id));

  return (
    <div className="space-y-2 rounded-lg border p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <FolderOpen className="h-4 w-4 text-primary" />
          {officeProjectId
            ? "Bu projenin belgeleri"
            : caseId
              ? "Bu dosyanın belgeleri"
              : "Kayıtlı belgeler"}
          {value.length > 0 && <Badge variant="secondary">{value.length} seçili</Badge>}
        </div>
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              onChange(
                allSelected
                  ? value.filter((id) => !filtered.some((doc) => doc.id === id))
                  : [...new Set([...value, ...filtered.map((d) => d.id)])].slice(
                      0,
                      Number.isFinite(max) ? max : undefined,
                    ),
              )
            }
            disabled={loading || filtered.length === 0}
          >
            {allSelected ? "Bu sayfanın seçimini kaldır" : "Bu sayfayı seç"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => load()}
            disabled={loading}
            aria-label="Listeyi yenile"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Seçtiğiniz belgelerin okunabilen metni kullanılır
        {Number.isFinite(max) ? ` (en fazla ${max} belge)` : ""}.
        {max > 40
          ? " Arka plan kuyruğu metnin tüm bölümlerini sırayla işler. Tamamlanamayan bölümler sonuçta ayrıca gösterilir."
          : " İlgili pasajlar soru kapsamına göre getirilir; seçmek tüm belgeyi okundu yapmaz."}
      </p>
      <Input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Belge ara (ad, dosya no, birim)"
        className="h-8"
      />

      <div className="max-h-56 space-y-1 overflow-y-auto">
        {error && (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        )}
        {loading && (
          <p role="status" className="text-xs text-muted-foreground">
            Belgeler yükleniyor…
          </p>
        )}
        {!loading && !error && filtered.length === 0 && (
          <p className="py-4 text-center text-xs text-muted-foreground">
            Belge bulunamadı. UYAP'a Bağlan sayfasından belge aktarabilirsiniz.
          </p>
        )}
        {filtered.map((d) => (
          <label
            key={d.id}
            className="flex cursor-pointer items-start gap-2 rounded-md p-2 text-xs hover:bg-muted/50"
          >
            <Checkbox
              checked={value.includes(d.id)}
              onCheckedChange={() => toggle(d.id)}
              className="mt-0.5"
            />
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{d.file_name}</span>
              <span className="text-muted-foreground">
                {[d.uyap_file_no, d.uyap_birim, d.doc_date].filter(Boolean).join(" • ") ||
                  docSourceLabel(d.source)}
                {d.text_state !== "ready" && ` • ${docTextNote(d.text_state)}`}
              </span>
            </span>
          </label>
        ))}
      </div>
      <div className="flex items-center justify-between gap-2 text-xs">
        <Button
          size="sm"
          variant="outline"
          disabled={loading || offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          Önceki
        </Button>
        <span>Sayfa {Math.floor(offset / 50) + 1} · Arama bütün belgelerde yapılır</span>
        <Button
          size="sm"
          variant="outline"
          disabled={loading || !hasMore}
          onClick={() => setOffset(offset + 50)}
        >
          Sonraki
        </Button>
      </div>
    </div>
  );
};

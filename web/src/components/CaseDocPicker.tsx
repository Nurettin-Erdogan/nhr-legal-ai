import { useCallback, useEffect, useRef, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { useAuth } from "@/components/AuthProvider";
import { FolderOpen, Loader2, RefreshCw } from "lucide-react";
import { docSourceLabel, docTextNote, docTextState, type DocTextState } from "@/lib/case-doc-text";
import { getProjectDocuments } from "@/lib/project-documents";

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
        if (officeProjectId) {
          const result = await getProjectDocuments(officeProjectId);
          if (current !== requestId.current) return;
          setLoadedScope(scope);
          setDocs(
            result.documents.map((doc) => ({
              ...doc,
              text_state:
                doc.status === "ready" ? "ready" : doc.status === "failed" ? "none" : "reading",
            })),
          );
          return;
        }
        const data: Array<Record<string, unknown>> = [];
        for (let offset = 0; ; offset += 1000) {
          let query = supabase
            .from("case_documents")
            .select(
              "id, file_name, uyap_file_no, uyap_birim, doc_date, source, content_excerpt, created_at",
            )
            .order("created_at", { ascending: false })
            .order("id", { ascending: false });
          if (caseId) query = query.eq("case_id", caseId);
          const result = await query.range(offset, offset + 999);
          if (current !== requestId.current) return;
          if (result.error) throw new Error(result.error.message);
          if (!Array.isArray(result.data)) throw new Error("Belge listesi yüklenemedi.");
          data.push(...result.data);
          if (result.data.length < 1000) break;
        }
        setLoadedScope(scope);
        setDocs(
          data.map((d) => ({
            id: d.id as string,
            file_name: d.file_name as string,
            uyap_file_no: (d.uyap_file_no as string | null) ?? null,
            uyap_birim: (d.uyap_birim as string | null) ?? null,
            doc_date: (d.doc_date as string | null) ?? null,
            source: (d.source as string) ?? "manual",
            text_state: docTextState(
              d.content_excerpt as string | null,
              d.created_at as string | null,
            ),
          })),
        );
      } catch (error) {
        if (current === requestId.current) {
          setError(error instanceof Error ? error.message : "Belge listesi yüklenemedi.");
          setDocs([]);
        }
      } finally {
        if (current === requestId.current) setLoading(false);
      }
    },
    [caseId, scope, ownerId, officeProjectId],
  );

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
    if (!reading) return;
    const timer = window.setTimeout(() => load(true), 4000);
    return () => window.clearTimeout(timer);
  }, [reading, docs, load]);

  const toggle = (id: string) => {
    if (value.includes(id)) onChange(value.filter((v) => v !== id));
    else if (value.length >= max) return;
    else onChange([...value, id]);
  };

  const filtered = q.trim()
    ? scopedDocs.filter((d) =>
        `${d.file_name} ${d.uyap_file_no ?? ""} ${d.uyap_birim ?? ""}`
          .toLowerCase()
          .includes(q.trim().toLowerCase()),
      )
    : scopedDocs;

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
                  ? []
                  : [...new Set([...value, ...filtered.map((d) => d.id)])].slice(
                      0,
                      Number.isFinite(max) ? max : undefined,
                    ),
              )
            }
            disabled={loading || filtered.length === 0}
          >
            {allSelected ? "Seçimi temizle" : "Tümünü seç"}
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
    </div>
  );
};

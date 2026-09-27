import { useEffect, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { FolderOpen, Loader2, RefreshCw } from "lucide-react";

export interface CaseDocRow {
  id: string;
  file_name: string;
  uyap_file_no: string | null;
  uyap_birim: string | null;
  doc_date: string | null;
  source: string;
  has_text: boolean;
}

interface Props {
  value: string[];
  onChange: (ids: string[]) => void;
  /** Kaç belge seçilebilir (varsayılan: sınırsız) */
  max?: number;
}

/** UYAP / dosya deposundan AI'ya bağlam olarak verilecek belgeleri seçme paneli. */
export const CaseDocPicker = ({ value, onChange, max = Infinity }: Props) => {
  const [docs, setDocs] = useState<CaseDocRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState("");

  const load = async () => {
    setLoading(true);
    const { data } = await supabase
      .from("case_documents")
      .select("id, file_name, uyap_file_no, uyap_birim, doc_date, source, content_excerpt")
      .order("created_at", { ascending: false })
      .limit(1000);
    setDocs(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (data ?? []).map((d: any) => ({
        id: d.id as string,
        file_name: d.file_name as string,
        uyap_file_no: (d.uyap_file_no as string | null) ?? null,
        uyap_birim: (d.uyap_birim as string | null) ?? null,
        doc_date: (d.doc_date as string | null) ?? null,
        source: (d.source as string) ?? "manual",
        has_text: Boolean(d.content_excerpt),
      })),
    );
    setLoading(false);
  };

  useEffect(() => {
    load();
  }, []);

  const toggle = (id: string) => {
    if (value.includes(id)) onChange(value.filter((v) => v !== id));
    else if (value.length >= max) return;
    else onChange([...value, id]);
  };

  const filtered = q.trim()
    ? docs.filter((d) =>
        `${d.file_name} ${d.uyap_file_no ?? ""} ${d.uyap_birim ?? ""}`
          .toLowerCase()
          .includes(q.trim().toLowerCase()),
      )
    : docs;

  const allSelected = filtered.length > 0 && filtered.every((d) => value.includes(d.id));

  return (
    <div className="space-y-2 rounded-lg border p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <FolderOpen className="h-4 w-4 text-primary" />
          UYAP / Dosya Belgeleri
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
          <Button size="sm" variant="ghost" onClick={load} disabled={loading}>
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Seçtiğiniz tüm belgelerin içeriği AI'ya bağlam olarak verilir
        {Number.isFinite(max)
          ? ` (en fazla ${max} belge)`
          : " (sınır yok; çok belge seçilirse belge başına metin otomatik kısaltılır)"}
        .
      </p>
      <Input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Belge ara (ad, dosya no, birim)"
        className="h-8"
      />

      <div className="max-h-56 space-y-1 overflow-y-auto">
        {filtered.length === 0 && (
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
                {[d.uyap_file_no, d.uyap_birim, d.doc_date].filter(Boolean).join(" • ") || d.source}
                {!d.has_text && " • metin çıkarılamadı"}
              </span>
            </span>
          </label>
        ))}
      </div>
    </div>
  );
};

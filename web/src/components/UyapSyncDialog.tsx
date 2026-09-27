import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Loader2, RefreshCw, ShieldCheck, CheckCircle2, AlertTriangle } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/components/AuthProvider";
import { toast } from "sonner";
import {
  MAX_ARCHIVE_ENTRIES,
  extractTextSample,
  humanSize,
  parseUyapMeta,
  readArchive,
  storagePathFor,
} from "@/lib/uyap";

interface Props {
  onSynced?: () => void;
}

type Result = { inserted: number; skipped: number; found: number };

export const UyapSyncDialog = ({ onSynced }: Props) => {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const [archive, setArchive] = useState<File | null>(null);

  const reset = () => {
    setArchive(null);
    setResult(null);
    setProgress(0);
  };

  const run = async () => {
    if (!user || !archive) return;
    setBusy(true);
    setResult(null);
    setProgress(0);
    const startedAt = Date.now();

    const { data: run } = await supabase
      .from("uyap_sync_runs")
      .insert({ owner_id: user.id, status: "running", archive_name: archive.name })
      .select("id")
      .single();

    let inserted = 0;
    let skipped = 0;
    let found = 0;

    try {
      const entries = await readArchive(archive);
      found = entries.length;
      if (!found) throw new Error("Arşivde içe aktarılabilir belge bulunamadı");

      for (let i = 0; i < entries.length; i++) {
        const entry = entries[i]!;
        try {
          const sample = await extractTextSample(entry.name, entry.data);
          const meta = parseUyapMeta(entry.name, sample);
          const path = storagePathFor(user.id, entry.name);

          // Aynı dosya no + belge adı daha önce aktarıldıysa atla (idempotent senkronizasyon)
          const { data: dup } = await supabase
            .from("case_documents")
            .select("id")
            .eq("owner_id", user.id)
            .eq("file_name", entry.name.split("/").pop()!)
            .eq("source", "uyap")
            .limit(1);
          if (dup && dup.length) {
            skipped++;
            continue;
          }

          const blob = new Blob([new Uint8Array(entry.data)], { type: "application/octet-stream" });
          const { error: upErr } = await supabase.storage
            .from("case-files")
            .upload(path, blob, { upsert: false });
          if (upErr) {
            skipped++;
            continue;
          }

          const { error: dbErr } = await supabase.from("case_documents").insert({
            owner_id: user.id,
            file_name: entry.name.split("/").pop()!,
            storage_path: path,
            size_bytes: entry.data.length,
            source: "uyap",
            content_excerpt: sample ? sample.slice(0, 1500) : null,
            sync_run_id: run?.id ?? null,
            ...meta,
          });
          if (dbErr) {
            await supabase.storage.from("case-files").remove([path]);
            skipped++;
          } else {
            inserted++;
          }
        } catch {
          skipped++;
        } finally {
          setProgress(((i + 1) / entries.length) * 100);
        }
      }

      if (run?.id) {
        await supabase
          .from("uyap_sync_runs")
          .update({
            status: "completed",
            found_count: found,
            inserted_count: inserted,
            skipped_count: skipped,
            duration_ms: Date.now() - startedAt,
          })
          .eq("id", run.id);
      }
      setResult({ inserted, skipped, found });
      toast.success(`Senkronizasyon tamamlandı: ${inserted} yeni belge`);
      onSynced?.();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Senkronizasyon başarısız";
      if (run?.id) {
        await supabase
          .from("uyap_sync_runs")
          .update({
            status: "failed",
            error_message: message,
            found_count: found,
            inserted_count: inserted,
            skipped_count: skipped,
            duration_ms: Date.now() - startedAt,
          })
          .eq("id", run.id);
      }
      toast.error(message);
      onSynced?.();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <RefreshCw className="h-4 w-4 mr-1" /> UYAP Senkronizasyonu
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>UYAP Dosya Senkronizasyonu</DialogTitle>
          <DialogDescription>
            UYAP Avukat Portalı'ndan indirdiğiniz dosya arşivini (.zip / .eyp) içe aktarın. Belgeler
            okunur, dosya no · birim · tarih · belge türü otomatik çıkarılır.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 text-[11px] leading-relaxed">
            <div className="flex items-center gap-2 font-semibold text-primary mb-1">
              <ShieldCheck className="h-3.5 w-3.5" /> Güvenli entegrasyon ilkesi
            </div>
            UYAP'ın açık bir API'si yoktur ve e-imza/parola bilgilerinizi hiçbir zaman istemiyoruz.
            Senkronizasyon, sizin indirdiğiniz resmî arşivin içe aktarılmasıyla yapılır. Arşiv
            tarayıcınızda açılır, dosyalar yalnızca sizin erişebildiğiniz özel depoya yüklenir. En
            fazla {MAX_ARCHIVE_ENTRIES} belge işlenir.
          </div>

          <input
            type="file"
            accept=".zip,.eyp"
            onChange={(e) => {
              setArchive(e.target.files?.[0] ?? null);
              setResult(null);
            }}
            className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-2 file:text-primary-foreground"
          />
          {archive && (
            <p className="text-xs text-muted-foreground">
              {archive.name} · {humanSize(archive.size)}
            </p>
          )}

          {busy && <Progress value={progress} />}

          {result && (
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs space-y-2">
              <div className="flex items-center gap-2 font-semibold text-emerald-700 dark:text-emerald-400">
                <CheckCircle2 className="h-4 w-4" /> Senkronizasyon tamamlandı
              </div>
              <div className="flex gap-2 flex-wrap">
                <Badge variant="outline">Bulunan: {result.found}</Badge>
                <Badge variant="outline">Eklenen: {result.inserted}</Badge>
                <Badge variant="outline">Atlanan: {result.skipped}</Badge>
              </div>
              {result.skipped > 0 && (
                <p className="flex items-start gap-1 text-muted-foreground">
                  <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                  Atlananlar; daha önce aktarılmış veya desteklenmeyen belgelerdir.
                </p>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={busy}>
            Kapat
          </Button>
          <Button onClick={run} disabled={busy || !archive}>
            {busy ? (
              <>
                <Loader2 className="h-4 w-4 mr-1 animate-spin" /> Aktarılıyor...
              </>
            ) : (
              "Senkronize Et"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

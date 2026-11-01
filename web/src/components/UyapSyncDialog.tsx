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
import { useAuth } from "@/components/AuthContext";
import { toast } from "sonner";
import { humanSize, readArchive } from "@/lib/uyap";
import { importEntries, type ImportResult } from "@/lib/uyap-import";

interface Props {
  onSynced?: () => void;
}

export const UyapSyncDialog = ({ onSynced }: Props) => {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<ImportResult | null>(null);
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

    let found = 0;

    try {
      const entries = await readArchive(archive);
      found = entries.length;
      if (!found) throw new Error("Arşivde içe aktarılabilir belge bulunamadı");

      const res = await importEntries(user.id, entries, {
        source: "uyap",
        syncRunId: run?.id ?? null,
        onProgress: setProgress,
      });

      if (run?.id) {
        await supabase
          .from("uyap_sync_runs")
          .update({
            status: res.failed ? "partial" : "completed",
            found_count: found,
            inserted_count: res.inserted,
            skipped_count: res.skipped,
            error_message: res.errors.join(" | ") || null,
            duration_ms: Date.now() - startedAt,
          })
          .eq("id", run.id);
      }
      setResult(res);
      if (res.failed)
        toast.warning(`${res.inserted} belge eklendi, ${res.failed} belge aktarılmadı`);
      else toast.success(`Senkronizasyon tamamlandı: ${res.inserted} yeni belge`);
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
            inserted_count: 0,
            skipped_count: 0,
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
        <Button size="sm" variant="outline" aria-label="UYAP Senkronizasyonu">
          <RefreshCw className="h-4 w-4 sm:mr-1" />{" "}
          <span className="hidden sm:inline">UYAP Senkronizasyonu</span>
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
            tarayıcınızda açılır, dosyalar yalnızca sizin erişebildiğiniz özel depoya yüklenir.
            Belge sayısı ve boyutu için sınır yoktur.
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
            <div
              className={`rounded-lg border p-3 text-xs space-y-2 ${result.failed ? "border-amber-500/30 bg-amber-500/5" : "border-emerald-500/30 bg-emerald-500/5"}`}
            >
              <div
                className={`flex items-center gap-2 font-semibold ${result.failed ? "text-amber-700 dark:text-amber-400" : "text-emerald-700 dark:text-emerald-400"}`}
              >
                {result.failed ? (
                  <AlertTriangle className="h-4 w-4" />
                ) : (
                  <CheckCircle2 className="h-4 w-4" />
                )}
                {result.failed ? "Senkronizasyon kısmen tamamlandı" : "Senkronizasyon tamamlandı"}
              </div>
              <div className="flex gap-2 flex-wrap">
                <Badge variant="outline">Bulunan: {result.found}</Badge>
                <Badge variant="outline">Eklenen: {result.inserted}</Badge>
                <Badge variant="outline">Atlanan: {result.skipped}</Badge>
                <Badge variant="destructive">Hatalı: {result.failed}</Badge>
              </div>
              {result.skipped > 0 && (
                <p className="flex items-start gap-1 text-muted-foreground">
                  <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                  Atlananlar; daha önce aktarılmış veya desteklenmeyen belgelerdir.
                </p>
              )}
              {result.errors.map((error) => (
                <p key={error} className="text-destructive">
                  {error}
                </p>
              ))}
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

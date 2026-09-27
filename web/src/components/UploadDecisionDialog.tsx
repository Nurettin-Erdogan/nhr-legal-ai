import { saveTextDocument } from "@/lib/office-api";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
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
import { Loader2, Upload, FileText, CheckCircle2, Sparkles } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { toast } from "sonner";

interface Props {
  onUploaded?: () => void;
}

interface Extracted {
  daire?: string;
  esas_no?: string;
  karar_no?: string;
  karar_tarihi?: string;
  hukuk_dali?: string;
  title?: string;
  excerpt?: string;
}

export const UploadDecisionDialog = ({ onUploaded }: Props) => {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [parsing, setParsing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [extracted, setExtracted] = useState<Extracted | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setText("");
    setSourceUrl("");
    setExtracted(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      toast.error("Dosya çok büyük (max 10 MB)");
      return;
    }
    setParsing(true);
    try {
      let out = "";
      if (file.name.toLowerCase().endsWith(".pdf")) {
        const pdfjs = await import("pdfjs-dist");
        const workerMod = await import("pdfjs-dist/build/pdf.worker.min.mjs?url");
        pdfjs.GlobalWorkerOptions.workerSrc = (workerMod as { default: string }).default;
        const buf = await file.arrayBuffer();
        const pdf = await pdfjs.getDocument({ data: buf }).promise;
        const parts: string[] = [];
        for (let i = 1; i <= pdf.numPages; i++) {
          const page = await pdf.getPage(i);
          const content = await page.getTextContent();
          parts.push(
            content.items.map((it) => ("str" in it ? (it as { str: string }).str : "")).join(" "),
          );
        }
        out = parts.join("\n\n");
      } else if (file.name.toLowerCase().endsWith(".docx")) {
        const mammoth = await import("mammoth/mammoth.browser.js");
        const buf = await file.arrayBuffer();
        const r = await mammoth.extractRawText({ arrayBuffer: buf });
        out = r.value;
      } else if (file.type.startsWith("text/") || /\.(txt|md)$/i.test(file.name)) {
        out = await file.text();
      } else {
        toast.error("Desteklenmeyen format (PDF, DOCX, TXT)");
        return;
      }
      if (!out.trim()) {
        toast.error("Dosyadan metin çıkarılamadı");
        return;
      }
      setText(out);
      toast.success(`${file.name} işlendi (${out.length.toLocaleString("tr-TR")} karakter)`);
    } catch (err) {
      console.error(err);
      toast.error("Dosya işlenemedi");
    } finally {
      setParsing(false);
    }
  };

  const submit = async () => {
    if (text.trim().length < 200) {
      toast.error("Karar metni çok kısa");
      return;
    }
    setSubmitting(true);
    try {
      // Kullanıcının yüklediği karar kişisel belge deposuna gider; resmî korpusa girmez ve
      // "doğrulanmış" sayılmaz.
      await saveTextDocument({
        fileName: `karar-${new Date().toISOString().slice(0, 10)}.txt`,
        text: sourceUrl ? `${text}\n\nKaynak: ${sourceUrl}` : text,
        source: "karar-yukleme",
        docType: "Karar",
      });
      toast.success("Karar dosyalarınıza eklendi ✓ (doğrulanmış kaynak sayılmaz)");
      onUploaded?.();
      setTimeout(() => {
        setOpen(false);
        reset();
      }, 1500);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Yükleme başarısız");
    } finally {
      setSubmitting(false);
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
          <Upload className="h-3 w-3 mr-1" />
          Karar Yükle
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-gold-deep" />
            Yargıtay Kararı Yükle
          </DialogTitle>
          <DialogDescription>
            PDF / DOCX / TXT karar metnini yükleyin. AI; daire, esas/karar no, tarih ve özet
            bilgilerini otomatik çıkarıp veritabanına kaydeder.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="grid gap-2">
            <label className="text-xs font-semibold text-muted-foreground">
              Dosya yükle (opsiyonel)
            </label>
            <div className="flex gap-2">
              <input
                ref={fileRef}
                type="file"
                accept=".pdf,.docx,.txt,.md"
                onChange={handleFile}
                className="hidden"
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => fileRef.current?.click()}
                disabled={parsing || submitting}
              >
                {parsing ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <Upload className="h-3 w-3 mr-1" />
                )}
                Dosya Seç
              </Button>
              <span className="text-xs text-muted-foreground self-center">
                veya aşağıya yapıştırın
              </span>
            </div>
          </div>

          <div className="grid gap-2">
            <label className="text-xs font-semibold text-muted-foreground">Karar metni</label>
            <Textarea
              rows={10}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Karar metnini buraya yapıştırın veya dosya yükleyin..."
              className="font-mono text-xs"
            />
            <span className="text-[10px] text-muted-foreground text-right">
              {text.length.toLocaleString("tr-TR")} karakter
            </span>
          </div>

          <div className="grid gap-2">
            <label className="text-xs font-semibold text-muted-foreground">
              Kaynak URL (opsiyonel)
            </label>
            <Input
              value={sourceUrl}
              onChange={(e) => setSourceUrl(e.target.value)}
              placeholder="https://karararama.yargitay.gov.tr/..."
            />
          </div>

          {extracted && (
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 space-y-2">
              <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400 text-sm font-semibold">
                <CheckCircle2 className="h-4 w-4" />
                AI Tarafından Çıkarılan Veri
              </div>
              <div className="grid gap-1 text-xs">
                {extracted.daire && (
                  <div>
                    <b>Daire:</b> {extracted.daire}
                  </div>
                )}
                <div className="flex gap-2 flex-wrap">
                  {extracted.esas_no && (
                    <Badge variant="outline" className="text-[10px] font-mono">
                      E. {extracted.esas_no}
                    </Badge>
                  )}
                  {extracted.karar_no && (
                    <Badge variant="outline" className="text-[10px] font-mono">
                      K. {extracted.karar_no}
                    </Badge>
                  )}
                  {extracted.karar_tarihi && (
                    <Badge variant="outline" className="text-[10px]">
                      {extracted.karar_tarihi}
                    </Badge>
                  )}
                  {extracted.hukuk_dali && (
                    <Badge className="text-[10px] bg-gold/15 text-gold-deep hover:bg-gold/20">
                      {extracted.hukuk_dali}
                    </Badge>
                  )}
                </div>
                {extracted.title && (
                  <div className="mt-1">
                    <b>Başlık:</b> {extracted.title}
                  </div>
                )}
                {extracted.excerpt && (
                  <div className="text-muted-foreground mt-1">{extracted.excerpt}</div>
                )}
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>
            İptal
          </Button>
          <Button onClick={submit} disabled={submitting || parsing || text.trim().length < 200}>
            {submitting ? (
              <>
                <Loader2 className="h-3 w-3 mr-1 animate-spin" /> AI ile işleniyor...
              </>
            ) : (
              <>
                <Sparkles className="h-3 w-3 mr-1" /> AI ile Çıkar & Kaydet
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

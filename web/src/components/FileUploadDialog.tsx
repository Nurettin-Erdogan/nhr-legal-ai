import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { confirmAction } from "@/lib/confirmation";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import { Loader2, Upload, ShieldCheck } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/components/AuthContext";
import { toast } from "sonner";
import {
  ALLOWED_EXTENSIONS,
  humanSize,
  isAllowedFile,
  parseUyapMeta,
  storagePathFor,
} from "@/lib/uyap";

import { linkProjectDocuments } from "@/lib/project-documents";

interface Props {
  onUploaded?: () => void;
  /** Verilirse yüklenen belgeler bu projeye bağlanır (Projeler > Belgeler sekmesi). */
  projectId?: string;
  label?: string;
}

export const FileUploadDialog = ({ onUploaded, projectId, label = "Dosya Yükle" }: Props) => {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [caseId, setCaseId] = useState<string>("none");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(0);
  const [cases, setCases] = useState<Array<{ id: string; title: string }>>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    void supabase
      .from("cases")
      .select("id, title")
      .order("created_at", { ascending: false })
      .limit(100)
      .then(({ data }) => setCases(data ?? []));
  }, [open]);

  const reset = () => {
    setFiles([]);
    setNotes("");
    setCaseId("none");
    setDone(0);
    if (inputRef.current) inputRef.current.value = "";
  };

  const pick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const list = Array.from(e.target.files ?? []);
    const ok = list.filter((f) => {
      if (!isAllowedFile(f.name)) {
        toast.error(`${f.name}: desteklenmeyen format`);
        return false;
      }
      return true;
    });
    setFiles(ok);
  };

  const upload = async () => {
    if (!user || !files.length) return;
    setBusy(true);
    setDone(0);
    let success = 0;
    const created: string[] = [];
    try {
      for (const file of files) {
        // Aynı ad ve boyutta belge zaten yüklüyse sessizce çoğaltılmaz: kullanıcıya sorulur (Büro Asistanı ve arama sonuçları
        // aynı belge için tekrar tekrar öneri/sonuç üretmesin).
        const existing = await supabase
          .from("case_documents")
          .select("id")
          .eq("file_name", file.name)
          .eq("size_bytes", file.size)
          .limit(1);
        if (
          Array.isArray(existing.data) &&
          existing.data.length > 0 &&
          !(await confirmAction({
            title: "Bu belge zaten yüklü görünüyor",
            description: `"${file.name}" aynı ad ve boyutta daha önce yüklenmiş. Yine de yeniden yüklensin mi?`,
            confirmLabel: "Yine de yükle",
            cancelLabel: "Atla",
          }))
        ) {
          setDone((d) => d + 1);
          continue;
        }
        const path = storagePathFor(user.id, file.name);
        const { error: upErr } = await supabase.storage.from("case-files").upload(path, file, {
          contentType: file.type || "application/octet-stream",
          upsert: false,
        });
        if (upErr) {
          toast.error(`${file.name}: ${upErr.message}`);
          setDone((d) => d + 1);
          continue;
        }

        const meta = parseUyapMeta(file.name);
        const documentId = crypto.randomUUID();
        const { error: dbErr } = await supabase.from("case_documents").insert({
          id: documentId,
          owner_id: user.id,
          case_id: caseId === "none" ? null : caseId,
          file_name: file.name,
          storage_path: path,
          mime_type: file.type || null,
          size_bytes: file.size,
          source: "manual",
          notes: notes || null,
          ...meta,
        });
        if (dbErr) {
          await supabase.storage.from("case-files").remove([path]);
          toast.error(`${file.name}: ${dbErr.message}`);
        } else {
          success++;
          created.push(documentId);
        }
        setDone((d) => d + 1);
      }
      if (success && projectId && created.length) {
        try {
          await linkProjectDocuments(projectId, created);
        } catch (error) {
          toast.error(
            error instanceof Error
              ? `Yüklendi ama projeye bağlanamadı: ${error.message}`
              : "Yüklendi ama projeye bağlanamadı.",
          );
        }
      }
      if (success) {
        toast.success(
          projectId
            ? `${success} dosya yüklendi ve projeye bağlandı`
            : `${success} dosya güvenli alana yüklendi`,
        );
        onUploaded?.();
        setOpen(false);
        reset();
      }
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
        <Button size="sm" aria-label={label}>
          <Upload className="h-4 w-4 sm:mr-1" />{" "}
          <span className={projectId ? "" : "hidden sm:inline"}>{label}</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{label}</DialogTitle>
          <DialogDescription>
            Belgeler yalnızca sizin erişebildiğiniz özel alanda saklanır (
            {ALLOWED_EXTENSIONS.join(", ")}).
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <input
            ref={inputRef}
            type="file"
            multiple
            onChange={pick}
            className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-2 file:text-primary-foreground"
          />

          {files.length > 0 && (
            <ul className="max-h-32 overflow-y-auto text-xs space-y-1 rounded-lg border border-border p-2">
              {files.map((f) => (
                <li key={f.name} className="flex justify-between gap-2">
                  <span className="truncate">{f.name}</span>
                  <span className="text-muted-foreground shrink-0">{humanSize(f.size)}</span>
                </li>
              ))}
            </ul>
          )}

          <div className="grid gap-2">
            <label className="text-xs font-semibold text-muted-foreground">
              İlgili dava (opsiyonel)
            </label>
            <Select value={caseId} onValueChange={setCaseId}>
              <SelectTrigger>
                <SelectValue placeholder="Seçin" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Dava ile ilişkilendirme</SelectItem>
                {cases.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <label className="text-xs font-semibold text-muted-foreground">Not (opsiyonel)</label>
            <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>

          {busy && <Progress value={(done / Math.max(files.length, 1)) * 100} />}

          <p className="flex items-start gap-2 text-[11px] text-muted-foreground">
            <ShieldCheck className="h-3.5 w-3.5 mt-0.5 shrink-0 text-primary" />
            Dosyalar özel depoda tutulur; indirme bağlantıları kısa süreli imzalı bağlantılarla
            üretilir.
          </p>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={busy}>
            İptal
          </Button>
          <Button onClick={upload} disabled={busy || !files.length}>
            {busy ? (
              <>
                <Loader2 className="h-4 w-4 mr-1 animate-spin" /> Yükleniyor...
              </>
            ) : (
              <>Yükle ({files.length})</>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

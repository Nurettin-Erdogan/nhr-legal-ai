import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { Switch } from "@/components/ui/switch";
import {
  Upload,
  Play,
  Square,
  ListChecks,
  ScanText,
  Loader2,
  Sparkles,
  Download,
  Save,
  Trash2,
  CheckCircle2,
  Clock,
  AlertTriangle,
  FileText,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Document, Packer, Paragraph, TextRun } from "docx";
import { jsPDF } from "jspdf";
import { saveAs } from "file-saver";
import { ocrImages, generatePetitionFromText, saveOcrDocument } from "@/lib/ocr.functions";
import { prepareForOcr, OCR_MAX_BYTES } from "@/lib/ocr-client";
import { humanSize, parseUyapMeta } from "@/lib/uyap";
import { supabase } from "@/integrations/supabase/client";
import { useQuery } from "@tanstack/react-query";
import {
  detectDocType,
  decidePetitionType,
  DOC_TYPE_LABELS,
  PETITION_LABELS as AUTO_PETITION_LABELS,
  downloadPetitionDocx,
  downloadPetitionPdf,
  slugName,
} from "@/lib/auto-pipeline";

type LogLevel = "info" | "success" | "warn" | "error" | "busy";

interface LogEntry {
  at: string;
  level: LogLevel;
  text: string;
}

interface AutoResult {
  fileName: string;
  docType: string;
  petitionType: string;
  outFile: string;
}

const LOG_ICON: Record<LogLevel, string> = {
  info: "\u{1F4CB}",
  success: "\u2713",
  warn: "\u26A0",
  error: "\u274C",
  busy: "\u23F3",
};

const LOG_CLASS: Record<LogLevel, string> = {
  info: "text-muted-foreground",
  success: "text-emerald-600 dark:text-emerald-400",
  warn: "text-amber-600 dark:text-amber-400",
  error: "text-destructive",
  busy: "text-primary",
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

type Status = "waiting" | "reading" | "read" | "sent" | "error";

interface Item {
  id: string;
  file: File;
  status: Status;
  text: string;
  error?: string;
  meta?: ReturnType<typeof parseUyapMeta>;
  pages?: number;
}

const PETITION_TYPES = [
  { value: "itiraz", label: "İtiraz Dilekçesi" },
  { value: "temyiz", label: "Temyiz Dilekçesi" },
  { value: "istinaf", label: "İstinaf Dilekçesi" },
  { value: "cevap", label: "Cevap Dilekçesi" },
  { value: "dava", label: "Dava Dilekçesi" },
  { value: "beyan", label: "Beyan Dilekçesi" },
  { value: "talep", label: "Talep Dilekçesi" },
];

const STATUS_UI: Record<Status, { label: string; icon: typeof Clock; cls: string }> = {
  waiting: { label: "Beklemede", icon: Clock, cls: "text-muted-foreground" },
  reading: { label: "Okunuyor", icon: Loader2, cls: "text-primary" },
  read: { label: "Okundu", icon: CheckCircle2, cls: "text-primary" },
  sent: { label: "Kaydedildi", icon: CheckCircle2, cls: "text-primary" },
  error: { label: "Hata", icon: AlertTriangle, cls: "text-destructive" },
};

const DocumentProcessing = () => {
  const [items, setItems] = useState<Item[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [autoRunning, setAutoRunning] = useState(false);
  const [autoDone, setAutoDone] = useState(0);
  const [autoTotal, setAutoTotal] = useState(0);
  const [autoFormat, setAutoFormat] = useState<"docx" | "pdf">("docx");
  const [autoDownload, setAutoDownload] = useState(true);
  const [autoDelay, setAutoDelay] = useState(2000);
  const [results, setResults] = useState<AutoResult[]>([]);
  const [summary, setSummary] = useState<{
    total: number;
    ok: number;
    failed: number;
    seconds: number;
    byType: Record<string, number>;
  } | null>(null);
  const stopRef = useRef(false);
  const [batchRunning, setBatchRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [petitionType, setPetitionType] = useState("itiraz");
  const [notes, setNotes] = useState("");
  const [petition, setPetition] = useState("");
  const [petitionTitle, setPetitionTitle] = useState("");
  const [generating, setGenerating] = useState(false);
  const [savingDoc, setSavingDoc] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const stored = useQuery({
    queryKey: ["ocr-pending-docs"],
    queryFn: async () => {
      const { data, error } = await supabase
        .from("case_documents")
        .select("id, file_name, storage_path, size_bytes, source, content_excerpt")
        .neq("source", "ocr")
        .order("created_at", { ascending: false })
        .limit(200);
      if (error) throw error;
      return data ?? [];
    },
  });

  /** UYAP'tan aktarılmış (depodaki) bir belgeyi indirip OCR listesine alır. */
  const pullStored = async (row: { id: string; file_name: string; storage_path: string }) => {
    addLog(`${row.file_name} depodan alınıyor…`, "busy");
    try {
      const { data, error } = await supabase.storage.from("case-files").download(row.storage_path);
      if (error || !data) throw new Error("Belge indirilemedi");
      const file = new File([data], row.file_name, { type: data.type || "application/pdf" });
      if (file.size > OCR_MAX_BYTES) throw new Error("25 MB sınırını aşıyor");
      const item: Item = {
        id: `stored-${row.id}-${crypto.randomUUID()}`,
        file,
        status: "waiting",
        text: "",
      };
      setItems((prev) => [...prev, item]);
      setActiveId(item.id);
      const text = await readOne(item);
      if (text) {
        await supabase
          .from("case_documents")
          .update({ content_excerpt: text.slice(0, 100000) })
          .eq("id", row.id);
        stored.refetch();
      }
    } catch (e) {
      addLog(`${row.file_name}: ${e instanceof Error ? e.message : "alınamadı"}`, "error");
      toast.error(e instanceof Error ? e.message : "Belge alınamadı");
    }
  };

  const active = useMemo(() => items.find((i) => i.id === activeId) ?? null, [items, activeId]);

  const addLog = useCallback((text: string, level: LogLevel = "info") => {
    const at = new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
    setLog((prev) => [{ at, level, text }, ...prev].slice(0, 300));
  }, []);

  const patch = (id: string, next: Partial<Item>) =>
    setItems((prev) => prev.map((i) => (i.id === id ? { ...i, ...next } : i)));

  const addFiles = (files: File[]) => {
    const accepted: Item[] = [];
    for (const file of files) {
      if (file.size > OCR_MAX_BYTES) {
        addLog(`${file.name} atlandı — 25 MB sınırını aşıyor`, "warn");
        continue;
      }
      accepted.push({
        id: `${file.name}-${file.size}-${crypto.randomUUID()}`,
        file,
        status: "waiting",
        text: "",
      });
    }
    if (!accepted.length) return;
    setItems((prev) => [...prev, ...accepted]);
    setActiveId((cur) => cur ?? accepted[0]!.id);
    addLog(`${accepted.length} belge listeye eklendi`, "success");
  };

  const readOne = async (item: Item): Promise<string | null> => {
    patch(item.id, { status: "reading", error: undefined });
    addLog(`${item.file.name} okunuyor…`, "busy");
    try {
      const prepared = await prepareForOcr(item.file);
      let text = prepared.embeddedText;
      let pages = 0;
      if (prepared.images.length) {
        const res = await ocrImages({
          data: { images: prepared.images, fileName: item.file.name },
        });
        pages = res.pages;
        text = [text, res.text]
          .filter((s) => s && s.trim())
          .join("\n\n")
          .trim();
      }
      if (!text.trim()) throw new Error("Metin bulunamadı");
      patch(item.id, {
        status: "read",
        text,
        pages,
        meta: parseUyapMeta(item.file.name, text),
      });
      setActiveId(item.id);
      addLog(
        `${item.file.name} okundu (${text.length.toLocaleString("tr-TR")} karakter)`,
        "success",
      );
      return text;
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Okunamadı";
      patch(item.id, { status: "error", error: msg });
      addLog(`${item.file.name} okunamadı: ${msg}`, "error");
      return null;
    }
  };

  const readAll = async () => {
    const queue = items.filter((i) => i.status === "waiting" || i.status === "error");
    if (!queue.length) {
      toast.info("Okunacak belge yok");
      return;
    }
    setBatchRunning(true);
    setProgress(0);
    for (let i = 0; i < queue.length; i++) {
      await readOne(queue[i]!);
      setProgress(((i + 1) / queue.length) * 100);
    }
    setBatchRunning(false);
    toast.success("Toplu okuma tamamlandı");
  };

  const saveToLibrary = async (item: Item) => {
    if (!item.text.trim()) {
      toast.error("Önce belgeyi oku");
      return;
    }
    setSavingDoc(true);
    try {
      await saveOcrDocument({
        data: {
          fileName: item.file.name,
          text: item.text,
          mimeType: item.file.type || undefined,
          sizeBytes: item.file.size,
        },
      });
      patch(item.id, { status: "sent" });
      addLog(`${item.file.name} JurisAI dosyalarına kaydedildi`, "success");
      toast.success("Belge JurisAI dosyalarına aktarıldı");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Aktarılamadı");
    } finally {
      setSavingDoc(false);
    }
  };

  const makePetition = async () => {
    if (!active?.text.trim()) {
      toast.error("Önce bir belge oku");
      return;
    }
    setGenerating(true);
    setPetition("");
    addLog(`${active.file.name} için dilekçe yazılıyor…`, "busy");
    try {
      const res = await generatePetitionFromText({
        data: {
          text: active.text,
          petitionType,
          notes,
          fileName: active.file.name,
        },
      });
      setPetition(res.content);
      setPetitionTitle(`${res.label} — ${active.file.name.replace(/\.[^.]+$/, "")}`);
      addLog(`Dilekçe hazır: ${res.label}`, "success");
      toast.success("Dilekçe oluşturuldu");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Dilekçe yazılamadı");
      addLog("Dilekçe yazılamadı", "error");
    } finally {
      setGenerating(false);
    }
  };

  /**
   * Tek tıkla tam otomatik boru hattı:
   * UYAP'tan aktarılan her belge → OCR → belge türü → uygun dilekçe → Word/PDF indir.
   */
  const runAutomation = useCallback(async () => {
    if (autoRunning) return;
    stopRef.current = false;
    setAutoRunning(true);
    setResults([]);
    setSummary(null);
    setAutoDone(0);
    const startedAt = Date.now();
    addLog("Otomatik UYAP → OCR → JurisAI → Dilekçe akışı başladı", "info");

    try {
      addLog("Belge listesi kontrol ediliyor…", "busy");
      const { data, error } = await supabase
        .from("case_documents")
        .select("id, file_name, storage_path, size_bytes, source, content_excerpt")
        .neq("source", "ocr")
        .order("created_at", { ascending: false })
        .limit(200);
      if (error) throw new Error("Belge listesi alınamadı");
      const queue = data ?? [];
      setAutoTotal(queue.length);
      if (!queue.length) {
        addLog(
          "Aktarılmış belge bulunamadı. Eklentideki BAŞLAT ile UYAP belgelerini aktar ya da dosyaları buraya bırak.",
          "warn",
        );
        return;
      }
      addLog(`${queue.length} belge bulundu`, "success");

      const counts: Record<string, number> = {};
      let ok = 0;
      let failed = 0;

      for (let i = 0; i < queue.length; i++) {
        if (stopRef.current) {
          addLog("Otomasyon durduruldu. İşlenen belgeler kayıtlı.", "warn");
          break;
        }
        const row = queue[i]!;
        const tag = `[${i + 1}/${queue.length}]`;
        try {
          addLog(`${tag} ${row.file_name} depodan indiriliyor…`, "busy");
          const { data: blob, error: dlErr } = await supabase.storage
            .from("case-files")
            .download(row.storage_path);
          if (dlErr || !blob) throw new Error("belge indirilemedi");
          const file = new File([blob], row.file_name, {
            type: blob.type || "application/pdf",
          });
          if (file.size > OCR_MAX_BYTES) throw new Error("25 MB sınırını aşıyor");

          const item: Item = {
            id: `auto-${row.id}-${crypto.randomUUID()}`,
            file,
            status: "waiting",
            text: "",
          };
          setItems((prev) => [...prev, item]);
          addLog(`${tag} OCR yapılıyor…`, "busy");
          const text = await readOne(item);
          if (!text) throw new Error("OCR başarısız");

          await supabase
            .from("case_documents")
            .update({ content_excerpt: text.slice(0, 100000) })
            .eq("id", row.id);

          const docType = detectDocType(text);
          addLog(`${tag} Belge türü: ${DOC_TYPE_LABELS[docType]}`, "info");
          const type = decidePetitionType(docType);
          const label = AUTO_PETITION_LABELS[type] ?? "Dilekçe";
          addLog(`${tag} ${label} yazılıyor…`, "busy");

          const res = await generatePetitionFromText({
            data: { text, petitionType: type, fileName: row.file_name },
          });
          setPetition(res.content);
          setPetitionTitle(`${res.label} — ${row.file_name}`);
          addLog(
            `${tag} ${res.label} hazır (${res.content.length.toLocaleString("tr-TR")} karakter)`,
            "success",
          );

          const outName = `${String(i + 1).padStart(2, "0")}_${label.replace(/\s+/g, "_")}_${slugName(row.file_name)}`;
          if (autoDownload) {
            if (autoFormat === "pdf") await downloadPetitionPdf(res.content, outName);
            else await downloadPetitionDocx(res.content, outName);
            addLog(`${tag} ${outName}.${autoFormat} indirildi`, "success");
          }

          await saveOcrDocument({
            data: {
              fileName: `${outName}.txt`,
              text: res.content,
              mimeType: "text/plain",
            },
          }).catch(() => null);

          counts[label] = (counts[label] ?? 0) + 1;
          ok++;
          setResults((prev) => [
            ...prev,
            {
              fileName: row.file_name,
              docType: DOC_TYPE_LABELS[docType],
              petitionType: label,
              outFile: `${outName}.${autoFormat}`,
            },
          ]);
        } catch (e) {
          failed++;
          addLog(`${tag} Hata: ${e instanceof Error ? e.message : "bilinmeyen"}`, "error");
        } finally {
          setAutoDone(i + 1);
        }
        if (i < queue.length - 1 && !stopRef.current) await sleep(autoDelay);
      }

      setSummary({
        total: queue.length,
        ok,
        failed,
        seconds: Math.round((Date.now() - startedAt) / 1000),
        byType: counts,
      });
      addLog(`Tamamlandı: ${ok} dilekçe yazıldı, ${failed} hata`, ok ? "success" : "warn");
      stored.refetch();
    } catch (e) {
      addLog(`Kritik hata: ${e instanceof Error ? e.message : "bilinmeyen"}`, "error");
    } finally {
      setAutoRunning(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRunning, autoDelay, autoDownload, autoFormat, addLog]);

  const search = Route.useSearch();
  const autoStarted = useRef(false);
  useEffect(() => {
    if (search.auto && !autoStarted.current) {
      autoStarted.current = true;
      void runAutomation();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search.auto]);

  const downloadDocx = async () => {
    const doc = new Document({
      sections: [
        {
          children: petition.split("\n").map(
            (line) =>
              new Paragraph({
                children: [
                  new TextRun({
                    text: line.replace(/[#*_`]/g, ""),
                    font: "Times New Roman",
                    size: 24,
                  }),
                ],
                spacing: { after: 120 },
              }),
          ),
        },
      ],
    });
    saveAs(await Packer.toBlob(doc), `${petitionTitle || "dilekce"}.docx`);
  };

  const downloadPdf = () => {
    const pdf = new jsPDF({ unit: "pt", format: "a4" });
    const lines = pdf.splitTextToSize(petition.replace(/[#*_`]/g, ""), 500);
    pdf.setFontSize(11);
    let y = 60;
    for (const line of lines) {
      if (y > 780) {
        pdf.addPage();
        y = 60;
      }
      pdf.text(line, 50, y);
      y += 16;
    }
    pdf.save(`${petitionTitle || "dilekce"}.pdf`);
  };

  return (
    <DashboardLayout
      title="Belge İşleme (OCR)"
      subtitle="UYAP belgelerini oku, metne çevir ve dilekçeye dönüştür"
    >
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div className="space-y-6">
          <Card className="space-y-4 border-primary/40 p-5">
            <div>
              <h2 className="text-lg font-semibold">Tam Otomatik Dilekçe Akışı</h2>
              <p className="text-sm text-muted-foreground">
                Tek tuş: UYAP'tan aktarılan tüm belgeler okunur, türü belirlenir, uygun dilekçe
                yazılır ve bilgisayarına indirilir.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="lg" onClick={runAutomation} disabled={autoRunning}>
                {autoRunning ? (
                  <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                ) : (
                  <Play className="mr-2 h-5 w-5" />
                )}
                Başlat
              </Button>
              <Button
                size="lg"
                variant="destructive"
                disabled={!autoRunning}
                onClick={() => {
                  stopRef.current = true;
                  addLog("Durdurma isteği alındı…", "warn");
                }}
              >
                <Square className="mr-2 h-4 w-4" /> Durdur
              </Button>
            </div>
            {(autoRunning || autoTotal > 0) && (
              <div>
                <Progress value={autoTotal ? (autoDone / autoTotal) * 100 : 0} />
                <p className="mt-1 text-xs text-muted-foreground">
                  {autoTotal ? Math.round((autoDone / autoTotal) * 100) : 0}% ({autoDone}/
                  {autoTotal})
                </p>
              </div>
            )}
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <Label>Dosya biçimi</Label>
                <Select
                  value={autoFormat}
                  onValueChange={(v) => setAutoFormat(v as "docx" | "pdf")}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="docx">Word (.docx)</SelectItem>
                    <SelectItem value="pdf">PDF</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label htmlFor="autoDelay">Belge arası bekleme (ms)</Label>
                <Input
                  id="autoDelay"
                  type="number"
                  min={0}
                  max={20000}
                  step={500}
                  value={autoDelay}
                  onChange={(e) => setAutoDelay(Number(e.target.value) || 0)}
                />
              </div>
              <div className="flex items-end gap-2">
                <Switch
                  id="autoDownload"
                  checked={autoDownload}
                  onCheckedChange={setAutoDownload}
                />
                <Label htmlFor="autoDownload">Otomatik indir</Label>
              </div>
            </div>
          </Card>

          {summary && (
            <Card className="space-y-3 p-5">
              <h2 className="flex items-center gap-2 font-semibold">
                <ListChecks className="h-4 w-4 text-primary" /> Otomasyon Özeti
              </h2>
              <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                <div>
                  <p className="text-lg font-semibold">
                    {summary.ok}/{summary.total}
                  </p>
                  <p className="text-xs text-muted-foreground">yazılan dilekçe</p>
                </div>
                <div>
                  <p className="text-lg font-semibold">{summary.failed}</p>
                  <p className="text-xs text-muted-foreground">hata</p>
                </div>
                <div>
                  <p className="text-lg font-semibold">
                    {Math.floor(summary.seconds / 60)} dk {summary.seconds % 60} sn
                  </p>
                  <p className="text-xs text-muted-foreground">toplam süre</p>
                </div>
                <div>
                  <p className="text-lg font-semibold">{results.length}</p>
                  <p className="text-xs text-muted-foreground">indirilen dosya</p>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(summary.byType).map(([label, count]) => (
                  <Badge key={label} variant="secondary">
                    {label}: {count}
                  </Badge>
                ))}
              </div>
              {results.length > 0 && (
                <ul className="max-h-40 space-y-1 overflow-auto text-xs text-muted-foreground">
                  {results.map((r) => (
                    <li key={r.outFile}>
                      {r.outFile} — {r.docType} → {r.petitionType}
                    </li>
                  ))}
                </ul>
              )}
              <Button variant="secondary" size="sm" onClick={runAutomation} disabled={autoRunning}>
                Tekrar Çalıştır
              </Button>
            </Card>
          )}

          <Card
            className="border-dashed p-6 text-center"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              addFiles([...e.dataTransfer.files]);
            }}
          >
            <Upload className="mx-auto mb-3 h-8 w-8 text-primary" />
            <p className="font-medium">Dosyaları buraya sürükle veya seç</p>
            <p className="mt-1 text-sm text-muted-foreground">
              PDF, DOCX, JPG, PNG, TXT — dosya başına en fazla 25 MB
            </p>
            <input
              ref={inputRef}
              type="file"
              multiple
              className="hidden"
              accept=".pdf,.docx,.doc,.txt,.jpg,.jpeg,.png,.tif,.tiff"
              onChange={(e) => {
                addFiles([...(e.target.files ?? [])]);
                e.target.value = "";
              }}
            />
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              <Button onClick={() => inputRef.current?.click()}>Dosya Seç</Button>
              <Button variant="secondary" onClick={readAll} disabled={batchRunning}>
                {batchRunning ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <ScanText className="mr-2 h-4 w-4" />
                )}
                Tümünü Oku
              </Button>
            </div>
            {batchRunning && <Progress value={progress} className="mt-4" />}
          </Card>

          <Card className="p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-semibold">Dosya Listesi ({items.length})</h2>
              {items.length > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setItems([]);
                    setActiveId(null);
                    setPetition("");
                  }}
                >
                  <Trash2 className="mr-1 h-4 w-4" /> Temizle
                </Button>
              )}
            </div>
            {items.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Henüz belge yok. UYAP'tan indirdiğin dosyaları buraya bırak.
              </p>
            ) : (
              <ul className="space-y-2">
                {items.map((item) => {
                  const ui = STATUS_UI[item.status];
                  const Icon = ui.icon;
                  return (
                    <li
                      key={item.id}
                      className={`rounded-xl border p-3 ${
                        activeId === item.id ? "border-primary bg-primary/5" : "border-border"
                      }`}
                    >
                      <button
                        type="button"
                        className="flex w-full items-start gap-2 text-left"
                        onClick={() => setActiveId(item.id)}
                      >
                        <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">
                            {item.file.name}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {humanSize(item.file.size)}
                            {item.meta?.uyap_file_no ? ` • ${item.meta.uyap_file_no}` : ""}
                            {item.meta?.uyap_birim ? ` • ${item.meta.uyap_birim}` : ""}
                          </span>
                        </span>
                        <Badge variant="secondary" className={`gap-1 ${ui.cls}`}>
                          <Icon
                            className={`h-3 w-3 ${item.status === "reading" ? "animate-spin" : ""}`}
                          />
                          {ui.label}
                        </Badge>
                      </button>
                      {item.error && <p className="mt-1 text-xs text-destructive">{item.error}</p>}
                      <div className="mt-2 flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={item.status === "reading" || batchRunning}
                          onClick={() => readOne(item)}
                        >
                          <ScanText className="mr-1 h-3.5 w-3.5" /> Oku
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={!item.text || savingDoc}
                          onClick={() => saveToLibrary(item)}
                        >
                          <Save className="mr-1 h-3.5 w-3.5" /> JurisAI'ya Gönder
                        </Button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>

          <Card className="p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-semibold">UYAP'tan Aktarılan Belgeler</h2>
              <Button variant="ghost" size="sm" onClick={() => stored.refetch()}>
                Yenile
              </Button>
            </div>
            {stored.isLoading ? (
              <p className="text-sm text-muted-foreground">Yükleniyor…</p>
            ) : !stored.data?.length ? (
              <p className="text-sm text-muted-foreground">
                Eklentiyle aktardığın belgeler burada görünür ve tek tıkla okunabilir.
              </p>
            ) : (
              <ul className="max-h-72 space-y-2 overflow-auto">
                {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                {stored.data.map((row: any) => (
                  <li
                    key={row.id}
                    className="flex items-center justify-between gap-2 rounded-lg border p-2"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm">{row.file_name}</span>
                      <span className="text-xs text-muted-foreground">
                        {humanSize(row.size_bytes ?? 0)}
                        {row.content_excerpt ? " • okunmuş" : " • okunmadı"}
                      </span>
                    </span>
                    <Button size="sm" variant="secondary" onClick={() => pullStored(row)}>
                      <ScanText className="mr-1 h-3.5 w-3.5" /> Oku
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card className="p-5">
            <h2 className="mb-3 font-semibold">İşlem Günlüğü</h2>
            <div className="max-h-56 space-y-1 overflow-auto rounded-lg bg-muted/40 p-3 font-mono text-xs">
              {log.length === 0 ? (
                <p className="text-muted-foreground">Hazır.</p>
              ) : (
                log.map((entry, i) => (
                  <div key={i} className={LOG_CLASS[entry.level]}>
                    [{entry.at}] {LOG_ICON[entry.level]} {entry.text}
                  </div>
                ))
              )}
            </div>
          </Card>
        </div>

        <div className="space-y-6">
          <Card className="p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-semibold">OCR Çıktısı</h2>
              {active?.pages ? <Badge variant="secondary">{active.pages} sayfa OCR</Badge> : null}
            </div>
            <Textarea
              value={active?.text ?? ""}
              onChange={(e) => active && patch(active.id, { text: e.target.value })}
              placeholder="Bir belge seç ve 'Oku' düğmesine bas; metin burada düzenlenebilir."
              className="min-h-[220px] font-mono text-xs"
            />
          </Card>

          <Card className="space-y-4 p-5">
            <h2 className="font-semibold">Dilekçe Üret</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <Label>Dilekçe türü</Label>
                <Select value={petitionType} onValueChange={setPetitionType}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PETITION_TYPES.map((t) => (
                      <SelectItem key={t.value} value={t.value}>
                        {t.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label htmlFor="notes">Not (opsiyonel)</Label>
                <Input
                  id="notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Örn: süre tutum, vekalet bilgisi"
                />
              </div>
            </div>
            <Button onClick={makePetition} disabled={generating || !active?.text}>
              {generating ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="mr-2 h-4 w-4" />
              )}
              Dilekçe Yaz
            </Button>

            {petition && (
              <div className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="secondary" onClick={downloadDocx}>
                    <Download className="mr-1 h-4 w-4" /> Word
                  </Button>
                  <Button size="sm" variant="secondary" onClick={downloadPdf}>
                    <Download className="mr-1 h-4 w-4" /> PDF
                  </Button>
                </div>
                <Textarea
                  value={petition}
                  onChange={(e) => setPetition(e.target.value)}
                  className="min-h-[200px] text-sm"
                />
                <div className="prose prose-sm max-w-none rounded-lg border p-4 dark:prose-invert">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{petition}</ReactMarkdown>
                </div>
              </div>
            )}
          </Card>
        </div>
      </div>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/document-processing")({
  validateSearch: (search: Record<string, unknown>) => ({
    auto: search.auto === "1" || search.auto === true,
  }),
  head: () => ({
    meta: [
      { title: "Belge İşleme ve OCR | JurisAI" },
      {
        name: "description",
        content: "UYAP belgelerini OCR ile oku, metni düzenle ve tek tıkla dilekçeye dönüştür.",
      },
      { property: "og:title", content: "Belge İşleme ve OCR | JurisAI" },
      {
        property: "og:description",
        content: "Mahkeme belgelerini OCR ile metne çevir, JurisAI ile dilekçe üret.",
      },
    ],
  }),
  component: DocumentProcessing,
});

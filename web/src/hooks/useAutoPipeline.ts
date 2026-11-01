/** Tek tuşla tam otomatik akış: depodaki belgeler → OCR → belge türü → dilekçe → Word/PDF indir. */
import { useCallback, useRef, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { prepareForOcr, OCR_MAX_BYTES } from "@/lib/ocr-client";
import { ocrImages, generatePetitionFromText, saveOcrDocument } from "@/lib/ocr.functions";
import {
  detectDocType,
  decidePetitionType,
  DOC_TYPE_LABELS,
  PETITION_LABELS,
  downloadPetitionDocx,
  downloadPetitionPdf,
  slugName,
} from "@/lib/auto-pipeline";

export type LogLevel = "info" | "success" | "warn" | "error" | "busy";

export interface LogEntry {
  at: string;
  level: LogLevel;
  text: string;
}

export interface PipelineResult {
  fileName: string;
  docType: string;
  petitionType: string;
  outFile: string;
  content: string;
}

export interface PipelineSummary {
  total: number;
  ok: number;
  failed: number;
  seconds: number;
  byType: Record<string, number>;
}

export interface PipelineOptions {
  format: "docx" | "pdf";
  autoDownload: boolean;
  delayMs: number;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function useAutoPipeline() {
  const [log, setLog] = useState<LogEntry[]>([]);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(0);
  const [total, setTotal] = useState(0);
  const [current, setCurrent] = useState("");
  const [results, setResults] = useState<PipelineResult[]>([]);
  const [summary, setSummary] = useState<PipelineSummary | null>(null);
  const stopRef = useRef(false);

  const addLog = useCallback((text: string, level: LogLevel = "info") => {
    const at = new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
    setLog((prev) => [{ at, level, text }, ...prev].slice(0, 400));
  }, []);

  const stop = useCallback(() => {
    stopRef.current = true;
    addLog("Durdurma isteği alındı, mevcut belge bitince duracak…", "warn");
  }, [addLog]);

  const start = useCallback(
    async (options: PipelineOptions) => {
      if (running) return;
      stopRef.current = false;
      setRunning(true);
      setResults([]);
      setSummary(null);
      setDone(0);
      setCurrent("");
      const startedAt = Date.now();
      addLog("Otomatik akış başladı: belge → okuma → tür tespiti → dilekçe → indirme", "info");

      try {
        addLog("Belge listesi alınıyor…", "busy");
        const { data, error } = await supabase
          .from("case_documents")
          .select("id, file_name, storage_path, size_bytes")
          .neq("source", "ocr")
          .order("created_at", { ascending: false })
          .limit(200);
        if (error) throw new Error("Belge listesi alınamadı");
        const queue = data ?? [];
        setTotal(queue.length);
        if (!queue.length) {
          addLog(
            "İşlenecek belge yok. UYAP eklentisiyle belgeleri aktar ya da Belge İşleme sayfasından dosya yükle.",
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
            addLog("Otomasyon durduruldu. İşlenen dilekçeler kayıtlı.", "warn");
            break;
          }
          const row = queue[i]!;
          const tag = `[${i + 1}/${queue.length}]`;
          setCurrent(row.file_name);
          try {
            addLog(`${tag} ${row.file_name} indiriliyor…`, "busy");
            const { data: blob, error: dlErr } = await supabase.storage
              .from("case-files")
              .download(row.storage_path);
            if (dlErr || !blob) throw new Error("belge indirilemedi");
            const file = new File([blob], row.file_name, { type: blob.type || "application/pdf" });
            if (file.size > OCR_MAX_BYTES) throw new Error("25 MB sınırını aşıyor");

            addLog(`${tag} metne çevriliyor…`, "busy");
            const prepared = await prepareForOcr(file);
            let text = prepared.embeddedText;
            if (prepared.images.length) {
              const res = await ocrImages({
                data: { images: prepared.images, fileName: file.name },
              });
              text = [text, res.text]
                .filter((s) => s && s.trim())
                .join("\n\n")
                .trim();
            }
            if (!text.trim()) throw new Error("metin bulunamadı");
            addLog(`${tag} ${text.length.toLocaleString("tr-TR")} karakter okundu`, "success");

            await supabase
              .from("case_documents")
              .update({ content_excerpt: text.slice(0, 100000) })
              .eq("id", row.id);

            const docType = detectDocType(text);
            const type = decidePetitionType(docType);
            const label = PETITION_LABELS[type] ?? "Dilekçe";
            addLog(`${tag} ${DOC_TYPE_LABELS[docType]} → ${label} yazılıyor…`, "busy");

            const petition = await generatePetitionFromText({
              data: { text, petitionType: type, fileName: row.file_name },
            });

            const outName = `${String(i + 1).padStart(2, "0")}_${label.replace(/\s+/g, "_")}_${slugName(row.file_name)}`;
            if (options.autoDownload) {
              if (options.format === "pdf") await downloadPetitionPdf(petition.content, outName);
              else await downloadPetitionDocx(petition.content, outName);
              addLog(`${tag} ${outName}.${options.format} indirildi`, "success");
            } else {
              addLog(`${tag} ${petition.label} hazır`, "success");
            }

            await saveOcrDocument({
              data: { fileName: `${outName}.txt`, text: petition.content, mimeType: "text/plain" },
            }).catch(() => null);

            counts[label] = (counts[label] ?? 0) + 1;
            ok++;
            setResults((prev) => [
              ...prev,
              {
                fileName: row.file_name,
                docType: DOC_TYPE_LABELS[docType],
                petitionType: label,
                outFile: `${outName}.${options.format}`,
                content: petition.content,
              },
            ]);
          } catch (e) {
            failed++;
            addLog(`${tag} Hata: ${e instanceof Error ? e.message : "bilinmeyen"}`, "error");
          } finally {
            setDone(i + 1);
          }
          if (i < queue.length - 1 && !stopRef.current) await sleep(options.delayMs);
        }

        setSummary({
          total: queue.length,
          ok,
          failed,
          seconds: Math.round((Date.now() - startedAt) / 1000),
          byType: counts,
        });
        addLog(`Tamamlandı: ${ok} dilekçe yazıldı, ${failed} hata`, ok ? "success" : "warn");
      } catch (e) {
        addLog(`Kritik hata: ${e instanceof Error ? e.message : "bilinmeyen"}`, "error");
      } finally {
        setCurrent("");
        setRunning(false);
      }
    },
    [running, addLog],
  );

  return { log, running, done, total, current, results, summary, start, stop };
}

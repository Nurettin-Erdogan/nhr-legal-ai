import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2, Play, Square, ListChecks, FileDown, Rocket } from "lucide-react";
import { useAutoPipeline, type LogLevel } from "@/hooks/useAutoPipeline";
import { downloadPetitionDocx, downloadPetitionPdf } from "@/lib/auto-pipeline";

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

const Automation = () => {
  const { log, running, done, total, current, results, summary, start, stop } = useAutoPipeline();
  const [format, setFormat] = useState<"docx" | "pdf">("docx");
  const [autoDownload, setAutoDownload] = useState(true);
  const [delayMs, setDelayMs] = useState(2000);
  const search = Route.useSearch();
  const started = useRef(false);

  const run = () => void start({ format, autoDownload, delayMs });

  useEffect(() => {
    if (search.auto && !started.current) {
      started.current = true;
      void start({ format: "docx", autoDownload: true, delayMs: 2000 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search.auto]);

  const percent = total ? Math.round((done / total) * 100) : 0;

  return (
    <DashboardLayout
      title="Tek Tuşla Otomasyon"
      subtitle="Belgeleri oku, türünü belirle, dilekçeyi yaz ve indir — hepsi tek düğmeyle"
    >
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-6">
          <Card className="space-y-5 border-primary/40 p-6">
            <div className="flex items-start gap-3">
              <Rocket className="mt-1 h-6 w-6 text-primary" />
              <div>
                <h2 className="text-lg font-semibold">Otomatik dilekçe üretimi</h2>
                <p className="text-sm text-muted-foreground">
                  Hesabındaki tüm belgeler tek tek okunur, hangi tür dosya olduğu belirlenir, uygun
                  dilekçe yazılır ve bilgisayarına indirilir. Sen sadece başlat.
                </p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button size="lg" className="flex-1 sm:flex-none" onClick={run} disabled={running}>
                {running ? (
                  <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                ) : (
                  <Play className="mr-2 h-5 w-5" />
                )}
                Başlat
              </Button>
              <Button size="lg" variant="destructive" disabled={!running} onClick={stop}>
                <Square className="mr-2 h-4 w-4" /> Durdur
              </Button>
            </div>

            {(running || total > 0) && (
              <div>
                <Progress value={percent} />
                <p className="mt-1 text-xs text-muted-foreground">
                  %{percent} ({done}/{total}) {current ? `• ${current}` : ""}
                </p>
              </div>
            )}

            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <Label>Dosya biçimi</Label>
                <Select value={format} onValueChange={(v) => setFormat(v as "docx" | "pdf")}>
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
                <Label htmlFor="delay">Belge arası bekleme (ms)</Label>
                <Input
                  id="delay"
                  type="number"
                  min={0}
                  max={20000}
                  step={500}
                  value={delayMs}
                  onChange={(e) => setDelayMs(Number(e.target.value) || 0)}
                />
              </div>
              <div className="flex items-end gap-2">
                <Switch id="dl" checked={autoDownload} onCheckedChange={setAutoDownload} />
                <Label htmlFor="dl">Otomatik indir</Label>
              </div>
            </div>
          </Card>

          <Card className="p-5">
            <h2 className="mb-3 font-semibold">İşlem Günlüğü</h2>
            <div className="max-h-80 space-y-1 overflow-auto rounded-lg bg-muted/40 p-3 font-mono text-xs">
              {log.length === 0 ? (
                <p className="text-muted-foreground">Hazır. "Başlat"a basabilirsin.</p>
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
          {summary && (
            <Card className="space-y-3 p-5">
              <h2 className="flex items-center gap-2 font-semibold">
                <ListChecks className="h-4 w-4 text-primary" /> Özet
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
                  <p className="text-xs text-muted-foreground">süre</p>
                </div>
                <div>
                  <p className="text-lg font-semibold">{results.length}</p>
                  <p className="text-xs text-muted-foreground">hazır dosya</p>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(summary.byType).map(([label, count]) => (
                  <Badge key={label} variant="secondary">
                    {label}: {count}
                  </Badge>
                ))}
              </div>
              <Button variant="secondary" size="sm" onClick={run} disabled={running}>
                Tekrar Çalıştır
              </Button>
            </Card>
          )}

          <Card className="p-5">
            <h2 className="mb-3 font-semibold">Hazır Dilekçeler ({results.length})</h2>
            {results.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Akış tamamlandıkça yazılan dilekçeler burada listelenir; istediğini yeniden
                indirebilirsin.
              </p>
            ) : (
              <ul className="max-h-[420px] space-y-2 overflow-auto">
                {results.map((r) => (
                  <li key={r.outFile} className="rounded-lg border p-3">
                    <p className="truncate text-sm font-medium">{r.outFile}</p>
                    <p className="text-xs text-muted-foreground">
                      {r.fileName} • {r.docType} → {r.petitionType}
                    </p>
                    <div className="mt-2 flex gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          void downloadPetitionDocx(r.content, r.outFile.replace(/\.[^.]+$/, ""))
                        }
                      >
                        <FileDown className="mr-1 h-3.5 w-3.5" /> Word
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          void downloadPetitionPdf(r.content, r.outFile.replace(/\.[^.]+$/, ""))
                        }
                      >
                        <FileDown className="mr-1 h-3.5 w-3.5" /> PDF
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/automation")({
  validateSearch: (search: Record<string, unknown>) => ({
    auto: search.auto === "1" || search.auto === true,
  }),
  head: () => ({
    meta: [
      { title: "Tek Tuşla Dilekçe Otomasyonu | JurisAI" },
      {
        name: "description",
        content:
          "Tek düğmeyle tüm dosyaları okut, belge türünü belirlet, dilekçeleri yazdır ve Word/PDF olarak indir.",
      },
      { property: "og:title", content: "Tek Tuşla Dilekçe Otomasyonu | JurisAI" },
      {
        property: "og:description",
        content: "JurisAI otomasyonu: belge okuma, tür tespiti ve dilekçe üretimi tek tuşla.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: Automation,
});

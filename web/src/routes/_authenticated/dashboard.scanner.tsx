import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import {
  Camera,
  X,
  Download,
  FileImage,
  FileText,
  Send,
  RotateCw,
  Trash2,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import { jsPDF } from "jspdf";
import { useNavigate } from "@/lib/router-compat";

type Page = { dataUrl: string; w: number; h: number };

const Scanner = () => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [active, setActive] = useState(false);
  const [pages, setPages] = useState<Page[]>([]);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  useEffect(() => () => stopCamera(), []);

  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setActive(true);
    } catch (e: any) {
      toast.error("Kameraya erişilemedi. Tarayıcı izinlerini kontrol edin.");
      console.error(e);
    }
  };

  const stopCamera = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setActive(false);
  };

  const capture = () => {
    const video = videoRef.current;
    if (!video) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0);
    // Light contrast/brightness boost for document feel
    const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const d = img.data;
    for (let i = 0; i < d.length; i += 4) {
      for (let c = 0; c < 3; c++) {
        const v = d[i + c];
        const adj = Math.min(255, Math.max(0, (v - 128) * 1.25 + 138));
        d[i + c] = adj;
      }
    }
    ctx.putImageData(img, 0, 0);
    const dataUrl = canvas.toDataURL("image/jpeg", 0.9);
    setPages((p) => [...p, { dataUrl, w: canvas.width, h: canvas.height }]);
    toast.success(`Sayfa ${pages.length + 1} eklendi`);
  };

  const onPickFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    for (const f of files) {
      const url = await fileToDataUrl(f);
      const dim = await imgDim(url);
      setPages((p) => [...p, { dataUrl: url, w: dim.w, h: dim.h }]);
    }
    e.target.value = "";
  };

  const removePage = (i: number) => setPages((p) => p.filter((_, idx) => idx !== i));

  const downloadPdf = async () => {
    if (!pages.length) return;
    setBusy(true);
    try {
      const pdf = new jsPDF({ unit: "pt", format: "a4" });
      const pw = pdf.internal.pageSize.getWidth();
      const ph = pdf.internal.pageSize.getHeight();
      pages.forEach((pg, idx) => {
        if (idx > 0) pdf.addPage();
        const ratio = Math.min(pw / pg.w, ph / pg.h);
        const w = pg.w * ratio;
        const h = pg.h * ratio;
        const x = (pw - w) / 2;
        const y = (ph - h) / 2;
        pdf.addImage(pg.dataUrl, "JPEG", x, y, w, h);
      });
      pdf.save(`tarama-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.pdf`);
    } finally {
      setBusy(false);
    }
  };

  const downloadJpgs = () => {
    pages.forEach((pg, i) => {
      const a = document.createElement("a");
      a.href = pg.dataUrl;
      a.download = `tarama-sayfa-${i + 1}.jpg`;
      a.click();
    });
  };

  const sendToAssistant = () => {
    if (!pages.length) return;
    sessionStorage.setItem(
      "scanner_payload",
      JSON.stringify({ pages: pages.map((p) => p.dataUrl), at: Date.now() }),
    );
    toast.success("Tarama Asistana iletildi");
    navigate("/dashboard/ai");
  };

  return (
    <DashboardLayout
      title="Belge Tarayıcı"
      subtitle="Telefonun kamerasıyla sayfa çek, PDF veya JPG olarak kaydet"
    >
      <div className="max-w-5xl mx-auto grid lg:grid-cols-[1fr_320px] gap-6">
        {/* Camera area */}
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="relative aspect-[3/4] bg-black flex items-center justify-center">
            <video
              ref={videoRef}
              playsInline
              muted
              className={active ? "w-full h-full object-cover" : "hidden"}
            />
            {!active && (
              <div className="text-center p-8">
                <Camera className="h-12 w-12 mx-auto text-muted-foreground mb-3" />
                <p className="text-sm text-muted-foreground mb-4">
                  Kamera kapalı. Başlatmak için butona basın.
                </p>
                <Button onClick={startCamera}>
                  <Camera className="h-4 w-4 mr-2" /> Kamerayı Aç
                </Button>
                <div className="mt-3">
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    className="text-xs text-muted-foreground hover:text-foreground underline"
                  >
                    veya galeriden seç
                  </button>
                </div>
              </div>
            )}
          </div>

          {active && (
            <div className="p-4 flex items-center justify-center gap-3 border-t border-border">
              <Button variant="outline" size="icon" onClick={stopCamera} aria-label="Kapat">
                <X className="h-4 w-4" />
              </Button>
              <Button size="lg" onClick={capture} className="rounded-full h-16 w-16 p-0">
                <Camera className="h-6 w-6" />
              </Button>
              <Button
                variant="outline"
                size="icon"
                onClick={() => fileInputRef.current?.click()}
                aria-label="Galeri"
              >
                <FileImage className="h-4 w-4" />
              </Button>
            </div>
          )}

          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            capture="environment"
            onChange={onPickFiles}
            className="hidden"
          />
        </div>

        {/* Pages + actions */}
        <div className="space-y-4">
          <div className="rounded-xl border border-border bg-card p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium">Sayfalar ({pages.length})</h3>
              {pages.length > 0 && (
                <button
                  onClick={() => setPages([])}
                  className="text-xs text-muted-foreground hover:text-destructive"
                >
                  Tümünü sil
                </button>
              )}
            </div>
            {pages.length === 0 ? (
              <p className="text-xs text-muted-foreground">Henüz sayfa eklenmedi.</p>
            ) : (
              <div className="grid grid-cols-3 gap-2 max-h-80 overflow-y-auto">
                {pages.map((p, i) => (
                  <div
                    key={i}
                    className="relative group rounded-md overflow-hidden border border-border"
                  >
                    <img
                      src={p.dataUrl}
                      alt={`Sayfa ${i + 1}`}
                      className="w-full h-20 object-cover"
                    />
                    <span className="absolute bottom-0 left-0 bg-background/80 text-[10px] px-1">
                      {i + 1}
                    </span>
                    <button
                      onClick={() => removePage(i)}
                      className="absolute top-1 right-1 h-5 w-5 rounded bg-background/80 opacity-0 group-hover:opacity-100 transition flex items-center justify-center"
                      aria-label="Sayfayı sil"
                    >
                      <Trash2 className="h-3 w-3 text-destructive" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-xl border border-border bg-card p-4 space-y-2">
            <Button
              onClick={downloadPdf}
              disabled={!pages.length || busy}
              className="w-full justify-start"
            >
              {busy ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <FileText className="h-4 w-4 mr-2" />
              )}
              PDF olarak indir
            </Button>
            <Button
              onClick={downloadJpgs}
              disabled={!pages.length}
              variant="outline"
              className="w-full justify-start"
            >
              <Download className="h-4 w-4 mr-2" /> JPG olarak indir
            </Button>
            <Button
              onClick={sendToAssistant}
              disabled={!pages.length}
              variant="outline"
              className="w-full justify-start"
            >
              <Send className="h-4 w-4 mr-2" /> Asistana gönder
            </Button>
          </div>

          <p className="text-[10px] text-muted-foreground">
            İpucu: En iyi sonuç için belgeyi düz bir zeminde, gölgesiz şekilde çekin.
          </p>
        </div>
      </div>
    </DashboardLayout>
  );
};

const fileToDataUrl = (f: File) =>
  new Promise<string>((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result as string);
    r.onerror = rej;
    r.readAsDataURL(f);
  });

const imgDim = (src: string) =>
  new Promise<{ w: number; h: number }>((res) => {
    const img = new Image();
    img.onload = () => res({ w: img.naturalWidth, h: img.naturalHeight });
    img.src = src;
  });

export const Route = createFileRoute("/_authenticated/dashboard/scanner")({
  component: Scanner,
});

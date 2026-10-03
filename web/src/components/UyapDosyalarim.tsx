import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  detectExtension,
  listUyapDosyalari,
  openUyapDosya,
  otherCells,
  type BridgeDosya,
  type DosyaListe,
  type ExtensionStatus,
} from "@/lib/uyap-bridge";
import { toast } from "sonner";
import { FolderOpen, Loader2, RefreshCw, ShieldCheck } from "lucide-react";

/**
 * UYAP'taki dosyaları JurisAI içinde gösterir. Liste, tarayıcı eklentisi üzerinden senin açık UYAP oturumundan okunur ve
 * yalnız bu sayfada tutulur: JurisAI sunucusuna gönderilmez. Evrakları çekme adımı şimdilik UYAP sekmesindeki seçim penceresinde
 * yapılır ("Evrakları seç" düğmesi o sekmeyi öne getirir).
 */
export const UyapDosyalarim = () => {
  const [extension, setExtension] = useState<ExtensionStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<{ message: string; code?: string } | null>(null);
  const [liste, setListe] = useState<DosyaListe | null>(null);
  const [filter, setFilter] = useState("");
  const [opening, setOpening] = useState<string | null>(null);

  const detect = useCallback(async () => setExtension(await detectExtension()), []);

  useEffect(() => {
    void detect();
    // Eklenti sayfadan sonra yüklenirse ya da güncellenirse kendini duyurur.
    const onReady = (event: MessageEvent) => {
      if (event.source === window && event.origin === window.location.origin && event.data?.source === "jurisai-extension" && event.data?.type === "READY")
        void detect();
    };
    window.addEventListener("message", onReady);
    return () => window.removeEventListener("message", onReady);
  }, [detect]);

  const load = async () => {
    setLoading(true);
    setError(null);
    const result = await listUyapDosyalari();
    setLoading(false);
    if (!result.ok) {
      setListe(null);
      setError({ message: result.error, code: result.code });
      return;
    }
    setListe(result.liste);
  };

  const open = async (item: BridgeDosya) => {
    setOpening(item.key);
    const result = await openUyapDosya(item.key);
    setOpening(null);
    if (!result.ok) {
      toast.error(result.error);
      if (result.code === "stale") void load();
      return;
    }
    toast.success("UYAP sekmesine geçildi: evrak seçim penceresi orada açılıyor.");
  };

  const shown = useMemo(() => {
    const needle = filter.trim().toLocaleLowerCase("tr");
    if (!liste || !needle) return liste?.items ?? [];
    return liste.items.filter((item) => item.cells.join(" ").toLocaleLowerCase("tr").includes(needle));
  }, [liste, filter]);

  return (
    <section className="mb-6 rounded-xl border bg-card p-5 space-y-4" data-testid="uyap-dosyalarim">
      <div className="flex flex-wrap items-center gap-2">
        <Badge>Yeni</Badge>
        <FolderOpen className="h-4 w-4 text-primary" />
        <h2 className="font-semibold">UYAP Dosyalarım</h2>
        {extension?.installed && (
          <Badge variant="outline" className="ml-auto">
            Eklenti {extension.version ? `v${extension.version}` : "bağlı"}
          </Badge>
        )}
      </div>

      {extension === null && (
        <p className="text-sm text-muted-foreground flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" /> Eklenti aranıyor…
        </p>
      )}

      {extension && !extension.installed && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm leading-relaxed">
          <p className="font-medium">JurisAI eklentisi bulunamadı.</p>
          <p className="text-muted-foreground mt-1">
            Aşağıdaki "Tarayıcı eklentisi" bölümünden eklentiyi kur (zaten kuruluysa en güncel sürüme geçmesi için UYAP sekmesini ve bu sayfayı
            yenile).
          </p>
          <Button size="sm" variant="outline" className="mt-2" onClick={() => void detect()}>
            <RefreshCw className="h-3.5 w-3.5 mr-2" /> Yeniden dene
          </Button>
        </div>
      )}

      {extension?.installed && (
        <>
          <p className="text-sm text-muted-foreground leading-relaxed">
            UYAP'a normal şekilde giriş yap ve dosya listesini (Dosya Sorgulama) bir sekmede açık tut. Aşağıdaki düğme listeyi senin açık oturumundan
            okur.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void load()} disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-2" />}
              {liste ? "Listeyi yenile" : "UYAP'taki dosyalarımı listele"}
            </Button>
          </div>
          {extension.connected === false && (
            <p className="text-xs text-amber-600">
              Eklentide bağlantı anahtarı yok: listeyi görebilirsin ama evrak aktarmak için anahtarı eklentiye yapıştırman gerekir (aşağıda).
            </p>
          )}
        </>
      )}

      {error && (
        <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
          {error.message}
        </div>
      )}

      {liste && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium" data-testid="uyap-dosya-sayisi">
              {liste.items.length} dosya
            </span>
            {liste.pages && liste.pages > 1 && (
              <Badge variant="secondary">
                UYAP'ta {liste.pages} sayfa var, şu an {liste.page ?? "?"}. sayfa görünüyor
              </Badge>
            )}
            <Input
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Ara: esas no, mahkeme…"
              className="ml-auto h-8 w-56"
              aria-label="Dosyalarda ara"
            />
          </div>
          {liste.pages && liste.pages > 1 && (
            <p className="text-xs text-muted-foreground">
              Diğer sayfalardaki dosyaları görmek için UYAP'ta o sayfaya geç ve listeyi yenile.
            </p>
          )}
          <ul className="divide-y rounded-lg border">
            {shown.map((item) => (
              <li key={item.key} className="flex flex-wrap items-center gap-3 p-3 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{item.esas || item.cells[0] || "Dosya"}</div>
                  {item.birim && <div className="text-muted-foreground">{item.birim}</div>}
                  {otherCells(item).length > 0 && (
                    <div className="text-xs text-muted-foreground truncate">{otherCells(item).join(" · ")}</div>
                  )}
                </div>
                <Button size="sm" variant="outline" disabled={opening === item.key} onClick={() => void open(item)}>
                  {opening === item.key ? <Loader2 className="h-3.5 w-3.5 mr-2 animate-spin" /> : null}
                  Evrakları seç
                </Button>
              </li>
            ))}
            {!shown.length && <li className="p-3 text-sm text-muted-foreground">Aramaya uyan dosya yok.</li>}
          </ul>
        </div>
      )}

      <p className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
        <ShieldCheck className="h-3.5 w-3.5 mt-0.5 shrink-0" />
        Dosya listesi yalnız bu sayfada, tarayıcında tutulur; JurisAI sunucusuna gönderilmez. Evrakları çekmeden önce hangilerinin aktarılacağını sen seçersin.
      </p>
    </section>
  );
};

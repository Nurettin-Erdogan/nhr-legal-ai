import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  EXTENSION_CHANGED_EVENT,
  describeListFailure,
  detectExtension,
  listUyapDosyalari,
  openUyapDosya,
  otherCells,
  currentJob,
  stopJob,
  type BridgeDosya,
  type CurrentJob,
  type ExtensionStatus,
} from "@/lib/uyap-bridge";
import { UyapDosyaPanel } from "@/components/UyapDosyaPanel";
import { UyapSyncAll } from "@/components/UyapSyncAll";
import { getSyncState, readResume, resumeIfInterrupted, setListe, subscribeSync } from "@/lib/uyap-sync-store";
import { toast } from "sonner";
import { ExternalLink, FolderOpen, Loader2, RefreshCw, ShieldCheck } from "lucide-react";

const UYAP_PORTALS = [
  { label: "UYAP Vatandaş Portalı'nı aç", url: "https://vatandas.uyap.gov.tr/" },
  { label: "UYAP Avukat Portalı'nı aç", url: "https://avukatbeta.uyap.gov.tr/" },
];
const WAIT_INTERVAL_MS = 4000;
const WAIT_MAX_TRIES = 45; // ~3 dakika

/**
 * UYAP'taki dosyaları JurisAI içinde gösterir. Liste, tarayıcı eklentisi üzerinden senin açık UYAP oturumundan okunur ve
 * yalnız bu sayfada tutulur: JurisAI sunucusuna gönderilmez. Evrak seçimi ve ilerleme JurisAI içinde yönetilir.
 */
export const UyapDosyalarim = () => {
  const [extension, setExtension] = useState<ExtensionStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<{ message: string; code?: string } | null>(null);
  // Liste depoda durur: başka sayfaya geçip dönünce yeniden taramak gerekmez.
  const liste = useSyncExternalStore(subscribeSync, () => getSyncState().liste, () => getSyncState().liste);
  const [filter, setFilter] = useState("");
  const [opening, setOpening] = useState<string | null>(null);
  const [panel, setPanel] = useState<BridgeDosya | null>(null);
  const [listPage, setListPage] = useState(0);
  // "Tüm dosyaları aktar" sürerken liste yenilenmez ve tek dosya işlemleri açılmaz (UYAP sekmesi aynı anda tek iş yürütür).
  const [syncing, setSyncing] = useState(() => getSyncState().running);

  const detect = useCallback(async () => setExtension(await detectExtension()), []);

  useEffect(() => {
    void detect();
    // Eklenti sayfadan sonra yüklenirse ya da güncellenirse kendini duyurur.
    const onReady = (event: MessageEvent) => {
      if (
        event.source === window &&
        event.origin === window.location.origin &&
        event.data?.source === "jurisai-extension" &&
        event.data?.type === "READY"
      )
        void detect();
    };
    window.addEventListener("message", onReady);
    const onChanged = () => void detect();
    window.addEventListener(EXTENSION_CHANGED_EVENT, onChanged);
    return () => {
      window.removeEventListener("message", onReady);
      window.removeEventListener(EXTENSION_CHANGED_EVENT, onChanged);
    };
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
    setListPage(0);
    if (resumeIfInterrupted(result.liste)) toast.success("Yarıda kalan aktarım kaldığı yerden sürüyor.");
  };

  // Sayfa yenilendiyse ve yarıda kalmış bir koşu varsa liste kendiliğinden okunur (koşu oradan sürer).
  useEffect(() => {
    if (!getSyncState().running && !getSyncState().liste && readResume()) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const open = async (item: BridgeDosya) => {
    setOpening(item.key);
    const result = await openUyapDosya(item.key, item.yargiTuru);
    setOpening(null);
    if (!result.ok) {
      toast.error(result.error);
      if (result.code === "stale") void load();
      return;
    }
    toast.success("UYAP sekmesine geçildi: evrak seçim penceresi orada açılıyor.");
  };

  const help = error ? describeListFailure(error.code, error.message) : null;
  const [gaveUp, setGaveUp] = useState(false);
  // Sayfa yenilendiğinde/yeniden açıldığında UYAP sekmesinde hâlâ süren iş (aktarım UYAP sekmesinde devam eder).
  const [remote, setRemote] = useState<CurrentJob | null>(null);
  const waitingForJob = error?.code === "busy";

  // UYAP'ta giriş yapılıp liste açılınca burası kendiliğinden dolsun: okuma-yalnız yoklama, en çok ~3 dakika.
  useEffect(() => {
    if (!help?.waiting) return;
    setGaveUp(false);
    let tries = 0;
    let stopped = false;
    let busy = false; // tam liste ~10 sn sürebilir: yoklamalar üst üste binmesin
    const timer = setInterval(async () => {
      if (busy) return;
      tries += 1;
      if (waitingForJob) {
        // Süren aktarım saatler sürebilir: vazgeçilmez; ilerleme gösterilir, iş bitince liste okunur.
        busy = true;
        const job = await currentJob();
        busy = false;
        if (stopped) return;
        setRemote(job);
        if (job?.busy) return;
      } else if (tries > WAIT_MAX_TRIES) {
        clearInterval(timer);
        if (!stopped) setGaveUp(true);
        return;
      }
      busy = true;
      const result = await listUyapDosyalari();
      busy = false;
      if (stopped) return;
      if (result.ok) {
        clearInterval(timer);
        setError(null);
        setRemote(null);
        setListe(result.liste);
        // Sayfa yenilenmeden önce süren "Tüm dosyaları aktar" koşusu varsa kaldığı yerden sürer.
        if (resumeIfInterrupted(result.liste)) toast.success("Yarıda kalan aktarım kaldığı yerden sürüyor.");
      }
    }, waitingForJob ? 2000 : WAIT_INTERVAL_MS);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [help?.waiting, error?.code, waitingForJob]);

  const remoteRun = remote?.status?.run;
  const remoteJob = remote?.status?.job;
  const stopRemote = async () => {
    if (remote?.tabId == null || !remoteJob) return;
    await stopJob(remote.tabId, remoteJob.id);
    toast.success("Durdurma istendi: süren evrak bitince aktarım durur.");
  };

  const shown = useMemo(() => {
    const needle = filter.trim().toLocaleLowerCase("tr");
    if (!liste || !needle) return liste?.items ?? [];
    return liste.items.filter((item) =>
      `${item.yargiTuru} ${item.cells.join(" ")}`.toLocaleLowerCase("tr").includes(needle),
    );
  }, [liste, filter]);
  const pageCount = Math.max(1, Math.ceil(shown.length / 50));
  const currentPage = Math.min(listPage, pageCount - 1);
  const visibleItems = useMemo(
    () => shown.slice(currentPage * 50, (currentPage + 1) * 50),
    [shown, currentPage],
  );
  // Yargı türüne göre gruplar (UYAP'ta her tür ayrı sorgulanır); sıra UYAP'taki sıradır.
  const groups = useMemo(() => {
    const map = new Map<string, BridgeDosya[]>();
    for (const item of visibleItems) {
      const label = item.yargiTuru || "Dosyalar";
      const group = map.get(label) ?? [];
      group.push(item);
      map.set(label, group);
    }
    return [...map.entries()];
  }, [visibleItems]);

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
          <p className="font-medium">Bu sayfa JurisAI eklentisiyle konuşamıyor.</p>
          {extension.error && (
            <p className="mt-1" role="status">
              Bağlantı kontrolü: {extension.error}
              {extension.code === "timeout" && " Bu sonuç eklentinin kurulu olmadığını kanıtlamaz; köprüden süre içinde yanıt alınamadı."}
            </p>
          )}
          <p className="text-muted-foreground mt-1">
            Eklenti kurulu değilse aşağıdaki "Tarayıcı eklentisi" bölümünden kur. Kuruluysa sırayla
            dene:
          </p>
          <ol className="text-muted-foreground mt-1 list-decimal pl-5 space-y-0.5">
            <li>
              Güncel JurisAI eklentisini aşağıdan indir; eski klasörden çalışıyorsa yeni klasörü
              yükle. Ardından <span className="font-mono text-xs">chrome://extensions</span> →
              JurisAI → ↻ (yeniden yükle).
            </li>
            <li>
              Sonra bu sayfayı F5 ile yenile (eklenti, sayfa açıldıktan sonra güncellendiyse sayfaya
              ancak yenilenince bağlanır).
            </li>
            <li>
              Hâlâ olmuyorsa eklentinin açık olduğundan emin ol; sayfa adresi{" "}
              <span className="font-mono text-xs">localhost:3000</span> olmalı.
            </li>
          </ol>
          <Button size="sm" variant="outline" className="mt-2" onClick={() => void detect()}>
            <RefreshCw className="h-3.5 w-3.5 mr-2" /> Yeniden dene
          </Button>
        </div>
      )}

      {extension?.installed && (
        <>
          <p className="text-sm text-muted-foreground leading-relaxed">
            UYAP'a normal şekilde giriş yap ve dosya listesini (Dosya Sorgulama) bir sekmede açık
            tut. Aşağıdaki düğme listeyi senin açık oturumundan okur.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void load()} disabled={loading || !!panel || syncing}>
              {loading ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4 mr-2" />
              )}
              {liste ? "Listeyi yenile" : "UYAP'taki dosyalarımı listele"}
            </Button>
          </div>
          {extension.connected === false && (
            <p className="text-xs text-amber-600">
              Eklentide bağlantı anahtarı yok: listeyi görebilirsin ama evrak aktarmak için aşağıdan
              "Anahtarı yenile" ya da "Bağlantı anahtarı oluştur"a bas; anahtar eklentiye
              kendiliğinden girilir.
            </p>
          )}
        </>
      )}

      {error && help && (
        <div
          role="alert"
          className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm space-y-2"
        >
          <p className="font-medium">{help.title}</p>
          {help.steps.length > 0 && (
            <ol className="list-decimal pl-5 space-y-0.5 text-muted-foreground">
              {help.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          )}
          {waitingForJob && (
            <div className="space-y-2" data-testid="uyap-remote-job">
              <p className="flex items-center gap-2 text-sm">
                <Loader2 className="h-4 w-4 animate-spin text-primary" />
                {remoteRun
                  ? `Evrak aktarılıyor: ${remoteRun.done}/${remoteRun.total}${remoteRun.current ? ` · ${remoteRun.current}` : ""}`
                  : remoteJob?.phase || "UYAP sekmesindeki işlem bekleniyor…"}
              </p>
              {remoteRun && remoteRun.total > 0 && <Progress value={Math.round((remoteRun.done / remoteRun.total) * 100)} />}
              {remoteJob?.kind === "pull" && (
                <Button size="sm" variant="outline" onClick={() => void stopRemote()} data-testid="uyap-remote-stop">
                  Aktarımı durdur
                </Button>
              )}
              <p className="text-xs text-muted-foreground">
                Aktarılan evraklar hesabına kaydediliyor. Bu dosya bitince liste burada görünür
                {readResume() ? " ve aktarım kalan dosyalarla kendiliğinden sürer." : "."}
              </p>
            </div>
          )}
          {help.waiting && !waitingForJob && (
            <>
              <div className="flex flex-wrap gap-2 pt-1">
                {UYAP_PORTALS.map((portal) => (
                  <Button
                    key={portal.url}
                    size="sm"
                    variant="outline"
                    onClick={() => window.open(portal.url, "_blank", "noopener,noreferrer")}
                  >
                    {portal.label}
                    <ExternalLink className="h-3.5 w-3.5 ml-2" />
                  </Button>
                ))}
              </div>
              <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                {gaveUp ? (
                  'Beklemeyi bıraktım: UYAP hazır olunca "Listeyi yenile"ye bas.'
                ) : (
                  <>
                    <Loader2 className="h-3 w-3 animate-spin" /> Bekleniyor: UYAP'ta dosya listesini
                    açınca burası kendiliğinden güncellenir.
                  </>
                )}
              </p>
            </>
          )}
        </div>
      )}

      {liste && (
        <div className="space-y-3">
          <div
            role={liste.complete ? "status" : "alert"}
            className={`rounded-lg border p-3 text-sm ${liste.complete ? "border-emerald-500/30 bg-emerald-500/5" : "border-amber-500/30 bg-amber-500/5"}`}
            data-testid="uyap-list-completeness"
          >
            <p className="font-medium">
              {liste.complete
                ? "Dosya listesi taraması tamamlandı"
                : "Dosya listesinin tamamı doğrulanamadı"}
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              {liste.complete
                ? "Eklenti, bu sorgudaki yargı türlerinin sayfalarını tamamladı. Bu sonuç yalnız açık hesabın erişebildiği dosyaları kapsar."
                : "Görünen dosyaları kullanabilirsin; bu liste tüm dosyaların olarak kabul edilmemeli. Güncel eklentiyle yeniden tara."}
            </p>
            {liste.errors.length > 0 && (
              <ul className="list-disc pl-5 mt-2 text-xs">
                {liste.errors.map((message, index) => (
                  <li key={index}>{message}</li>
                ))}
              </ul>
            )}
          </div>
          <UyapSyncAll
            liste={liste}
            disabled={loading || !!panel || opening !== null || extension?.connected === false}
            onRunningChange={setSyncing}
          />
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
              onChange={(event) => {
                setFilter(event.target.value);
                setListPage(0);
              }}
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
          {groups.map(([label, items]) => (
            <div key={label} className="space-y-1" data-testid="uyap-yargi-grubu">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {label} · {items.length} dosya
              </h3>
              <ul className="divide-y rounded-lg border">
                {items.map((item) => (
                  <li key={item.key} className="flex flex-wrap items-center gap-3 p-3 text-sm">
                    <div className="min-w-0 flex-1">
                      <div className="font-medium">{item.esas || item.cells[0] || "Dosya"}</div>
                      {item.birim && <div className="text-muted-foreground">{item.birim}</div>}
                      <div className="text-xs text-muted-foreground truncate">
                        {[item.role, item.tur, item.acilis && `Açılış ${item.acilis}`, item.durum]
                          .filter(Boolean)
                          .join(" · ") || otherCells(item).join(" · ")}
                      </div>
                    </div>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={loading || opening !== null || syncing}
                      onClick={() => void open(item)}
                      title="Evrak seçimini UYAP sekmesinde aç"
                    >
                      {opening === item.key ? (
                        <Loader2 className="h-3.5 w-3.5 mr-2 animate-spin" />
                      ) : null}
                      UYAP'ta aç
                    </Button>
                    <Button
                      size="sm"
                      disabled={loading || opening !== null || syncing}
                      onClick={() => setPanel(item)}
                      data-testid="uyap-evraklari-sec"
                    >
                      Evrakları seç
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {!shown.length && (
            <p className="rounded-lg border p-3 text-sm text-muted-foreground">
              Aramaya uyan dosya yok.
            </p>
          )}
          {shown.length > 0 && (
            <div
              className="flex flex-wrap items-center gap-2 text-xs"
              data-testid="uyap-local-pagination"
            >
              <span>
                {shown.length} eşleşme · {currentPage * 50 + 1}–
                {Math.min((currentPage + 1) * 50, shown.length)} gösteriliyor
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={currentPage === 0}
                onClick={() => setListPage(currentPage - 1)}
              >
                Önceki
              </Button>
              <span>
                {currentPage + 1} / {pageCount}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={currentPage + 1 >= pageCount}
                onClick={() => setListPage(currentPage + 1)}
              >
                Sonraki
              </Button>
            </div>
          )}
        </div>
      )}

      {panel && <UyapDosyaPanel key={panel.key} dosya={panel} onClose={() => setPanel(null)} />}

      <p className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
        <ShieldCheck className="h-3.5 w-3.5 mt-0.5 shrink-0" />
        Dosya listesi bu sayfada, tarayıcında tutulur. Evraklar yalnız sen başlatınca aktarılır: tek dosyada hangilerinin
        aktarılacağını seçersin, "Tüm dosyaları aktar" ise onayından sonra hepsini aktarır. Aktarılan dosyanın numarası, birimi ve
        UYAP listesindeki durumu dava kaydına yazılır.
      </p>
    </section>
  );
};

import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/components/AuthContext";
import { UyapDosyalarim } from "@/components/UyapDosyalarim";
import { UyapCaseLinks } from "@/components/UyapCaseLinks";
import { UyapAccountBinding } from "@/components/UyapAccountBinding";
import {
  detectExtension,
  EXTENSION_CHANGED_EVENT,
  setExtensionKey,
  type ExtensionStatus,
} from "@/lib/uyap-bridge";
import { supabase } from "@/integrations/supabase/client";
import { expandDroppedFiles, importEntries, type ImportResult } from "@/lib/uyap-import";
import { ALLOWED_EXTENSIONS } from "@/lib/uyap";
import { downloadExtensionPackage } from "@/lib/office-api";
import { toast } from "sonner";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Loader2,
  ShieldCheck,
  UploadCloud,
  Info,
  Copy,
  Download,
  Puzzle,
  RefreshCw,
} from "lucide-react";

const UYAP_PORTALS = [
  { label: "UYAP Avukat Portalı", url: "https://avukatbeta.uyap.gov.tr/" },
  { label: "UYAP Vatandaş Portalı", url: "https://vatandas.uyap.gov.tr/" },
  { label: "e-Devlet Kapısı", url: "https://www.turkiye.gov.tr/" },
];

const newToken = () =>
  `jsai_${crypto.randomUUID().replace(/-/g, "")}${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;

/** Kişiye özel paketi indirir: bağlantı anahtarı içindedir, kurulduktan sonra anahtar girmek gerekmez. */
const downloadExtension = async (): Promise<boolean> => {
  try {
    const href = URL.createObjectURL(await downloadExtensionPackage());
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = "jurisai-avukat.zip";
    anchor.click();
    URL.revokeObjectURL(href);
    return true;
  } catch (error) {
    toast.error(error instanceof Error ? error.message : "Eklenti indirilemedi. Lütfen tekrar dene.");
    return false;
  }
};

const UyapConnect = () => {
  const { user } = useAuth();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [opened, setOpened] = useState(false);
  // Düz anahtar yalnız oluşturulduğu anda bu oturumda bellektedir; sunucuda yalnız özeti saklanır.
  const [token, setToken] = useState<string | null>(null);
  const [activeToken, setActiveToken] = useState<{
    prefix: string;
    lastUsed: string | null;
  } | null>(null);
  const [tokenBusy, setTokenBusy] = useState(false);
  const [extension, setExtension] = useState<ExtensionStatus | null>(null);
  const [downloaded, setDownloaded] = useState(false);

  useEffect(() => {
    let alive = true;
    const detect = () => void detectExtension(2500).then((status) => alive && setExtension(status));
    detect();
    window.addEventListener(EXTENSION_CHANGED_EVENT, detect);
    // Kurulum bitince sayfayı yenilemeden "Bağlı"ya geçer.
    const poll = window.setInterval(detect, 3000);
    return () => {
      alive = false;
      window.clearInterval(poll);
      window.removeEventListener(EXTENSION_CHANGED_EVENT, detect);
    };
  }, []);

  useEffect(() => {
    if (!user) return;
    void supabase
      .from("uyap_ingest_tokens")
      .select("token_prefix,last_used_at")
      .eq("owner_id", user.id)
      .eq("revoked", false)
      .order("created_at", { ascending: false })
      .limit(1)
      .then(({ data }) => {
        const row = data?.[0];
        setActiveToken(
          row
            ? { prefix: String(row.token_prefix ?? ""), lastUsed: row.last_used_at ?? null }
            : null,
        );
      });
  }, [user]);

  const createToken = useCallback(
    async (rotate = false) => {
      if (!user) return;
      setTokenBusy(true);
      try {
        if (rotate) {
          await supabase
            .from("uyap_ingest_tokens")
            .update({ revoked: true })
            .eq("owner_id", user.id);
        }
        const value = newToken();
        const { error } = await supabase
          .from("uyap_ingest_tokens")
          .insert({ owner_id: user.id, token: value, label: "Tarayıcı eklentisi" });
        if (error) throw error;
        setToken(value);
        setActiveToken({ prefix: value.slice(0, 9), lastUsed: null });
        // Eklentinin kendi onay penceresinde kullanıcı izin verirse anahtar yazılır.
        const written = await setExtensionKey(value);
        toast.success(
          written
            ? "Anahtar oluşturuldu ve onayınla eklentiye girildi"
            : rotate
              ? "Yeni anahtar oluşturuldu"
              : "Bağlantı anahtarı hazır",
        );
      } catch {
        toast.error("Anahtar oluşturulamadı");
      } finally {
        setTokenBusy(false);
      }
    },
    [user],
  );

  // Eklenti kurulu ama bağlı değilse anahtar kendiliğinden oluşturulup eklentiye gönderilir; eklentinin onay penceresi
  // açılır (kullanıcı izin vermeden anahtar yazılmaz). Oturum başına bir kez denenir, reddedilirse tekrar sorulmaz.
  const autoPaired = useRef(false);
  useEffect(() => {
    if (!user || autoPaired.current || extension?.installed !== true || extension.connected) return;
    autoPaired.current = true;
    try {
      if (window.sessionStorage.getItem("uyap-auto-pair")) return;
      window.sessionStorage.setItem("uyap-auto-pair", "1");
    } catch {
      /* oturum belleği yoksa yine de bir kez denenir */
    }
    void createToken(false);
  }, [user, extension, createToken]);

  const handleFiles = useCallback(
    async (files: File[]) => {
      if (!user || !files.length) return;
      setBusy(true);
      setResult(null);
      setProgress(0);
      const startedAt = Date.now();

      const { data: run } = await supabase
        .from("uyap_sync_runs")
        .insert({
          owner_id: user.id,
          status: "running",
          archive_name: files
            .map((f) => f.name)
            .join(", ")
            .slice(0, 200),
        })
        .select("id")
        .single();

      try {
        const entries = await expandDroppedFiles(files);
        if (!entries.length)
          throw new Error("İçe aktarılabilir belge bulunamadı (pdf, udf, docx, zip, eyp ...)");

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
              found_count: res.found,
              inserted_count: res.inserted,
              skipped_count: res.skipped,
              error_message: res.errors.join(" | ") || null,
              duration_ms: Date.now() - startedAt,
            })
            .eq("id", run.id);
        }
        setResult(res);
        if (res.failed)
          toast.warning(`${res.inserted} belge aktarıldı, ${res.failed} belge aktarılmadı`);
        else toast.success(`${res.inserted} belge JurisAI'ya aktarıldı`);
      } catch (e) {
        const message = e instanceof Error ? e.message : "Aktarım başarısız";
        if (run?.id) {
          await supabase
            .from("uyap_sync_runs")
            .update({
              status: "failed",
              error_message: message,
              duration_ms: Date.now() - startedAt,
            })
            .eq("id", run.id);
        }
        toast.error(message);
      } finally {
        setBusy(false);
      }
    },
    [user],
  );

  const installed = extension?.installed === true;
  const connected = installed && extension?.connected === true;

  return (
    <DashboardLayout
      title="UYAP'a Bağlan"
      subtitle="UYAP'ta kendi oturumunu aç; belgeleri JurisAI hesabına sen onaylayarak aktar."
    >
      {/* 1. Eklenti bağlantısı */}
      <section className="mb-6 space-y-4 rounded-xl border bg-card p-5" data-testid="uyap-extension">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Puzzle className="h-4 w-4 text-primary" />
            <h2 className="font-semibold">UYAP eklentisi</h2>
          </div>
          {extension === null ? (
            <Badge variant="outline">Kontrol ediliyor…</Badge>
          ) : connected ? (
            <Badge className="bg-emerald-600 hover:bg-emerald-600">Bağlı</Badge>
          ) : installed ? (
            <Badge variant="secondary">Kurulu · anahtar gerekli</Badge>
          ) : (
            <Badge variant="outline">Kurulu değil</Badge>
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          UYAP oturumun tarayıcında kalır; eklenti yalnız seçtiğin evrakları JurisAI hesabına
          aktarır. Şifre ve e-imza hiçbir zaman okunmaz.
        </p>

        {!installed && extension !== null && (
          <div className="space-y-3">
            <Button
              onClick={() =>
                void downloadExtension().then((ok) => {
                  if (ok) setDownloaded(true);
                })
              }
            >
              <Download className="mr-2 h-4 w-4" /> Eklentiyi indir
            </Button>
            <p className="text-xs text-muted-foreground">
              Paket hesabına özel hazırlanır; kurulduktan sonra anahtar girmen gerekmez.
            </p>
            <details open={downloaded} className="text-sm text-muted-foreground">
              <summary className="cursor-pointer select-none font-medium text-foreground">
                Kurulum adımları (1 dakika)
              </summary>
              <ol className="mt-2 list-decimal space-y-2 pl-5">
                <li>İndirilen .zip dosyasına sağ tıkla → "Tümünü ayıkla".</li>
                <li>
                  Chrome'da yeni sekme aç, adres çubuğuna{" "}
                  <span className="font-mono text-xs">chrome://extensions</span> yaz.{" "}
                  <button
                    type="button"
                    className="font-medium text-primary underline-offset-2 hover:underline"
                    onClick={() => {
                      void navigator.clipboard.writeText("chrome://extensions");
                      toast.success("Adres kopyalandı; yeni sekmeye yapıştır");
                    }}
                  >
                    Adresi kopyala
                  </button>
                </li>
                <li>Sağ üstteki "Geliştirici modu" anahtarını aç.</li>
                <li>
                  "Paketlenmemiş öğe yükle"ye bas, ayıkladığın klasörü seç. Bu sayfa kendiliğinden
                  "Bağlı"ya döner.
                </li>
              </ol>
            </details>
          </div>
        )}

        {installed && !connected && (
          <div className="space-y-2">
            <Button onClick={() => void createToken(false)} disabled={tokenBusy}>
              {tokenBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Eklentiyi hesabıma bağla
            </Button>
            <p className="text-xs text-muted-foreground">
              Eklenti algılanınca anahtar kendiliğinden hazırlanır; açılan eklenti penceresinde
              "Onayla"ya basman yeterli. Pencere açılmadıysa bu düğmeyi kullan.
            </p>
          </div>
        )}

        {token && (
          <div className="space-y-2">
            <div className="flex gap-2">
              <Input readOnly value={token} className="font-mono text-xs" />
              <Button
                variant="secondary"
                onClick={() => {
                  void navigator.clipboard.writeText(token);
                  toast.success("Anahtar kopyalandı");
                }}
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
            <p className="text-xs font-medium text-amber-600">
              Anahtar eklentiye otomatik girilir. Girilmediyse şimdi kopyalayıp eklentiye yapıştır;
              bu sayfa kapandığında bir daha gösterilmez.
            </p>
          </div>
        )}

        <details className="text-sm text-muted-foreground">
          <summary className="cursor-pointer select-none font-medium text-foreground">
            Gelişmiş ayarlar
          </summary>
          <div className="mt-3 space-y-3">
            {activeToken && !token && (
              <p className="text-xs" data-testid="uyap-token-hidden">
                Etkin anahtar: <span className="font-mono">{activeToken.prefix}…</span>
                {activeToken.lastUsed
                  ? ` · son kullanım ${new Date(activeToken.lastUsed).toLocaleString("tr-TR")}`
                  : " · henüz kullanılmadı"}
                . Güvenlik için anahtar yalnız oluşturulurken gösterilir.
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => void createToken(Boolean(activeToken))}
                disabled={tokenBusy}
              >
                <RefreshCw className="mr-2 h-3.5 w-3.5" />
                {activeToken ? "Anahtarı yenile" : "Bağlantı anahtarı oluştur"}
              </Button>
              {installed && (
                <Button size="sm" variant="outline" onClick={() => void downloadExtension()}>
                  <Download className="mr-2 h-3.5 w-3.5" /> Yeni paket indir (eski anahtar iptal olur)
                </Button>
              )}
            </div>
            <p className="text-xs leading-relaxed">
              Anahtar hesabına özeldir, kimseyle paylaşma. Şüphede "Anahtarı yenile" ile eskisini
              geçersiz kıl. Eklenti ayarlarındaki "Otomatik aktarım" müvekkil verisi içerdiğinden
              varsayılan olarak <strong>kapalıdır</strong>; yalnız yetkili olduğun dosyalarda ve
              müvekkilini bilgilendirdiysen aç.
            </p>
          </div>
        </details>
      </section>

      {/* 2. Dosyalar */}
      <UyapDosyalarim />

      {/* 3. Aktarılan belgeler */}
      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        <UyapAccountBinding />
        <UyapCaseLinks />
      </div>

      {/* 4. Elle aktarım */}
      <details className="mb-6 rounded-xl border bg-card p-5 text-sm">
        <summary className="cursor-pointer select-none font-semibold">
          Eklentisiz aktarım: UYAP'tan indirdiğin dosyaları yükle
        </summary>
        <div className="mt-4 grid gap-6 lg:grid-cols-[1fr_1.2fr]">
          <div className="space-y-3">
            <p className="leading-relaxed text-muted-foreground">
              Girişi resmî sayfada sen yaparsın; JurisAI giriş bilgilerini görmez. Dosya listesinden
              belgeleri veya arşivi indirip yandaki alana bırak.
            </p>
            <div className="grid gap-2">
              {UYAP_PORTALS.map((p) => (
                <Button
                  key={p.url}
                  variant="outline"
                  size="sm"
                  className="justify-between"
                  onClick={() => {
                    window.open(p.url, "_blank", "noopener,noreferrer");
                    setOpened(true);
                  }}
                >
                  {p.label}
                  <ExternalLink className="h-4 w-4" />
                </Button>
              ))}
            </div>
            {opened && (
              <p className="flex items-start gap-1.5 text-xs text-primary">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                Portal açıldı. İndirme bitince dosyaları yandaki alana bırak.
              </p>
            )}
            <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
              UYAP'ın açık bir API'si yoktur; kimlik bilgilerinin üçüncü bir uygulamada saklanması
              KVKK'ya ve portal şartlarına aykırıdır. Bu yüzden oturum tarayıcında kalır.
            </p>
          </div>

          <div className="space-y-4">
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                void handleFiles(Array.from(e.dataTransfer.files));
              }}
              onClick={() => inputRef.current?.click()}
              className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
                dragging
                  ? "border-primary bg-primary/10"
                  : "border-muted-foreground/30 hover:border-primary/50"
              }`}
            >
              {busy ? (
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
              ) : (
                <UploadCloud className="h-8 w-8 text-primary" />
              )}
              <p className="text-sm font-medium">
                {busy ? "Belgeler işleniyor..." : "Dosyaları buraya bırak veya seç"}
              </p>
              <p className="text-xs text-muted-foreground">
                UYAP arşivi (.zip / .eyp) veya tek tek belgeler (.pdf, .udf, .odt, .docx, .html,
                .tif, .jpg)
              </p>
            </div>

            <input
              ref={inputRef}
              type="file"
              multiple
              accept={ALLOWED_EXTENSIONS.map((ext) => `.${ext}`).join(",")}
              className="hidden"
              onChange={(e) => {
                const files = Array.from(e.target.files ?? []);
                e.target.value = "";
                void handleFiles(files);
              }}
            />

            {busy && <Progress value={progress} />}

            {result && (
              <div
                className={`space-y-2 rounded-lg border p-3 text-xs ${result.failed ? "border-amber-500/30 bg-amber-500/5" : "border-emerald-500/30 bg-emerald-500/5"}`}
              >
                <div
                  className={`flex items-center gap-2 font-semibold ${result.failed ? "text-amber-700 dark:text-amber-400" : "text-emerald-700 dark:text-emerald-400"}`}
                >
                  {result.failed ? (
                    <AlertTriangle className="h-4 w-4" />
                  ) : (
                    <CheckCircle2 className="h-4 w-4" />
                  )}
                  {result.failed ? "Aktarım kısmen tamamlandı" : "Aktarım tamamlandı"}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline">Bulunan: {result.found}</Badge>
                  <Badge variant="outline">Eklenen: {result.inserted}</Badge>
                  <Badge variant="outline">Atlanan: {result.skipped}</Badge>
                  {result.failed > 0 && <Badge variant="destructive">Hatalı: {result.failed}</Badge>}
                </div>
                {result.errors.map((error) => (
                  <p key={error} className="text-destructive">
                    {error}
                  </p>
                ))}
                <p className="text-muted-foreground">
                  Belgeler dosya no · birim · tarih · tür bilgisiyle kaydedildi. Dava kapsamlı AI
                  aramasında kullanmak için belgeyi ilgili davaya ayrıca bağla.
                </p>
              </div>
            )}

            <Button variant="outline" size="sm" className="w-full" asChild>
              <a href="/dashboard/files">Dosyalar sayfasına git</a>
            </Button>
          </div>
        </div>
      </details>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/uyap")({
  component: UyapConnect,
  head: () => ({
    meta: [
      { title: "UYAP'a Bağlan · JurisAI" },
      {
        name: "description",
        content: "UYAP oturumunu güvenle aç, belgeleri onayınla JurisAI'ya aktar.",
      },
      { property: "og:title", content: "UYAP'a Bağlan · JurisAI" },
      { property: "og:description", content: "UYAP dosyalarını güvenli akışla JurisAI'ya aktar." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
});

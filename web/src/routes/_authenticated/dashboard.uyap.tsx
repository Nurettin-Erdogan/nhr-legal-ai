import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/components/AuthProvider";
import { UyapDosyalarim } from "@/components/UyapDosyalarim";
import { UyapRunHistory } from "@/components/UyapRunHistory";
import { UyapCaseLinks } from "@/components/UyapCaseLinks";
import { setExtensionKey } from "@/lib/uyap-bridge";
import { supabase } from "@/integrations/supabase/client";
import { expandDroppedFiles, importEntries, type ImportResult } from "@/lib/uyap-import";
import { ALLOWED_EXTENSIONS } from "@/lib/uyap";
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

const downloadExtension = async (file = "jurisai-avukat.zip") => {
  try {
    const response = await fetch(`/${file}`);
    if (!response.ok) throw new Error(String(response.status));
    const href = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = file;
    anchor.click();
    URL.revokeObjectURL(href);
  } catch {
    toast.error("Eklenti indirilemedi. Lütfen tekrar dene.");
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

  return (
    <DashboardLayout
      title="UYAP'a Bağlan"
      subtitle="UYAP'ta kendi oturumunu aç; belgeleri JurisAI hesabına sen onaylayarak aktar."
    >
      <UyapDosyalarim />
      <UyapRunHistory />
      <UyapCaseLinks />

      {/* Tarayıcı eklentisi */}
      <section className="mb-6 rounded-xl border bg-card p-5 space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">Önerilen</Badge>
          <Puzzle className="h-4 w-4 text-primary" />
          <h2 className="font-semibold">Tarayıcı eklentisi ile aktarım</h2>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">
          JurisAI eklentisini Chrome'a kurarsın ve UYAP'ta kendi oturumunu açarsın. Yukarıdaki "UYAP
          Dosyalarım" bölümünden dosyaları listeleyip evrakları seçerek aktarımı JurisAI içinden
          yönetirsin. Belgeler senin oturumunla indirilip doğrudan JurisAI hesabına kaydedilir;
          şifre/e-imza hiçbir zaman okunmaz veya sunucuya gönderilmez. Varsayılan olarak yalnızca
          düğmeye bastığın evrak gönderilir.
        </p>

        <ol className="text-sm space-y-2 list-decimal pl-5 text-muted-foreground">
          <li>
            Eklentiyi indir ve <span className="font-mono text-xs">chrome://extensions</span> →
            "Geliştirici modu" → "Paketlenmemiş öğe yükle" ile klasörü seç.
          </li>
          <li>
            Aşağıdan bağlantı anahtarı oluştur; bağlı eklentiye otomatik girilir. Bağlanamazsa
            anahtarı eklentiye kendin yapıştır.
          </li>
          <li>
            UYAP'a giriş yaptıktan sonra JurisAI'da "Dosyalarımı listele" → "Evrakları seç" →
            "Seçilenleri JurisAI'ya aktar" akışını kullan.
          </li>
        </ol>
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs leading-relaxed text-muted-foreground">
          <p className="font-semibold text-foreground mb-1">İsteğe bağlı: otomatik aktarım</p>
          Eklenti ayarlarından "Otomatik aktarım"ı açarsan, UYAP'ta bir dosyayı görüntülediğinde
          dosyanın evrakları ve künyesi (mahkeme, esas no, taraf adı) hesabına kendiliğinden
          gönderilir. Müvekkil verisi içerdiğinden varsayılan olarak <strong>kapalıdır</strong>;
          yalnızca yetkili olduğun dosyalarda ve müvekkilini bilgilendirdiysen aç. Aktarılan
          belgeleri bilgisayarına da kaydetmek ayrı bir seçenektir ve yine kapalı gelir.
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          {activeToken ? (
            <Button variant="outline" onClick={() => void createToken(true)} disabled={tokenBusy}>
              <RefreshCw className="h-4 w-4 mr-2" /> Anahtarı yenile
            </Button>
          ) : (
            <Button variant="outline" onClick={() => void createToken(false)} disabled={tokenBusy}>
              {tokenBusy ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
              Bağlantı anahtarı oluştur
            </Button>
          )}
          <Button variant="default" onClick={() => void downloadExtension()}>
            <Download className="h-4 w-4 mr-2" /> JurisAI bağlantı eklentisini indir (.zip)
          </Button>
        </div>

        {token && (
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
        )}
        {activeToken && !token && (
          <p className="text-xs text-muted-foreground" data-testid="uyap-token-hidden">
            Etkin anahtar: <span className="font-mono">{activeToken.prefix}…</span>
            {activeToken.lastUsed
              ? ` · son kullanım ${new Date(activeToken.lastUsed).toLocaleString("tr-TR")}`
              : " · henüz kullanılmadı"}
            . Güvenlik için anahtar yalnız oluşturulurken gösterilir. Eklentideki anahtarı
            kaybettiysen "Anahtarı yenile" ile yenisini oluştur.
          </p>
        )}
        {token && (
          <p className="text-xs font-medium text-amber-600">
            Bağlı eklentiye anahtar otomatik girilir. Otomatik bağlantı başarısızsa şimdi kopyalayıp
            yapıştır; bu sayfa kapandığında bir daha gösterilmeyecek.
          </p>
        )}
        <p className="text-[11px] text-muted-foreground">
          Anahtar hesabına özeldir, kimseyle paylaşma. Şüpheli durumda "Anahtarı yenile" ile eski
          anahtarı geçersiz kılabilirsin.
        </p>
      </section>

      <div className="grid gap-6 lg:grid-cols-[1.1fr_1fr]">
        {/* 1. Adım */}
        <section className="rounded-xl border bg-card p-5 space-y-4">
          <div className="flex items-center gap-2">
            <Badge>1. Adım</Badge>
            <h2 className="font-semibold">UYAP oturumunu aç</h2>
          </div>
          <p className="text-sm text-muted-foreground leading-relaxed">
            Girişi doğrudan resmî UYAP/e-Devlet sayfasında sen yaparsın (e-imza, mobil imza veya
            e-Devlet şifresi). JurisAI bu bilgileri görmez, saklamaz ve iletmez. Portal yeni sekmede
            açılır; dosya listesinden ilgili belgeleri veya dosya arşivini indirirsin.
          </p>
          <div className="grid gap-2">
            {UYAP_PORTALS.map((p) => (
              <Button
                key={p.url}
                variant={p.url.includes("avukat") ? "default" : "outline"}
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
            <p className="text-xs text-primary flex items-start gap-1.5">
              <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              Portal açıldı. İndirme tamamlandıktan sonra dosyaları yandaki alana bırak.
            </p>
          )}
          <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 text-[11px] leading-relaxed">
            <div className="flex items-center gap-2 font-semibold text-primary mb-1">
              <ShieldCheck className="h-3.5 w-3.5" /> Neden şifre istemiyoruz?
            </div>
            UYAP'ın açık bir API'si yoktur ve e-imza/e-Devlet kimlik bilgilerinin üçüncü bir
            uygulamada saklanması hem KVKK hem de portal kullanım şartlarına aykırıdır. Bu nedenle
            oturum senin tarayıcında kalır; JurisAI yalnızca senin indirdiğin belgeleri işler.
          </div>
        </section>

        {/* 2. Adım */}
        <section className="rounded-xl border bg-card p-5 space-y-4">
          <div className="flex items-center gap-2">
            <Badge>2. Adım</Badge>
            <h2 className="font-semibold">İndirilen dosyaları aktar</h2>
          </div>

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
              UYAP arşivi (.zip / .eyp) veya tek tek belgeler (.pdf, .udf, .odt, .docx, .html, .tif,
              .jpg)
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

          <Button variant="outline" className="w-full" asChild>
            <a href="/dashboard/files">Dosyalar sayfasına git</a>
          </Button>
        </section>
      </div>
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

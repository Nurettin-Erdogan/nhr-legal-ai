import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  BellRing,
  CalendarDays,
  Check,
  CheckCheck,
  ChevronRight,
  Clock3,
  FileText,
  FolderOpen,
  ListChecks,
  Loader2,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { useAuth } from "@/components/AuthContext";
import { Link } from "@/lib/router-compat";
import {
  loadBureau,
  decideBureau,
  type BureauData,
  type BureauProposal,
} from "@/lib/bureau-assistant";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { BureauReview, BureauWorkHistory } from "@/components/BureauReview";

const when = (date: string) =>
  new Intl.DateTimeFormat("tr-TR", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Istanbul",
  }).format(new Date(date));
const message = (error: unknown) =>
  error instanceof Error ? error.message : "İşlem tamamlanamadı.";

export function BureauAssistant() {
  const { user } = useAuth();
  const requestVersion = useRef(0);
  const [data, setData] = useState<BureauData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<BureauProposal | null>(null);
  const [reviewing, setReviewing] = useState<BureauProposal | null>(null);
  const [title, setTitle] = useState("");
  const [action, setAction] = useState<"approve" | "dismiss">("approve");
  const refresh = useCallback(async (signal?: AbortSignal) => {
    const version = ++requestVersion.current;
    setLoading(true);
    setError("");
    try {
      const value = await loadBureau(signal);
      if (!signal?.aborted && version === requestVersion.current) setData(value);
    } catch (e) {
      if (!signal?.aborted && version === requestVersion.current) {
        setError(message(e));
        setData(null);
      }
    } finally {
      if (!signal?.aborted && version === requestVersion.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const requests = requestVersion;
    setData(null);
    setSelected(null);
    setReviewing(null);
    void refresh(controller.signal);
    return () => {
      ++requests.current;
      controller.abort();
    };
  }, [refresh, user?.id]);
  const choose = (proposal: BureauProposal, decision: "approve" | "dismiss") => {
    setSelected(proposal);
    setTitle(proposal.title);
    setAction(decision);
  };
  const submit = async () => {
    if (!selected || busy) return;
    setBusy(true);
    try {
      const result = await decideBureau(selected.key, action, title.trim());
      toast.success(
        result.status === "dismissed"
          ? "Öneri reddedildi. Kaynak kayıt korundu."
          : result.repeated
            ? "Bu öneri daha önce işlendi; yeni kayıt oluşturulmadı."
            : selected.kind === "hearing"
              ? "Duruşma takvime eklendi."
              : "İnceleme görevi oluşturuldu.",
      );
      setSelected(null);
      await refresh();
    } catch (e) {
      toast.error(message(e));
    } finally {
      setBusy(false);
    }
  };
  const proposals = data?.proposals ?? [];
  const visible = proposals.filter(
    (p) =>
      (filter === "all" || p.kind === filter) &&
      `${p.title} ${p.case_title} ${p.source_label}`
        .toLocaleLowerCase("tr")
        .includes(search.toLocaleLowerCase("tr")),
  );
  return (
    <DashboardLayout title="Büro Asistanı" subtitle="Günün işleri, tek bir çalışma alanında">
      <div className="mx-auto max-w-7xl space-y-6">
        <section className="relative overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-primary/10 via-card to-card p-6 sm:p-8">
          <div
            className="absolute -right-14 -top-24 h-72 w-72 rounded-full border border-primary/10"
            aria-hidden="true"
          />
          <div className="relative flex flex-wrap items-start justify-between gap-5">
            <div className="max-w-2xl">
              <p className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[.18em] text-primary">
                <Sparkles className="h-4 w-4" /> Büro çalışma masanız
              </p>
              <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
                Takip bizde. Son söz sizde.
              </h1>
              <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">
                Yeni belgeleri gözden geçirin, yaklaşan duruşmaları planlayın. Önerileri inceleyin;
                yalnız onayladıklarınız göreve veya takvim kaydına dönüşsün.
              </p>
            </div>
            <Button variant="outline" onClick={() => void refresh()} disabled={loading || busy}>
              <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              Yenile
            </Button>
          </div>
          <div className="relative mt-7 grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[
              {
                label: "Onay bekleyen öneri",
                value: data ? proposals.length : "—",
                icon: Sparkles,
              },
              {
                label: "7 günde duruşma",
                value: data?.counts.upcoming_hearings ?? "—",
                icon: CalendarDays,
              },
              { label: "Açık görev", value: data?.counts.open_tasks ?? "—", icon: ListChecks },
              { label: "Gecikmiş görev", value: data?.counts.overdue_tasks ?? "—", icon: Clock3 },
            ].map(({ label, value, icon: Icon }) => (
              <div key={label} className="rounded-xl border border-border/80 bg-background/60 p-4">
                <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                  {label}
                  <Icon className="h-4 w-4" />
                </div>
                <p className="mt-3 text-2xl font-semibold tabular-nums">{value}</p>
              </div>
            ))}
          </div>
        </section>

        {error && (
          <div
            role="alert"
            className="rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm"
          >
            <p className="font-medium">Verilere şu anda ulaşılamıyor</p>
            <p className="mt-2 text-muted-foreground">{error}</p>
            <Button className="mt-3" variant="outline" onClick={() => void refresh()}>
              Yeniden dene
            </Button>
          </div>
        )}
        {data && (
          <section
            aria-label="Günlük büro özeti"
            className="rounded-2xl border border-border bg-card p-5 sm:p-6"
          >
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              <CalendarDays className="h-5 w-5 text-primary" /> Bugün ne var?
            </h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              {data.counts.today_hearings === undefined || data.counts.today_tasks === undefined
                ? "Günlük özet henüz alınamadı. Haftalık kayıtlarınızı aşağıdan inceleyebilirsiniz."
                : `Bugün ${data.counts.today_hearings} kayıtlı duruşmanız ve son tarihi bugün olan ${data.counts.today_tasks} açık göreviniz var.`}
              {data.counts.overdue_tasks > 0
                ? ` Ayrıca ${data.counts.overdue_tasks} görevin kayıtlı son tarihi geçti; öncelikle kontrol edin.`
                : " Kayıtlı son tarihi geçmiş açık göreviniz yok."}
            </p>
            <div className="mt-4 flex flex-wrap gap-4 text-sm font-medium text-primary">
              <Link to="/dashboard/tasks">
                İş listesine git <ArrowRight className="ml-1 inline h-4 w-4" />
              </Link>
              <Link to="/dashboard/files">
                Belgeleri incele <ArrowRight className="ml-1 inline h-4 w-4" />
              </Link>
            </div>
            <p className="mt-3 text-xs text-muted-foreground">
              İstanbul saatine göre kayıtlı tarihler kullanılır. Bu özet belge içeriğinden hukuki
              süre hesaplamaz.
            </p>
          </section>
        )}
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
          <section className="rounded-2xl border border-border bg-card">
            <div className="border-b border-border p-5 sm:p-6">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold">Sizin onayınızla</h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Kayıtlarınıza dayalı, dayanağı görünür öneriler
                  </p>
                </div>
                <span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
                  {data ? proposals.length : "—"} öneri
                </span>
              </div>
              <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
                <div
                  className="flex gap-1 rounded-lg bg-muted/50 p-1"
                  role="group"
                  aria-label="Öneri türü"
                >
                  {[
                    ["all", "Tümü"],
                    ["document", "Belgeler"],
                    ["hearing", "Duruşmalar"],
                  ].map(([key, label]) => (
                    <button
                      key={key}
                      aria-pressed={filter === key}
                      onClick={() => setFilter(key)}
                      className={`rounded-md px-3 py-2 text-xs font-medium ${filter === key ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <label className="relative">
                  <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                  <Input
                    aria-label="Önerilerde ara"
                    placeholder="Önerilerde ara…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="h-9 w-full pl-9 sm:w-48"
                  />
                </label>
              </div>
            </div>
            {loading && !data ? (
              <div
                role="status"
                className="flex items-center justify-center gap-2 p-16 text-sm text-muted-foreground"
              >
                <Loader2 className="h-4 w-4 animate-spin" />
                Kayıtlarınız kontrol ediliyor…
              </div>
            ) : data && !visible.length ? (
              <div className="flex flex-col items-center px-6 py-16 text-center">
                <span className="mb-4 rounded-2xl bg-emerald-500/10 p-4 text-emerald-600">
                  <CheckCheck className="h-7 w-7" />
                </span>
                <h3 className="font-semibold">
                  {proposals.length ? "Bu filtrede öneri yok" : "Şimdilik onay bekleyen iş yok"}
                </h3>
                <p className="mt-2 max-w-sm text-sm leading-6 text-muted-foreground">
                  {proposals.length
                    ? "Başka bir filtre veya arama sözcüğü deneyin."
                    : "Son 7 günün yeni belgeleri ve gelecek 7 günün kayıtlı duruşmaları burada değerlendirilir. Yeni kayıt eklediğinizde listeyi yenileyin."}
                </p>
                <Link
                  to="/dashboard/files"
                  className="mt-5 inline-flex items-center gap-2 text-sm font-medium text-primary"
                >
                  Belgelere git <ArrowRight className="h-4 w-4" />
                </Link>
              </div>
            ) : (
              <div className="divide-y divide-border">
                {visible.map((p) => (
                  <article key={p.key} className="p-5 sm:p-6">
                    <div className="flex gap-4">
                      <span
                        className={`mt-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${p.kind === "hearing" ? "bg-amber-500/10 text-amber-600 dark:text-amber-400" : "bg-primary/10 text-primary"}`}
                      >
                        {p.kind === "hearing" ? (
                          <CalendarDays className="h-5 w-5" />
                        ) : (
                          <FileText className="h-5 w-5" />
                        )}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] font-medium">
                          <span className="text-muted-foreground">
                            {p.kind === "hearing" ? "DURUŞMA PLANI" : "YENİ BELGE"}
                          </span>
                          {p.priority === "high" && (
                            <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-amber-700 dark:text-amber-400">
                              Yaklaşıyor
                            </span>
                          )}
                        </div>
                        <h3 className="break-words font-semibold leading-6">{p.title}</h3>
                        <p className="mt-2 text-sm leading-6 text-muted-foreground">
                          {p.description}
                        </p>
                        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                          <span className="inline-flex items-center gap-1">
                            <FolderOpen className="h-3 w-3" />
                            {p.case_title}
                          </span>
                          <span>{when(p.date)}</span>
                        </div>
                        <Link
                          to={p.source_url}
                          className="mt-3 inline-flex max-w-full items-center gap-1 text-xs text-primary hover:underline"
                        >
                          <span className="truncate">Dayanak: {p.source_label}</span>
                          <ArrowUpRight className="h-3 w-3 shrink-0" />
                        </Link>
                        <div className="mt-5 flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busy || loading}
                            onClick={() => setReviewing(p)}
                          >
                            {p.kind === "hearing"
                              ? "Duruşmaya hazırlan"
                              : "Belgeyi incele ve özetle"}
                          </Button>
                          <Button
                            size="sm"
                            disabled={busy || loading}
                            onClick={() => choose(p, "approve")}
                          >
                            <Check className="mr-1.5 h-3.5 w-3.5" />
                            İncele ve onayla
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busy || loading}
                            onClick={() => choose(p, "approve")}
                          >
                            Düzenle
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busy || loading}
                            onClick={() => choose(p, "dismiss")}
                          >
                            <X className="mr-1 h-3.5 w-3.5" />
                            Reddet
                          </Button>
                        </div>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            )}
            {data?.limited && (
              <p className="border-t border-border p-4 text-xs text-amber-700 dark:text-amber-400">
                Yoğun kayıt nedeniyle her türün en fazla 100 kaydı incelendi; bu liste tüm büroyu
                kapsamaz.
              </p>
            )}
          </section>
          <aside className="space-y-5">
            <section className="rounded-2xl border border-border bg-card p-5">
              <div className="mb-5 flex items-center justify-between">
                <h2 className="flex items-center gap-2 font-semibold">
                  <CalendarDays className="h-4 w-4 text-primary" />
                  Yaklaşan duruşmalar
                </h2>
                <Link to="/dashboard/calendar" aria-label="Takvimi aç">
                  <ChevronRight className="h-4 w-4" />
                </Link>
              </div>
              {data?.hearings.length ? (
                <div className="space-y-4">
                  {data.hearings.map((h) => (
                    <div key={h.id}>
                      <Link
                        key={h.id}
                        to={`/dashboard/cases/${h.id}`}
                        className="block border-l-2 border-primary/40 pl-3"
                      >
                        <p className="text-xs font-medium text-primary">{when(h.next_hearing)}</p>
                        <p className="mt-1 truncate text-sm font-medium">{h.title}</p>
                        <p className="mt-1 truncate text-xs text-muted-foreground">
                          {h.court || h.case_no || "Dava kaydı"}
                        </p>
                      </Link>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="mt-1"
                        onClick={() =>
                          setReviewing({
                            key: `hearing:${h.id}:${h.next_hearing}`,
                            kind: "hearing",
                            title: `Duruşma: ${h.title}`,
                            description: "Kayıtlı dosya bilgileriyle duruşma hazırlığı.",
                            case_id: h.id,
                            case_title: h.title,
                            source_label: h.case_no || h.court || "Dava kaydı",
                            source_url: `/dashboard/cases/${h.id}`,
                            date: h.next_hearing,
                            priority: "medium",
                            action_label: "Takvime ekle",
                          })
                        }
                      >
                        Hazırlık notunu aç
                      </Button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm leading-6 text-muted-foreground">
                  {data ? "Gelecek 7 günde kayıtlı duruşma yok." : "Duruşma bilgisi bekleniyor."}
                </p>
              )}
            </section>
            <section className="rounded-2xl border border-border bg-card p-5">
              <h2 className="mb-4 flex items-center gap-2 font-semibold">
                <ListChecks className="h-4 w-4 text-primary" />
                İş listeniz
              </h2>
              {data?.tasks.length ? (
                <ul className="divide-y divide-border">
                  {data.tasks.map((t) => (
                    <li key={t.id} className="py-3 first:pt-0">
                      <p className="text-sm font-medium">{t.title}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {t.due_date ? when(t.due_date) : "Son tarih belirtilmemiş"}
                      </p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {data ? "Açık görev yok." : "Görev bilgisi bekleniyor."}
                </p>
              )}
              <Link
                to="/dashboard/tasks"
                className="mt-4 inline-flex items-center gap-2 text-xs font-medium text-primary"
              >
                İş Takibi’ni aç <ArrowRight className="h-3 w-3" />
              </Link>
            </section>
            <div className="rounded-xl border border-dashed border-border p-4 text-xs leading-5 text-muted-foreground">
              <ShieldCheck className="mb-2 h-5 w-5 text-emerald-600" />
              <p className="font-medium text-foreground">Kontrol sizde</p>
              <p className="mt-1">
                Öneriler otomatik işlem yapmaz. Reddetmek belgeyi silmez. Hukuki süreler ve UYAP
                gönderimleri bu ekrandan kendiliğinden başlatılmaz.
              </p>
              <p className="mt-3">
                {data
                  ? `Son kontrol: ${when(data.generated_at)}`
                  : "Canlı kayıtlar yüklendiğinde güncellenir."}
              </p>
            </div>
          </aside>
        </div>
        <BureauWorkHistory key={user?.id} />
      </div>
      <Dialog
        open={!!reviewing}
        onOpenChange={(open) => {
          if (!open) setReviewing(null);
        }}
      >
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {reviewing?.kind === "hearing" ? "Duruşma hazırlığı" : "Dosya hareketini incele"}
            </DialogTitle>
            <DialogDescription>
              Kaynağı inceleyin, belge özetini oluşturun ve sonraki işlemi ayrıca onaylayın.
            </DialogDescription>
          </DialogHeader>
          {reviewing && (
            <BureauReview
              key={`${user?.id}:${reviewing.key}`}
              proposal={reviewing}
              onApprove={(current) => {
                choose(current, "approve");
                setReviewing(null);
              }}
            />
          )}
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!selected}
        onOpenChange={(open) => {
          if (!open && !busy) setSelected(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {action === "dismiss" ? "Öneriyi reddet" : selected?.action_label}
            </DialogTitle>
            <DialogDescription>
              {action === "dismiss"
                ? "Yalnız bu öneri listeden kaldırılır. Belge, dava ve mevcut kayıtlarınız korunur."
                : selected?.kind === "hearing"
                  ? "Davaya kayıtlı tarih ve aşağıdaki başlıkla bir takvim kaydı oluşturulacak."
                  : "Aşağıdaki başlıkla İş Takibi’ne yeni bir inceleme görevi eklenecek."}
            </DialogDescription>
          </DialogHeader>
          {selected && (
            <div className="space-y-4">
              <div className="rounded-lg bg-muted/50 p-3 text-xs leading-5">
                <p className="font-medium">{selected.case_title}</p>
                <p className="mt-1 break-words text-muted-foreground">
                  Dayanak: {selected.source_label}
                </p>
                {selected.kind === "hearing" && (
                  <p className="mt-2">Tarih: {when(selected.date)}</p>
                )}
              </div>
              {action === "approve" && (
                <label className="block space-y-2 text-sm">
                  Başlık
                  <Input
                    autoFocus
                    value={title}
                    maxLength={200}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                </label>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setSelected(null)} disabled={busy}>
              Vazgeç
            </Button>
            <Button
              onClick={() => void submit()}
              disabled={busy || (action === "approve" && !title.trim())}
            >
              {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {action === "dismiss" ? "Öneriyi reddet" : `Onayla · ${selected?.action_label}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </DashboardLayout>
  );
}

export function BureauAssistantCard() {
  const { user } = useAuth();
  const [data, setData] = useState<BureauData | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setFailed(false);
    void loadBureau(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [user?.id]);
  return (
    <Link
      to="/dashboard/bureau-assistant"
      className="flex items-center gap-4 rounded-xl border border-primary/20 bg-primary/5 p-5 transition-colors hover:bg-primary/10"
    >
      <span className="rounded-xl bg-primary/10 p-3 text-primary">
        <BellRing className="h-5 w-5" />
      </span>
      <div className="min-w-0 flex-1">
        <h2 className="font-semibold">Büro Asistanı</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {failed
            ? "Çalışma masanızı açın; kayıtlar yeniden kontrol edilsin."
            : data
              ? data.proposals.length
                ? `${data.proposals.length} öneri onayınızı bekliyor${data.limited ? " · sınırlı liste" : ""}.`
                : "Onay bekleyen öneri yok. İşlerinize göz atın."
              : "Yeni belgeler ve yaklaşan duruşmalar kontrol ediliyor…"}
        </p>
      </div>
      <ArrowRight className="h-5 w-5 shrink-0 text-primary" />
    </Link>
  );
}

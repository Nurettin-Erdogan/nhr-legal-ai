import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { useAuth } from "@/components/AuthProvider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  adminApi,
  type AdminAuditEntry,
  type AdminFeedback,
  type AdminOverview,
  type AdminRegistration,
  type AdminUser,
} from "@/lib/admin-api";
import {
  BACKUP_STALE_HOURS,
  FEEDBACK_LABELS,
  INVITE_STATE_LABELS,
  MODE_LABELS,
  ROLE_LABELS,
  STATUS_LABELS,
  actionLabel,
  backupAgeHours,
  formatBytes,
  formatCount,
  formatDateTime,
  formatUsd,
  isAdmin,
} from "@/lib/admin-panel";

export const Route = createFileRoute("/_authenticated/dashboard/admin")({
  component: AdminPage,
});

/** Bir sekmenin verisini yükler; hata sayfayı bozmaz, sekmede gösterilir.
 * Yalnız en son isteğin yanıtı yazılır: sekme açılırken başlayan süzgeçsiz liste, hemen ardından yapılan aramanın
 * sonucunu geç dönüp eziyordu (tarayıcı denemesi, 2026-10-24). */
function useLoad<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const latest = useRef(0);
  const reload = useCallback(async () => {
    const request = ++latest.current;
    setLoading(true);
    setError("");
    try {
      const next = await loader();
      if (request === latest.current) setData(next);
    } catch (reason) {
      if (request === latest.current) setError(reason instanceof Error ? reason.message : "Veri alınamadı.");
    } finally {
      if (request === latest.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { data, error, loading, reload };
}

function Notice({ error, loading }: { error: string; loading: boolean }) {
  if (error)
    return (
      <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
        {error}
      </p>
    );
  if (loading) return <p className="text-sm text-muted-foreground">Yükleniyor…</p>;
  return null;
}

function Stat({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {detail && <div className="mt-1 text-xs text-muted-foreground">{detail}</div>}
    </div>
  );
}

function HealthRow({ ok, label, children }: { ok: boolean | null; label: string; children: ReactNode }) {
  const tone = ok === null ? "bg-muted-foreground" : ok ? "bg-emerald-500" : "bg-amber-500";
  return (
    <li className="flex items-start gap-3 border-b py-3 last:border-0">
      <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${tone}`} aria-hidden="true" />
      <div className="min-w-0">
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs text-muted-foreground">{children}</div>
      </div>
    </li>
  );
}

function OverviewTab() {
  const { data, error, loading, reload } = useLoad<AdminOverview>(() => adminApi.overview());
  const summary = data?.summary;
  const health = data?.health;
  const age = backupAgeHours(health?.backup.created_at);
  return (
    <div className="space-y-5">
      <div className="flex justify-end">
        <Button size="sm" variant="outline" onClick={() => void reload()} disabled={loading}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Yenile
        </Button>
      </div>
      <Notice error={error} loading={loading && !data} />
      {summary && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Stat
            label="Kullanıcılar"
            value={formatCount(summary.users_total)}
            detail={`${formatCount(summary.users_active)} aktif · ${formatCount(summary.users_suspended)} askıda`}
          />
          <Stat
            label="Son 7 gün"
            value={formatCount(summary.users_seen_7d)}
            detail={`giriş yapan kullanıcı · ${formatCount(summary.users_new_7d)} yeni hesap`}
          />
          <Stat
            label="Asistan kullanımı"
            value={formatCount(summary.ai_answers_7d)}
            detail={`son 7 günde cevap · son 24 saatte ${formatCount(summary.ai_answers_24h)}`}
          />
          <Stat
            label="Geri bildirim"
            value={formatCount(summary.feedback_7d)}
            detail={`son 7 gün · toplam ${formatCount(summary.feedback_total)}`}
          />
          <Stat
            label="Büro verisi"
            value={formatCount(summary.documents_total)}
            detail={`belge · ${formatCount(summary.cases_total)} dava (içerik yöneticiye gösterilmez)`}
          />
          <Stat
            label="Hukuk korpusu"
            value={formatCount(data?.corpus.decisions)}
            detail={`doğrulanmış karar · ${formatCount(data?.corpus.legislation ?? undefined)} mevzuat maddesi`}
          />
        </div>
      )}
      {health && (
        <section className="rounded-xl border bg-card px-4">
          <h2 className="pt-4 text-sm font-semibold">Sistem durumu</h2>
          <ul>
            <HealthRow ok={health.database} label="Veritabanı">
              {health.database ? "Bağlı" : "Bağlantı yok"}
            </HealthRow>
            <HealthRow ok={health.local_model.reachable && health.local_model.installed} label="Yerel yapay zekâ modeli">
              {health.local_model.model} ·{" "}
              {health.local_model.reachable
                ? health.local_model.installed
                  ? "çalışıyor"
                  : "model kurulu değil"
                : "Ollama'ya ulaşılamıyor"}{" "}
              (dava ve belge soruları bu modelle cevaplanır)
            </HealthRow>
            <HealthRow
              ok={health.cloud.provider ? !health.cloud.error && (health.cloud.remaining_usd ?? 1) > 0.5 : null}
              label="Bulut yapay zekâ modeli (genel sorular)"
            >
              {health.cloud.provider ? `${health.cloud.provider} · ${health.cloud.model ?? "—"}` : "Kapalı"}
              {health.cloud.error && ` · ${health.cloud.error}`}
              {typeof health.cloud.remaining_usd === "number" &&
                ` · kalan bakiye ${formatUsd(health.cloud.remaining_usd)} (harcanan ${formatUsd(health.cloud.usage_usd)})`}
            </HealthRow>
            <HealthRow ok={health.backup.found ? (age ?? 99) <= BACKUP_STALE_HOURS : false} label="Kullanıcı verisi yedeği">
              {health.backup.found
                ? `${formatDateTime(health.backup.created_at)} · ${formatCount(health.backup.rows)} satır · ${formatBytes(
                    health.backup.database_bytes,
                  )}${health.backup.uploads_included ? " · yüklenen dosyalar dahil" : " · yüklenen dosyalar hariç"}`
                : "Yedek bulunamadı"}
              {age !== null && age > BACKUP_STALE_HOURS && ` · son yedek ${Math.round(age)} saat önce, gece yedeği çalışmamış olabilir`}
            </HealthRow>
          </ul>
        </section>
      )}
    </div>
  );
}

function UsersTab({ selfId }: { selfId: string | undefined }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [applied, setApplied] = useState({ query: "", status: "" });
  const { data, error, loading, reload } = useLoad<AdminUser[]>(
    () => adminApi.users(applied.query, applied.status),
    [applied.query, applied.status],
  );
  const [busy, setBusy] = useState("");

  const act = async (key: string, confirmText: string | null, action: () => Promise<unknown>, done: string) => {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(key);
    try {
      await action();
      toast.success(done);
      await reload();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "İşlem yapılamadı.");
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="space-y-4">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setApplied({ query, status });
        }}
      >
        <Input
          className="w-full max-w-xs"
          placeholder="Ad ya da e-posta ara"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="Kullanıcı ara"
        />
        <select
          aria-label="Durum"
          className="h-9 rounded-md border bg-background px-2 text-sm"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
        >
          <option value="">Tüm durumlar</option>
          <option value="active">Aktif</option>
          <option value="suspended">Askıda</option>
          <option value="inactive">Pasif</option>
        </select>
        <Button type="submit" size="sm">
          Uygula
        </Button>
      </form>
      <Notice error={error} loading={loading && !data} />
      {data && (
        <>
          <p className="text-xs text-muted-foreground">
            {data.length} kullanıcı. Sayılar yalnız kullanım ölçüsüdür; müvekkil, dava ve belge içerikleri yöneticiye gösterilmez.
          </p>
          <div className="overflow-x-auto rounded-xl border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Kullanıcı</TableHead>
                  <TableHead>Rol</TableHead>
                  <TableHead>Durum</TableHead>
                  <TableHead>Son giriş</TableHead>
                  <TableHead className="text-right">Dava</TableHead>
                  <TableHead className="text-right">Belge</TableHead>
                  <TableHead className="text-right">Asistan (30 gün)</TableHead>
                  <TableHead>İşlemler</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((user) => {
                  const self = user.user_id === selfId;
                  const admin = user.roles.includes("admin");
                  const suspended = user.status === "suspended";
                  const name = user.full_name || user.email;
                  return (
                    <TableRow key={user.user_id} data-testid="admin-user-row">
                      <TableCell>
                        <div className="font-medium">
                          {name}
                          {self && <span className="ml-1 text-xs text-muted-foreground">(siz)</span>}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {user.email} · kayıt {formatDateTime(user.created_at)}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {user.roles.map((role) => (
                            <Badge key={role} variant={role === "admin" ? "default" : "secondary"}>
                              {ROLE_LABELS[role] ?? role}
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={suspended ? "destructive" : "outline"}>{STATUS_LABELS[user.status] ?? user.status}</Badge>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-sm">{formatDateTime(user.last_login_at)}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatCount(user.cases)}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatCount(user.documents)}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatCount(user.ai_answers_30d)}</TableCell>
                      <TableCell>
                        {self ? (
                          <span className="text-xs text-muted-foreground">Kendi hesabınız</span>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {suspended ? (
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={!!busy}
                                onClick={() =>
                                  void act(`${user.user_id}:status`, null, () => adminApi.setStatus(user.user_id, "active"),
                                    `${name} yeniden etkinleştirildi`)
                                }
                              >
                                Etkinleştir
                              </Button>
                            ) : (
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={!!busy}
                                onClick={() =>
                                  void act(
                                    `${user.user_id}:status`,
                                    `${name} askıya alınsın mı? Açık oturumları hemen kapanır ve giriş yapamaz. Verileri silinmez.`,
                                    () => adminApi.setStatus(user.user_id, "suspended"),
                                    `${name} askıya alındı`,
                                  )
                                }
                              >
                                Askıya al
                              </Button>
                            )}
                            {admin ? (
                              <Button
                                size="sm"
                                variant="ghost"
                                disabled={!!busy}
                                onClick={() =>
                                  void act(`${user.user_id}:role`, `${name} kullanıcısının yöneticiliği kaldırılsın mı?`,
                                    () => adminApi.revokeRole(user.user_id, "admin"), "Yöneticilik kaldırıldı")
                                }
                              >
                                Yöneticiliği kaldır
                              </Button>
                            ) : (
                              <Button
                                size="sm"
                                variant="ghost"
                                disabled={!!busy}
                                onClick={() =>
                                  void act(
                                    `${user.user_id}:role`,
                                    `${name} yönetici yapılsın mı? Bu paneli görür, kullanıcıları askıya alabilir ve kayıt ayarını değiştirebilir.`,
                                    () => adminApi.grantRole(user.user_id, "admin"),
                                    "Yönetici yetkisi verildi",
                                  )
                                }
                              >
                                Yönetici yap
                              </Button>
                            )}
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </>
      )}
    </div>
  );
}

function AccessTab() {
  const { data, error, loading, reload } = useLoad<AdminAccess>(() => adminApi.access());
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try {
      await action();
      toast.success(done);
      await reload();
      return true;
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "İşlem yapılamadı.");
      return false;
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <Notice error={error} loading={loading && !data} />
      {data && (
        <>
          <section className="space-y-3 rounded-xl border bg-card p-5">
            <h2 className="font-semibold">Uygulamaya kimler girebilir?</h2>
            <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Erişim modu">
              {(Object.keys(ACCESS_MODE_LABELS) as AdminAccess["mode"][]).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  role="radio"
                  aria-checked={data.mode === mode}
                  disabled={busy}
                  onClick={() => {
                    if (data.mode === mode || !window.confirm(accessModeConfirm(mode, data.unlisted_accounts))) return;
                    void run(() => adminApi.setAccessMode(mode), `Erişim: ${ACCESS_MODE_LABELS[mode].label}`);
                  }}
                  className={`rounded-lg border p-3 text-left transition ${
                    data.mode === mode ? "border-primary bg-primary/5" : "hover:bg-muted/50"
                  }`}
                >
                  <div className="text-sm font-medium">{ACCESS_MODE_LABELS[mode].label}</div>
                  <div className="mt-1 text-xs text-muted-foreground">{ACCESS_MODE_LABELS[mode].description}</div>
                </button>
              ))}
            </div>
            {data.mode === "allowlist" ? (
              <p className="text-sm text-muted-foreground" data-testid="access-summary">
                {data.unlisted_accounts > 0
                  ? `Listede olmayan ${formatCount(data.unlisted_accounts)} hesap şu an giriş yapamıyor. Kullanıcılar sekmesinden tek tıkla listeye ekleyebilirsiniz.`
                  : "Bütün aktif hesaplar listede ya da yönetici."}
              </p>
            ) : (
              <p role="alert" className="rounded-lg bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-300">
                Şu an bağlantıyı bilen herkes hesap açıp giriş yapabiliyor.
              </p>
            )}
            {!data.registration_allowed && (
              <p role="alert" className="rounded-lg bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-300">
                Sunucu ayarında (ALLOW_REGISTRATION) yeni hesap açma kapalı: listedeki kişiler yalnız mevcut hesaplarıyla girebilir.
              </p>
            )}
          </section>

          <section className="space-y-3 rounded-xl border bg-card p-5">
            <h2 className="font-semibold">Erişim listesi</h2>
            <p className="text-sm text-muted-foreground">
              Listeye eklediğiniz kişi, uygulamanın kayıt sayfasından bu e-posta adresiyle hesap açar ya da mevcut hesabıyla giriş
              yapar. Listeden çıkardığınız kişinin açık oturumu hemen kapanır; verileri silinmez. Uygulama e-posta göndermez; adrese
              siz haber verirsiniz.
            </p>
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (!email.trim()) return;
                void run(() => adminApi.addAccess(email, note), `${email.trim()} listeye eklendi`).then((ok) => {
                  if (!ok) return;
                  setEmail("");
                  setNote("");
                });
              }}
            >
              <Input
                type="email"
                required
                className="w-full max-w-xs"
                placeholder="avukat@ornek.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                aria-label="Listeye eklenecek e-posta"
              />
              <Input
                className="w-full max-w-xs"
                placeholder="Not (isteğe bağlı), ör. pilot avukat"
                maxLength={200}
                value={note}
                onChange={(event) => setNote(event.target.value)}
                aria-label="Not"
              />
              <Button type="submit" size="sm" disabled={busy}>
                Listeye ekle
              </Button>
            </form>
            {data.entries.length > 0 ? (
              <div className="overflow-x-auto rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>E-posta</TableHead>
                      <TableHead>Not</TableHead>
                      <TableHead>Hesap</TableHead>
                      <TableHead>Eklenme</TableHead>
                      <TableHead />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.entries.map((entry) => (
                      <TableRow key={entry.id} data-testid="access-entry">
                        <TableCell className="font-medium">{entry.email}</TableCell>
                        <TableCell className="text-sm text-muted-foreground">{entry.note ?? "—"}</TableCell>
                        <TableCell>
                          <Badge variant={entry.account_status === "active" ? "default" : "outline"}>
                            {accountStateLabel(entry.account_status)}
                          </Badge>
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-sm">{formatDateTime(entry.added_at)}</TableCell>
                        <TableCell>
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busy}
                            onClick={() => {
                              if (!window.confirm(removeAccessConfirm(entry.email, data.mode))) return;
                              void run(() => adminApi.removeAccess(entry.id), `${entry.email} listeden çıkarıldı`);
                            }}
                          >
                            Listeden çıkar
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Liste boş.{data.mode === "allowlist" ? " Şu an yalnız yöneticiler girebilir." : ""}
              </p>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function FeedbackTab() {
  const [category, setCategory] = useState("");
  const { data, error, loading } = useLoad<AdminFeedback[]>(() => adminApi.feedback(category), [category]);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Geri bildirim türü">
        {[["", "Hepsi"], ...Object.entries(FEEDBACK_LABELS)].map(([value, label]) => (
          <Button key={value} size="sm" variant={category === value ? "default" : "outline"} onClick={() => setCategory(value)}>
            {label}
          </Button>
        ))}
      </div>
      <Notice error={error} loading={loading && !data} />
      {data && data.length === 0 && <p className="text-sm text-muted-foreground">Bu türde geri bildirim yok.</p>}
      <ul className="space-y-3">
        {data?.map((item) => (
          <li key={item.id} className="rounded-xl border bg-card p-4" data-testid="admin-feedback">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <Badge variant={item.category === "hata" ? "destructive" : "secondary"}>{FEEDBACK_LABELS[item.category]}</Badge>
              <span>{item.user_name || item.user_email}</span>
              <span>· {formatDateTime(item.created_at)}</span>
              {item.page && <span>· {item.page}</span>}
            </div>
            <p className="mt-2 whitespace-pre-wrap text-sm">{item.message}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AuditTab() {
  const { data, error, loading, reload } = useLoad<[AdminAuditEntry[], AdminUser[]]>(() =>
    Promise.all([adminApi.audit(150), adminApi.users()]),
  );
  const names = useMemo(
    () => new Map((data?.[1] ?? []).map((user) => [user.user_id, user.full_name || user.email])),
    [data],
  );
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Son 150 kayıt. Giriş, kayıt, asistan kullanımı ve yönetici işlemleri burada tutulur (KVKK denetim kaydı).
        </p>
        <Button size="sm" variant="outline" onClick={() => void reload()} disabled={loading}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Yenile
        </Button>
      </div>
      <Notice error={error} loading={loading && !data} />
      {data && (
        <div className="overflow-x-auto rounded-xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Zaman</TableHead>
                <TableHead>Kim</TableHead>
                <TableHead>İşlem</TableHead>
                <TableHead>Ayrıntı</TableHead>
                <TableHead>IP</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data[0].map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell className="whitespace-nowrap text-sm">{formatDateTime(entry.created_at)}</TableCell>
                  <TableCell className="text-sm">
                    {entry.actor_user_id ? names.get(entry.actor_user_id) ?? entry.actor_user_id.slice(0, 8) : "—"}
                  </TableCell>
                  <TableCell className="text-sm">{actionLabel(entry.action)}</TableCell>
                  <TableCell className="max-w-xs truncate text-xs text-muted-foreground">
                    {entry.entity_type === "user" && entry.entity_id ? `${names.get(entry.entity_id) ?? "kullanıcı"} ` : ""}
                    {Object.keys(entry.metadata ?? {}).length ? JSON.stringify(entry.metadata) : ""}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{entry.ip_address ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function AdminPage() {
  const { roles, user } = useAuth();
  if (!isAdmin(roles)) {
    return (
      <DashboardLayout title="Yönetim" subtitle="Platform yönetici paneli">
        <section role="status" className="max-w-xl rounded-xl border bg-card p-6">
          <h2 className="font-semibold">Bu sayfa yalnız yöneticilere açıktır</h2>
          <p className="mt-2 text-sm text-muted-foreground">Hesabınızda yönetici yetkisi yok.</p>
        </section>
      </DashboardLayout>
    );
  }
  return (
    <DashboardLayout title="Yönetim" subtitle="Platform yönetici paneli — avukatlar bu bölümü görmez">
      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList className="flex h-auto flex-wrap justify-start">
          <TabsTrigger value="overview">Genel Bakış</TabsTrigger>
          <TabsTrigger value="users">Kullanıcılar</TabsTrigger>
          <TabsTrigger value="access">Erişim</TabsTrigger>
          <TabsTrigger value="feedback">Geri Bildirimler</TabsTrigger>
          <TabsTrigger value="audit">Denetim Kaydı</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <OverviewTab />
        </TabsContent>
        <TabsContent value="users">
          <UsersTab selfId={user?.id} />
        </TabsContent>
        <TabsContent value="access">
          <AccessTab />
        </TabsContent>
        <TabsContent value="feedback">
          <FeedbackTab />
        </TabsContent>
        <TabsContent value="audit">
          <AuditTab />
        </TabsContent>
      </Tabs>
    </DashboardLayout>
  );
}

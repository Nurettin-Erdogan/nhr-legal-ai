import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { BureauAssistantCard } from "@/components/BureauAssistant";
import {
  ArrowRight,
  Briefcase,
  CalendarClock,
  CheckCircle2,
  FolderOpen,
  ListChecks,
  Search,
  Sparkles,
  Users,
} from "lucide-react";
import { Link } from "@/lib/router-compat";
import { useNavigate } from "@/lib/router-hooks";
import { useAuth } from "@/components/AuthContext";
import { db } from "@/lib/db";
import {
  localDay,
  openTasks,
  overdueCount,
  recentCases,
  relativeDay,
  upcomingHearings,
  type HomeCase,
  type HomeTask,
} from "@/lib/home-summary";

const askExamples = [
  "Kıdem tazminatına hak kazanma şartları nelerdir?",
  "Kira artış oranı en çok ne kadar olabilir?",
  "Haksız fiilde zamanaşımı süresi nedir?",
];

const statusLabel: Record<string, string> = {
  active: "Aktif",
  pending: "Beklemede",
  closed: "Kapalı",
};
const statusTone: Record<string, string> = {
  active: "bg-success/10 text-success",
  pending: "bg-warning/10 text-warning",
  closed: "bg-muted text-muted-foreground",
};

const MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"];

type Load<T> = { rows: T[]; error?: string };

async function loadRows<T>(
  query: PromiseLike<{ data: unknown; error: { message: string } | null }>,
): Promise<Load<T>> {
  try {
    const result = await query;
    if (result.error) return { rows: [], error: result.error.message };
    return { rows: Array.isArray(result.data) ? (result.data as T[]) : [] };
  } catch {
    return { rows: [], error: "Yüklenemedi." };
  }
}

function greeting(now: Date): string {
  const hour = now.getHours();
  if (hour < 6) return "İyi geceler";
  if (hour < 12) return "Günaydın";
  if (hour < 18) return "İyi günler";
  return "İyi akşamlar";
}

function Card({
  title,
  icon: Icon,
  children,
  action,
}: {
  title: string;
  icon: typeof Briefcase;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-border bg-card p-5 shadow-sm">
      <div className="mb-3 flex items-center gap-2.5">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted text-muted-foreground">
          <Icon className="h-4 w-4" />
        </span>
        <h2 className="flex-1 text-sm font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Stat({
  to,
  icon: Icon,
  label,
  value,
  hint,
  alert,
}: {
  to: string;
  icon: typeof Briefcase;
  label: string;
  value: number | null;
  hint?: string;
  alert?: boolean;
}) {
  return (
    <Link
      to={to}
      className="group rounded-2xl border border-border bg-card p-4 shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md"
    >
      <div className="flex items-center justify-between text-muted-foreground">
        <span className="text-xs font-medium">{label}</span>
        <Icon className="h-4 w-4" />
      </div>
      <div
        className={`mt-2 text-3xl font-semibold tabular-nums ${alert ? "text-destructive" : ""}`}
        data-testid="stat-value"
      >
        {value === null ? "—" : value}
      </div>
      <div className="mt-1 min-h-4 text-xs text-muted-foreground">{hint ?? ""}</div>
    </Link>
  );
}

function DateBadge({ value, urgent }: { value: string | null; urgent: boolean }) {
  const day = localDay(value);
  const date = day === null ? null : new Date(day);
  return (
    <span
      className={`flex h-11 w-11 shrink-0 flex-col items-center justify-center rounded-xl text-center leading-none ${urgent ? "bg-amber-500/15 text-amber-700 dark:text-amber-400" : "bg-muted text-foreground"}`}
      aria-hidden="true"
    >
      <span className="text-base font-semibold tabular-nums">{date ? date.getDate() : "—"}</span>
      <span className="mt-0.5 text-[10px] uppercase tracking-wide">
        {date ? MONTHS[date.getMonth()] : ""}
      </span>
    </span>
  );
}

const Dashboard = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [cases, setCases] = useState<Load<HomeCase>>();
  const [tasks, setTasks] = useState<Load<HomeTask>>();
  const [clients, setClients] = useState<Load<{ id: string }>>();
  const [question, setQuestion] = useState("");

  useEffect(() => {
    let active = true;
    void loadRows<HomeCase>(
      db
        .from("cases")
        .select("id,title,case_no,court,status,next_hearing,created_at")
        .order("created_at", { ascending: false })
        .limit(200),
    ).then((value) => {
      if (active) setCases(value);
    });
    void loadRows<HomeTask>(
      db
        .from("tasks")
        .select("id,title,status,due_date,case_id")
        .neq("status", "done")
        .order("created_at", { ascending: false })
        .limit(200),
    ).then((value) => {
      if (active) setTasks(value);
    });
    void loadRows<{ id: string }>(db.from("clients").select("id").limit(1000)).then((value) => {
      if (active) setClients(value);
    });
    return () => {
      active = false;
    };
  }, []);

  const now = useMemo(() => new Date(), []);
  const hearings = cases ? upcomingHearings(cases.rows) : [];
  const open = tasks ? openTasks(tasks.rows) : [];
  const recent = cases ? recentCases(cases.rows) : [];
  const overdue = overdueCount(open);
  const activeCases =
    cases && !cases.error ? cases.rows.filter((c) => c.status === "active") : null;
  const thisWeek = cases && !cases.error ? hearings.filter((h) => h.days <= 7).length : null;
  const openCount =
    tasks && !tasks.error ? tasks.rows.filter((t) => t.status !== "done").length : null;
  const clientCount = clients && !clients.error ? clients.rows.length : null;
  const firstName = user?.full_name?.trim().split(/\s+/)[0] ?? "";
  const dateLabel = now.toLocaleDateString("tr-TR", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
  const brandNew =
    cases &&
    !cases.error &&
    cases.rows.length === 0 &&
    clients &&
    !clients.error &&
    clientCount === 0;

  const ask = (text: string) => {
    const value = text.trim();
    navigate(value ? `/dashboard/ai?q=${encodeURIComponent(value)}` : "/dashboard/ai");
  };

  return (
    <DashboardLayout title="Ana Sayfa" subtitle="Bugünkü işleriniz ve hızlı erişim">
      <div className="mx-auto max-w-5xl space-y-6 pb-16">
        <section className="relative overflow-hidden rounded-3xl border border-primary/15 bg-gradient-to-br from-primary/10 via-card to-card p-6 sm:p-8">
          <div
            className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-primary/10 blur-3xl"
            aria-hidden="true"
          />
          <p className="text-xs font-medium capitalize text-muted-foreground">{dateLabel}</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">
            {greeting(now)}
            {firstName ? `, ${firstName}` : ""}
          </h1>
          <p className="mt-1 max-w-xl text-sm text-muted-foreground">
            Hukuki bir soru sorun; cevap yalnız doğrulanmış kanun ve karar kaynaklarına dayanır.
          </p>
          <form
            className="mt-5 flex flex-col gap-2 sm:flex-row"
            onSubmit={(event) => {
              event.preventDefault();
              ask(question);
            }}
            role="search"
          >
            <label className="sr-only" htmlFor="home-ask">
              Hukuk Asistanına soru
            </label>
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                id="home-ask"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="Hukuki bir soru yazın…"
                className="h-12 w-full rounded-xl border border-input bg-background pl-10 pr-3 text-sm shadow-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
              />
            </div>
            <button
              type="submit"
              className="inline-flex h-12 items-center justify-center gap-2 rounded-xl bg-primary px-5 text-sm font-medium text-primary-foreground shadow-sm transition hover:bg-primary/90"
            >
              <Sparkles className="h-4 w-4" />
              Asistana sor
            </button>
          </form>
          <div className="mt-3 flex flex-wrap gap-2">
            {askExamples.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => ask(example)}
                className="rounded-full border border-border bg-background/70 px-3 py-1 text-xs text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
              >
                {example}
              </button>
            ))}
          </div>
        </section>

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat
            to="/dashboard/cases"
            icon={Briefcase}
            label="Aktif dava"
            value={activeCases ? activeCases.length : null}
            hint={cases && !cases.error ? `${cases.rows.length} dava kayıtlı` : undefined}
          />
          <Stat
            to="/dashboard/calendar"
            icon={CalendarClock}
            label="7 günde duruşma"
            value={thisWeek}
            hint={thisWeek === 0 ? "Bu hafta duruşma yok" : undefined}
          />
          <Stat
            to="/dashboard/tasks"
            icon={ListChecks}
            label="Açık görev"
            value={openCount}
            hint={overdue ? `${overdue} gecikmiş` : openCount === 0 ? "Her şey yolunda" : undefined}
            alert={overdue > 0}
          />
          <Stat to="/dashboard/clients" icon={Users} label="Müvekkil" value={clientCount} />
        </div>

        <BureauAssistantCard />

        {brandNew && (
          <section
            className="rounded-2xl border border-dashed border-primary/30 bg-primary/5 p-5"
            data-testid="getting-started"
          >
            <h2 className="text-sm font-semibold">İlk adımlar</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Çalışma alanınızı birkaç dakikada kurun; belgeleriniz yalnız size görünür.
            </p>
            <ol className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[
                { to: "/dashboard/clients", label: "Müvekkil ekleyin", icon: Users },
                { to: "/dashboard/cases", label: "Dava açın", icon: Briefcase },
                { to: "/dashboard/files", label: "Belge yükleyin", icon: FolderOpen },
                { to: "/dashboard/ai", label: "Belgelerinizle soru sorun", icon: CheckCircle2 },
              ].map((step, index) => (
                <li key={step.to}>
                  <Link
                    to={step.to}
                    className="flex h-full items-center gap-3 rounded-xl border border-border bg-card p-3 text-sm font-medium transition hover:border-primary/40"
                  >
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs text-primary-foreground">
                      {index + 1}
                    </span>
                    <span className="flex-1">{step.label}</span>
                    <step.icon className="h-4 w-4 text-muted-foreground" />
                  </Link>
                </li>
              ))}
            </ol>
          </section>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          <Card
            title="Yaklaşan duruşmalar"
            icon={CalendarClock}
            action={
              <Link
                to="/dashboard/cases"
                className="text-xs text-primary underline-offset-2 hover:underline"
              >
                Tüm davalar
              </Link>
            }
          >
            {!cases && (
              <p className="text-sm text-muted-foreground" role="status">
                Yükleniyor…
              </p>
            )}
            {cases?.error && (
              <p className="text-sm text-destructive" role="alert">
                {cases.error}
              </p>
            )}
            {cases && !cases.error && hearings.length === 0 && (
              <p className="text-sm text-muted-foreground" data-testid="no-hearings">
                Kayıtlı yaklaşan duruşma yok. Davanın “Duruşma tarihi” alanını doldurunca burada
                görünür.
              </p>
            )}
            <ul className="space-y-1" data-testid="hearings">
              {hearings.map((item) => (
                <li key={item.id}>
                  <Link
                    to={`/dashboard/cases/${item.id}`}
                    className="-mx-2 flex items-center gap-3 rounded-xl px-2 py-2 text-sm transition-colors hover:bg-muted/60"
                  >
                    <DateBadge value={item.next_hearing} urgent={item.days <= 1} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{item.title}</span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {[item.court, item.case_no].filter(Boolean).join(" · ") ||
                          "Mahkeme belirtilmemiş"}
                      </span>
                    </span>
                    <span
                      className={`shrink-0 text-xs font-medium ${item.days <= 1 ? "text-amber-700 dark:text-amber-400" : "text-muted-foreground"}`}
                    >
                      {relativeDay(item.days)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>

          <Card
            title={overdue ? `Açık görevler · ${overdue} gecikmiş` : "Açık görevler"}
            icon={ListChecks}
            action={
              <Link
                to="/dashboard/tasks"
                className="text-xs text-primary underline-offset-2 hover:underline"
              >
                Görevler
              </Link>
            }
          >
            {!tasks && (
              <p className="text-sm text-muted-foreground" role="status">
                Yükleniyor…
              </p>
            )}
            {tasks?.error && (
              <p className="text-sm text-destructive" role="alert">
                {tasks.error}
              </p>
            )}
            {tasks && !tasks.error && open.length === 0 && (
              <p className="text-sm text-muted-foreground" data-testid="no-tasks">
                Açık görev yok.
              </p>
            )}
            <ul className="space-y-1" data-testid="tasks">
              {open.map((task) => {
                const late = task.days !== null && task.days < 0;
                return (
                  <li key={task.id}>
                    <Link
                      to="/dashboard/tasks"
                      className="-mx-2 flex items-center gap-3 rounded-xl px-2 py-2 text-sm transition-colors hover:bg-muted/60"
                    >
                      <span
                        className={`h-2.5 w-2.5 shrink-0 rounded-full ${late ? "bg-destructive" : "bg-primary/60"}`}
                        aria-hidden="true"
                      />
                      <span className="min-w-0 flex-1 truncate">{task.title}</span>
                      <span
                        className={`shrink-0 text-xs font-medium ${late ? "text-destructive" : "text-muted-foreground"}`}
                      >
                        {task.due_date ? relativeDay(task.days) : "süresiz"}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </Card>
        </div>

        <Card
          title="Son davalar"
          icon={Briefcase}
          action={
            <Link
              to="/dashboard/cases"
              className="text-xs text-primary underline-offset-2 hover:underline"
            >
              Dava ekle / yönet
            </Link>
          }
        >
          {cases && !cases.error && recent.length === 0 && (
            <p className="text-sm text-muted-foreground" data-testid="no-cases">
              Henüz dava yok.{" "}
              <Link to="/dashboard/cases" className="text-primary underline">
                İlk davanızı ekleyin
              </Link>
              ; UYAP evraklarını ve belgeleri davaya bağlayıp belgelerle soru sorabilirsiniz.
            </p>
          )}
          <ul className="space-y-1" data-testid="recent-cases">
            {recent.map((item) => (
              <li key={item.id}>
                <Link
                  to={`/dashboard/cases/${item.id}`}
                  className="-mx-2 flex items-center gap-3 rounded-xl px-2 py-2 text-sm transition-colors hover:bg-muted/60"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{item.title}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {[item.court, item.case_no].filter(Boolean).join(" · ") || "—"}
                    </span>
                  </span>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${statusTone[item.status] ?? statusTone.closed}`}
                  >
                    {statusLabel[item.status] ?? item.status}
                  </span>
                  <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/")({
  component: Dashboard,
});

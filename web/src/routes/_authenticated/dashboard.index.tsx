import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { BookOpen, Briefcase, CalendarClock, Gavel, ListChecks, Microscope, Scale, FolderOpen } from "lucide-react";
import { Link } from "@/lib/router-compat";
import { db } from "@/lib/db";
import { openTasks, overdueCount, recentCases, relativeDay, upcomingHearings, type HomeCase, type HomeTask } from "@/lib/home-summary";

const shortcuts = [
  { to: "/dashboard/ai", icon: Scale, title: "Hukuk Asistanı", desc: "Sorunuzu sorun; kaynaklı, doğrulanmış cevap" },
  { to: "/dashboard/legislation", icon: BookOpen, title: "Mevzuat", desc: "Kanun, KHK, yönetmelik ve tebliğ; madde madde" },
  { to: "/dashboard/case-law", icon: Gavel, title: "İçtihat", desc: "Emsal karar ara ya da olayı anlat" },
  { to: "/dashboard/agent-research", icon: Microscope, title: "Derin Araştırma", desc: "Mevzuat, karar ve usul başlıklarıyla rapor" },
  { to: "/dashboard/files", icon: FolderOpen, title: "Dosyalar & UYAP", desc: "Belge yükle, UYAP evraklarını aktar" },
];

type Load<T> = { rows: T[]; error?: string };

async function loadRows<T>(query: PromiseLike<{ data: unknown; error: { message: string } | null }>): Promise<Load<T>> {
  try {
    const result = await query;
    if (result.error) return { rows: [], error: result.error.message };
    return { rows: Array.isArray(result.data) ? (result.data as T[]) : [] };
  } catch {
    return { rows: [], error: "Yüklenemedi." };
  }
}

function Card({ title, icon: Icon, children, action }: { title: string; icon: typeof Briefcase; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <div className="mb-3 flex items-center gap-2">
        <Icon className="h-4 w-4 text-muted-foreground" />
        <h2 className="flex-1 text-sm font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

const Dashboard = () => {
  const [cases, setCases] = useState<Load<HomeCase>>();
  const [tasks, setTasks] = useState<Load<HomeTask>>();

  useEffect(() => {
    let active = true;
    void loadRows<HomeCase>(db.from("cases").select("id,title,case_no,court,status,next_hearing,created_at").order("created_at", { ascending: false }).limit(200)).then((value) => {
      if (active) setCases(value);
    });
    void loadRows<HomeTask>(db.from("tasks").select("id,title,status,due_date,case_id").neq("status", "done").order("created_at", { ascending: false }).limit(200)).then((value) => {
      if (active) setTasks(value);
    });
    return () => {
      active = false;
    };
  }, []);

  const hearings = cases ? upcomingHearings(cases.rows) : [];
  const open = tasks ? openTasks(tasks.rows) : [];
  const recent = cases ? recentCases(cases.rows) : [];
  const overdue = overdueCount(open);

  return (
    <DashboardLayout title="Ana Sayfa" subtitle="Bugünkü işleriniz ve hızlı erişim">
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="grid gap-4 md:grid-cols-2">
          <Card title="Yaklaşan duruşmalar" icon={CalendarClock} action={<Link to="/dashboard/cases" className="text-xs underline">Tüm davalar</Link>}>
            {!cases && <p className="text-sm text-muted-foreground" role="status">Yükleniyor…</p>}
            {cases?.error && <p className="text-sm text-destructive" role="alert">{cases.error}</p>}
            {cases && !cases.error && hearings.length === 0 && (
              <p className="text-sm text-muted-foreground" data-testid="no-hearings">
                Kayıtlı yaklaşan duruşma yok. Davanın “Duruşma tarihi” alanını doldurunca burada görünür.
              </p>
            )}
            <ul className="divide-y" data-testid="hearings">
              {hearings.map((item) => (
                <li key={item.id}>
                  <Link to={`/dashboard/cases/${item.id}`} className="flex items-center justify-between gap-3 py-2 text-sm hover:underline">
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{item.title}</span>
                      <span className="block truncate text-xs text-muted-foreground">{[item.court, item.case_no].filter(Boolean).join(" · ") || "Mahkeme belirtilmemiş"}</span>
                    </span>
                    <span className={`shrink-0 text-xs font-medium ${item.days <= 1 ? "text-amber-700 dark:text-amber-400" : "text-muted-foreground"}`}>{relativeDay(item.days)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>

          <Card title={overdue ? `Açık görevler · ${overdue} gecikmiş` : "Açık görevler"} icon={ListChecks} action={<Link to="/dashboard/tasks" className="text-xs underline">Görevler</Link>}>
            {!tasks && <p className="text-sm text-muted-foreground" role="status">Yükleniyor…</p>}
            {tasks?.error && <p className="text-sm text-destructive" role="alert">{tasks.error}</p>}
            {tasks && !tasks.error && open.length === 0 && <p className="text-sm text-muted-foreground" data-testid="no-tasks">Açık görev yok.</p>}
            <ul className="divide-y" data-testid="tasks">
              {open.map((task) => (
                <li key={task.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <span className="min-w-0 truncate">{task.title}</span>
                  <span className={`shrink-0 text-xs font-medium ${task.days !== null && task.days < 0 ? "text-destructive" : "text-muted-foreground"}`}>{task.due_date ? relativeDay(task.days) : "süresiz"}</span>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        <Card title="Son davalar" icon={Briefcase} action={<Link to="/dashboard/cases" className="text-xs underline">Dava ekle / yönet</Link>}>
          {cases && !cases.error && recent.length === 0 && (
            <p className="text-sm text-muted-foreground" data-testid="no-cases">
              Henüz dava yok. <Link to="/dashboard/cases" className="underline">İlk davanızı ekleyin</Link>; UYAP evraklarını ve belgeleri davaya bağlayıp belgelerle soru sorabilirsiniz.
            </p>
          )}
          <ul className="divide-y" data-testid="recent-cases">
            {recent.map((item) => (
              <li key={item.id}>
                <Link to={`/dashboard/cases/${item.id}`} className="flex items-center justify-between gap-3 py-2 text-sm hover:underline">
                  <span className="min-w-0 truncate font-medium">{item.title}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">{item.court ?? item.case_no ?? ""}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>

        <div>
          <h2 className="mb-3 text-sm font-semibold text-muted-foreground">Hızlı erişim</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {shortcuts.map((a) => (
              <Link key={a.to} to={a.to} className="group flex items-center gap-4 rounded-xl border border-border bg-card p-4 transition-colors hover:border-foreground/20">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{a.title}</div>
                  <div className="mt-1 text-xs text-muted-foreground">{a.desc}</div>
                </div>
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted">
                  <a.icon className="h-4 w-4" />
                </div>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/")({
  component: Dashboard,
});

import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  ChevronLeft,
  ChevronRight,
  Plus,
  Loader2,
  Pencil,
  Trash2,
  Calendar as CalendarIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useEffect, useMemo, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/components/AuthContext";
import { toast } from "sonner";
import { z } from "zod";
import { deriveCalendarEvents } from "@/lib/calendar-derived";
import { useNavigate } from "@/lib/router-hooks";

interface CalEvent {
  id: string;
  owner_id: string;
  title: string;
  description: string | null;
  event_type: string;
  start_at: string;
  end_at: string | null;
  all_day: boolean;
  location: string | null;
  case_id: string | null;
  client_id: string | null;
  color: string | null;
  reminder_minutes: number | null;
  /** Dava duruşması ya da görev son tarihinden türeyen girdi: takvimde düzenlenmez, kaynağına götürür. */
  derived?: "case" | "task";
  link?: string;
}
interface CaseLite {
  id: string;
  title: string;
  case_no: string | null;
  court?: string | null;
  next_hearing?: string | null;
}
interface ClientLite {
  id: string;
  full_name: string;
}

const typeColor: Record<string, string> = {
  hearing: "bg-primary text-primary-foreground",
  meeting: "bg-secondary text-foreground border border-border",
  task: "bg-gold/20 text-gold-deep border border-gold/40",
  deadline: "bg-destructive/15 text-destructive border border-destructive/30",
  callback: "bg-blue-500/15 text-blue-600 border border-blue-500/30",
  other: "bg-muted text-muted-foreground border border-border",
};
const typeLabel: Record<string, string> = {
  hearing: "Duruşma",
  meeting: "Toplantı",
  task: "Görev",
  deadline: "Son Tarih",
  callback: "Geri Arama",
  other: "Diğer",
};

const schema = z.object({
  title: z.string().trim().min(1, "Başlık gerekli").max(200),
  description: z.string().trim().max(1000).optional().or(z.literal("")),
  event_type: z.enum(["hearing", "meeting", "task", "deadline", "callback", "other"]),
  start_at: z.string().min(1, "Başlangıç zamanı gerekli"),
  end_at: z.string().optional().or(z.literal("")),
  all_day: z.boolean(),
  location: z.string().trim().max(200).optional().or(z.literal("")),
  case_id: z.string().optional().or(z.literal("")),
  client_id: z.string().optional().or(z.literal("")),
  reminder_minutes: z.string().optional().or(z.literal("")),
});

type EvForm = {
  title: string;
  description: string;
  event_type: "hearing" | "meeting" | "task" | "deadline" | "callback" | "other";
  start_at: string;
  end_at: string;
  all_day: boolean;
  location: string;
  case_id: string;
  client_id: string;
  reminder_minutes: string;
};
const empty: EvForm = {
  title: "",
  description: "",
  event_type: "meeting",
  start_at: "",
  end_at: "",
  all_day: false,
  location: "",
  case_id: "",
  client_id: "",
  reminder_minutes: "",
};

const dayNames = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];

const startOfMonth = (d: Date) => new Date(d.getFullYear(), d.getMonth(), 1);
const endOfMonth = (d: Date) => new Date(d.getFullYear(), d.getMonth() + 1, 0);

const CalendarPage = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [cursor, setCursor] = useState(new Date());
  const [view, setView] = useState<"month" | "agenda">("month");
  const [events, setEvents] = useState<CalEvent[]>([]);
  const [cases, setCases] = useState<CaseLite[]>([]);
  const [clients, setClients] = useState<ClientLite[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<CalEvent | null>(null);
  const [form, setForm] = useState<EvForm>(empty);
  const [saving, setSaving] = useState(false);

  const monthStart = startOfMonth(cursor);
  const monthEnd = endOfMonth(cursor);

  const load = async () => {
    setLoading(true);
    // Load wider window so prev/next month transitions are smooth
    const from = new Date(monthStart);
    from.setDate(from.getDate() - 7);
    const to = new Date(monthEnd);
    to.setDate(to.getDate() + 7);
    const [{ data: e, error }, { data: cs }, { data: cl }, { data: ts }] = await Promise.all([
      supabase
        .from("calendar_events")
        .select("*")
        .gte("start_at", from.toISOString())
        .lte("start_at", to.toISOString())
        .order("start_at", { ascending: true }),
      supabase
        .from("cases")
        .select("id, title, case_no, court, next_hearing")
        .order("created_at", { ascending: false }),
      supabase.from("clients").select("id, full_name").order("full_name", { ascending: true }),
      supabase
        .from("tasks")
        .select("id, title, due_date, status, case_id")
        .gte("due_date", from.toISOString())
        .lte("due_date", to.toISOString()),
    ]);
    if (error) toast.error(error.message);
    const own = (e ?? []) as CalEvent[];
    // Davanın "Sonraki Duruşma" tarihi ve görevlerin son tarihi takvime kendiliğinden düşer (ayrı etkinlik açmak gerekmez).
    const derived = deriveCalendarEvents(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ((cs ?? []) as any[]).map((c) => ({
        id: c.id,
        title: c.title,
        court: c.court ?? null,
        next_hearing: c.next_hearing ?? null,
      })),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ((ts ?? []) as any[]).map((t) => ({
        id: t.id,
        title: t.title,
        due_date: t.due_date ?? null,
        status: t.status ?? null,
        case_id: t.case_id ?? null,
      })),
      from,
      to,
      own,
    );
    setEvents([...own, ...derived].sort((a, b) => a.start_at.localeCompare(b.start_at)));
    setCases((cs ?? []) as CaseLite[]);
    setClients((cl ?? []) as ClientLite[]);
    setLoading(false);
  };
  useEffect(() => {
    load(); /* eslint-disable-next-line */
  }, [cursor.getFullYear(), cursor.getMonth()]);

  const openCreate = (preset?: Date) => {
    setEditing(null);
    const base = preset ?? new Date();
    base.setMinutes(0, 0, 0);
    const iso = new Date(base.getTime() - base.getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 16);
    setForm({ ...empty, start_at: iso });
    setOpen(true);
  };
  const openEdit = (ev: CalEvent) => {
    if (ev.derived && ev.link) {
      navigate(ev.link); // türeyen girdi kaynağında (dava / görevler) düzenlenir
      return;
    }
    setEditing(ev);
    const toLocal = (s: string | null) => {
      if (!s) return "";
      const d = new Date(s);
      return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    };
    setForm({
      title: ev.title,
      description: ev.description ?? "",
      event_type: ev.event_type as EvForm["event_type"],
      start_at: toLocal(ev.start_at),
      end_at: toLocal(ev.end_at),
      all_day: ev.all_day,
      location: ev.location ?? "",
      case_id: ev.case_id ?? "",
      client_id: ev.client_id ?? "",
      reminder_minutes: ev.reminder_minutes ? String(ev.reminder_minutes) : "",
    });
    setOpen(true);
  };

  const save = async () => {
    const parsed = schema.safeParse(form);
    if (!parsed.success) {
      toast.error(parsed.error.issues[0].message);
      return;
    }
    if (!user) return;
    setSaving(true);
    const payload = {
      title: parsed.data.title,
      description: parsed.data.description || null,
      event_type: parsed.data.event_type,
      start_at: new Date(parsed.data.start_at).toISOString(),
      end_at: parsed.data.end_at ? new Date(parsed.data.end_at).toISOString() : null,
      all_day: parsed.data.all_day,
      location: parsed.data.location || null,
      case_id: parsed.data.case_id || null,
      client_id: parsed.data.client_id || null,
      reminder_minutes: parsed.data.reminder_minutes
        ? parseInt(parsed.data.reminder_minutes)
        : null,
    };
    if (editing) {
      const { error } = await supabase.from("calendar_events").update(payload).eq("id", editing.id);
      if (error) toast.error(error.message);
      else {
        toast.success("Etkinlik güncellendi");
        setOpen(false);
        load();
      }
    } else {
      const { error } = await supabase
        .from("calendar_events")
        .insert({ ...payload, owner_id: user.id });
      if (error) toast.error(error.message);
      else {
        toast.success("Etkinlik eklendi");
        setOpen(false);
        load();
      }
    }
    setSaving(false);
  };

  const remove = async (id: string) => {
    const { error } = await supabase.from("calendar_events").delete().eq("id", id);
    if (error) toast.error(error.message);
    else {
      toast.success("Silindi");
      load();
    }
  };

  // Month grid cells (Mon-first)
  const cells = useMemo(() => {
    const first = startOfMonth(cursor);
    const total = endOfMonth(cursor).getDate();
    // 0=Sun..6=Sat -> shift to Mon=0
    const offset = (first.getDay() + 6) % 7;
    const arr: (Date | null)[] = [...Array(offset).fill(null)];
    for (let d = 1; d <= total; d++) arr.push(new Date(cursor.getFullYear(), cursor.getMonth(), d));
    while (arr.length % 7 !== 0) arr.push(null);
    return arr;
  }, [cursor]);

  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();

  const today = new Date();
  const eventsByDay = useMemo(() => {
    const map = new Map<string, CalEvent[]>();
    events.forEach((e) => {
      const d = new Date(e.start_at);
      const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
      const arr = map.get(key) ?? [];
      arr.push(e);
      map.set(key, arr);
    });
    return map;
  }, [events]);

  const todaysEvents = events
    .filter((e) => sameDay(new Date(e.start_at), today))
    .sort((a, b) => a.start_at.localeCompare(b.start_at));
  const upcoming = events
    .filter((e) => new Date(e.start_at) >= today)
    .sort((a, b) => a.start_at.localeCompare(b.start_at))
    .slice(0, 8);

  const monthLabel = cursor.toLocaleDateString("tr-TR", { month: "long", year: "numeric" });

  return (
    <DashboardLayout
      title="Takvim"
      subtitle="Duruşmalar, randevular ve son tarihler"
      actions={
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button variant="elite" size="sm" onClick={() => openCreate()}>
              <Plus className="h-4 w-4" />
              Yeni Etkinlik
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>{editing ? "Etkinliği Düzenle" : "Yeni Etkinlik"}</DialogTitle>
            </DialogHeader>
            <div className="grid grid-cols-2 gap-4 py-2">
              <div className="col-span-2 space-y-1.5">
                <Label>Başlık *</Label>
                <Input
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="Örn: Asliye Hukuk Duruşması"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Tür</Label>
                <Select
                  value={form.event_type}
                  onValueChange={(v: EvForm["event_type"]) => setForm({ ...form, event_type: v })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(typeLabel).map(([k, v]) => (
                      <SelectItem key={k} value={k}>
                        {v}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Konum</Label>
                <Input
                  value={form.location}
                  onChange={(e) => setForm({ ...form, location: e.target.value })}
                  placeholder="Adliye, salon no..."
                />
              </div>
              <div className="space-y-1.5">
                <Label>Başlangıç *</Label>
                <Input
                  type="datetime-local"
                  value={form.start_at}
                  onChange={(e) => setForm({ ...form, start_at: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Bitiş</Label>
                <Input
                  type="datetime-local"
                  value={form.end_at}
                  onChange={(e) => setForm({ ...form, end_at: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label>İlgili Dava</Label>
                <Select
                  value={form.case_id || "none"}
                  onValueChange={(v) => setForm({ ...form, case_id: v === "none" ? "" : v })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Seçiniz" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Yok</SelectItem>
                    {cases.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        {c.case_no ? `${c.case_no} — ` : ""}
                        {c.title}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>İlgili Müvekkil</Label>
                <Select
                  value={form.client_id || "none"}
                  onValueChange={(v) => setForm({ ...form, client_id: v === "none" ? "" : v })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Seçiniz" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Yok</SelectItem>
                    {clients.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        {c.full_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Hatırlatma (dakika önce)</Label>
                <Select
                  value={form.reminder_minutes || "none"}
                  onValueChange={(v) =>
                    setForm({ ...form, reminder_minutes: v === "none" ? "" : v })
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Yok" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Yok</SelectItem>
                    <SelectItem value="15">15 dakika</SelectItem>
                    <SelectItem value="30">30 dakika</SelectItem>
                    <SelectItem value="60">1 saat</SelectItem>
                    <SelectItem value="1440">1 gün</SelectItem>
                    <SelectItem value="4320">3 gün</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="col-span-2 space-y-1.5">
                <Label>Açıklama</Label>
                <Textarea
                  rows={3}
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                />
              </div>
              <label className="col-span-2 flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.all_day}
                  onChange={(e) => setForm({ ...form, all_day: e.target.checked })}
                />
                Tüm gün
              </label>
            </div>
            <DialogFooter>
              <Button variant="ghost" onClick={() => setOpen(false)}>
                İptal
              </Button>
              <Button variant="elite" onClick={save} disabled={saving}>
                {saving && <Loader2 className="h-4 w-4 animate-spin" />}
                {editing ? "Güncelle" : "Kaydet"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      }
    >
      {loading ? (
        <div className="py-20 flex justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="grid lg:grid-cols-4 gap-6">
          <div className="lg:col-span-3 rounded-2xl bg-card border border-border shadow-card-elite overflow-hidden">
            <div className="p-4 flex items-center justify-between border-b border-border">
              <div className="flex items-center gap-2">
                <button
                  onClick={() =>
                    setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))
                  }
                  className="h-9 w-9 rounded-md hover:bg-secondary flex items-center justify-center"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <h3 className="font-serif text-xl font-semibold capitalize">{monthLabel}</h3>
                <button
                  onClick={() =>
                    setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))
                  }
                  className="h-9 w-9 rounded-md hover:bg-secondary flex items-center justify-center"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
                <Button variant="ghost" size="sm" onClick={() => setCursor(new Date())}>
                  Bugün
                </Button>
              </div>
              <div className="flex gap-1 text-xs">
                {(["month", "agenda"] as const).map((v) => (
                  <button
                    key={v}
                    onClick={() => setView(v)}
                    className={cn(
                      "px-3 py-1.5 rounded-md",
                      view === v
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:bg-secondary",
                    )}
                  >
                    {v === "month" ? "Ay" : "Ajanda"}
                  </button>
                ))}
              </div>
            </div>

            {view === "month" ? (
              <>
                <div className="grid grid-cols-7 border-b border-border bg-secondary/30">
                  {dayNames.map((d) => (
                    <div
                      key={d}
                      className="px-3 py-2 text-[11px] uppercase tracking-wider text-muted-foreground font-semibold"
                    >
                      {d}
                    </div>
                  ))}
                </div>
                <div className="grid grid-cols-7">
                  {cells.map((day, idx) => {
                    const key = day
                      ? `${day.getFullYear()}-${day.getMonth()}-${day.getDate()}`
                      : "";
                    const evts = day ? (eventsByDay.get(key) ?? []) : [];
                    const isToday = day && sameDay(day, today);
                    return (
                      <div
                        key={idx}
                        className={cn(
                          "min-h-[110px] border-b border-r border-border p-2 last:border-r-0 group",
                          !day && "bg-secondary/20",
                          day && "cursor-pointer hover:bg-secondary/40",
                        )}
                        onClick={() =>
                          day &&
                          openCreate(new Date(day.getFullYear(), day.getMonth(), day.getDate(), 9))
                        }
                      >
                        {day && (
                          <>
                            <div
                              className={cn(
                                "text-xs font-medium mb-1 inline-flex h-6 w-6 items-center justify-center rounded-full",
                                isToday && "bg-primary text-primary-foreground",
                              )}
                            >
                              {day.getDate()}
                            </div>
                            <div className="space-y-1">
                              {evts.slice(0, 3).map((e) => (
                                <div
                                  key={e.id}
                                  onClick={(ev) => {
                                    ev.stopPropagation();
                                    openEdit(e);
                                  }}
                                  className={cn(
                                    "text-[10px] px-1.5 py-1 rounded truncate cursor-pointer",
                                    typeColor[e.event_type] || typeColor.other,
                                  )}
                                >
                                  {!e.all_day &&
                                    new Date(e.start_at).toLocaleTimeString("tr-TR", {
                                      hour: "2-digit",
                                      minute: "2-digit",
                                    })}{" "}
                                  {e.title}
                                </div>
                              ))}
                              {evts.length > 3 && (
                                <div className="text-[10px] text-muted-foreground px-1.5">
                                  +{evts.length - 3} daha
                                </div>
                              )}
                            </div>
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              </>
            ) : (
              <div className="divide-y divide-border">
                {events.length === 0 && (
                  <div className="text-center py-16 text-sm text-muted-foreground">
                    Bu ay için etkinlik yok
                  </div>
                )}
                {events.map((e) => (
                  <div key={e.id} className="p-4 flex items-center gap-4 hover:bg-secondary/30">
                    <div className="w-20 text-xs text-muted-foreground font-mono">
                      <div>
                        {new Date(e.start_at).toLocaleDateString("tr-TR", {
                          day: "2-digit",
                          month: "short",
                        })}
                      </div>
                      {!e.all_day && (
                        <div>
                          {new Date(e.start_at).toLocaleTimeString("tr-TR", {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </div>
                      )}
                    </div>
                    <span
                      className={cn(
                        "text-[10px] px-2 py-0.5 rounded",
                        typeColor[e.event_type] || typeColor.other,
                      )}
                    >
                      {typeLabel[e.event_type]}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">{e.title}</div>
                      {e.location && (
                        <div className="text-xs text-muted-foreground truncate">{e.location}</div>
                      )}
                    </div>
                    {e.derived && (
                      <Button variant="outline" size="sm" onClick={() => openEdit(e)}>
                        {e.derived === "case" ? "Davayı aç" : "Görevlere git"}
                      </Button>
                    )}
                    {!e.derived && (
                      <Button variant="ghost" size="icon" onClick={() => openEdit(e)}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                    )}
                    {!e.derived && (
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="ghost" size="icon" className="text-destructive">
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Etkinliği sil?</AlertDialogTitle>
                            <AlertDialogDescription>Bu işlem geri alınamaz.</AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>İptal</AlertDialogCancel>
                            <AlertDialogAction onClick={() => remove(e.id)}>Sil</AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-4">
            <div className="p-5 rounded-2xl bg-card border border-border shadow-card-elite">
              <h4 className="font-serif font-semibold mb-3 flex items-center gap-2">
                <CalendarIcon className="h-4 w-4" />
                Bugün
              </h4>
              {todaysEvents.length === 0 ? (
                <div className="text-xs text-muted-foreground">Bugün etkinlik yok</div>
              ) : (
                <div className="space-y-3">
                  {todaysEvents.map((e) => (
                    <div
                      key={e.id}
                      onClick={() => openEdit(e)}
                      className="flex gap-3 text-xs cursor-pointer hover:bg-secondary/40 -mx-2 px-2 py-1.5 rounded"
                    >
                      <div className="font-mono text-muted-foreground w-12">
                        {e.all_day
                          ? "—"
                          : new Date(e.start_at).toLocaleTimeString("tr-TR", {
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                      </div>
                      <div className="min-w-0">
                        <div className="font-medium truncate">{e.title}</div>
                        <div className="text-muted-foreground mt-0.5">
                          {typeLabel[e.event_type]}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="p-5 rounded-2xl bg-card border border-border shadow-card-elite">
              <h4 className="font-serif font-semibold mb-3">Yaklaşan</h4>
              {upcoming.length === 0 ? (
                <div className="text-xs text-muted-foreground">Yaklaşan etkinlik yok</div>
              ) : (
                <div className="space-y-3 text-xs">
                  {upcoming.map((e) => (
                    <div
                      key={e.id}
                      onClick={() => openEdit(e)}
                      className="flex gap-2 cursor-pointer hover:bg-secondary/40 -mx-2 px-2 py-1.5 rounded"
                    >
                      <span
                        className={cn(
                          "h-2 w-2 rounded-full mt-1.5 shrink-0",
                          typeColor[e.event_type]?.split(" ")[0] || "bg-muted",
                        )}
                      />
                      <div className="min-w-0">
                        <div className="font-medium truncate">{e.title}</div>
                        <div className="text-muted-foreground">
                          {new Date(e.start_at).toLocaleString("tr-TR", {
                            day: "2-digit",
                            month: "short",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="p-5 rounded-2xl bg-card border border-border shadow-card-elite">
              <h4 className="font-serif font-semibold mb-3">Lejant</h4>
              <div className="space-y-2 text-xs">
                {Object.entries(typeLabel).map(([k, v]) => (
                  <div key={k} className="flex items-center gap-2">
                    <span className={cn("h-2.5 w-2.5 rounded-sm", typeColor[k])} />
                    <span>{v}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/calendar")({
  component: CalendarPage,
});

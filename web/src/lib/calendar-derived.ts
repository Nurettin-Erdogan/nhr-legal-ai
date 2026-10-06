/**
 * Takvimde kayıtlı etkinliklerin yanında gösterilen, başka kayıtlardan türeyen girdiler: davanın "Sonraki Duruşma" tarihi ve görevin
 * son tarihi. Kullanıcı duruşma tarihini davaya yazınca takvimde ayrıca etkinlik açması beklenmez; takvim bu kayıtları kendisi
 * gösterir (takvim boş kalıyor, duruşma yalnız Ana Sayfa'da görünüyordu). Türeyen girdi takvimde düzenlenmez: kaynağı olan dava ya da
 * görev kaydına götürür. Aynı davaya aynı saatte elle duruşma etkinliği açılmışsa türeyen girdi tekrar gösterilmez.
 */
export interface DerivedCase {
  id: string;
  title: string;
  court?: string | null;
  next_hearing: string | null;
}

export interface DerivedTask {
  id: string;
  title: string;
  due_date: string | null;
  status: string | null;
  case_id?: string | null;
}

export interface ExistingEvent {
  event_type: string;
  case_id: string | null;
  start_at: string;
}

export interface DerivedEvent {
  id: string;
  owner_id: string;
  title: string;
  description: string | null;
  event_type: "hearing" | "task";
  start_at: string;
  end_at: string | null;
  all_day: boolean;
  location: string | null;
  case_id: string | null;
  client_id: string | null;
  color: string | null;
  reminder_minutes: number | null;
  /** Kaynak kayıt türü; türeyen girdi takvimde düzenlenemez. */
  derived: "case" | "task";
  /** Kaynağın sayfası. */
  link: string;
}

const minuteKey = (value: string) => Math.floor(new Date(value).getTime() / 60000);

function within(value: string | null, from: Date, to: Date): value is string {
  if (!value) return false;
  const time = new Date(value).getTime();
  return Number.isFinite(time) && time >= from.getTime() && time <= to.getTime();
}

export function deriveCalendarEvents(
  cases: DerivedCase[],
  tasks: DerivedTask[],
  from: Date,
  to: Date,
  existing: ExistingEvent[] = [],
): DerivedEvent[] {
  const taken = new Set(
    existing.filter((event) => event.event_type === "hearing" && event.case_id).map((event) => `${event.case_id}:${minuteKey(event.start_at)}`),
  );
  const derived: DerivedEvent[] = [];
  for (const item of cases) {
    if (!within(item.next_hearing, from, to) || taken.has(`${item.id}:${minuteKey(item.next_hearing)}`)) continue;
    derived.push({
      id: `case:${item.id}`,
      owner_id: "",
      title: `Duruşma: ${item.title}`,
      description: null,
      event_type: "hearing",
      start_at: item.next_hearing,
      end_at: null,
      all_day: false,
      location: item.court ?? null,
      case_id: item.id,
      client_id: null,
      color: null,
      reminder_minutes: null,
      derived: "case",
      link: `/dashboard/cases/${item.id}`,
    });
  }
  for (const task of tasks) {
    if (task.status === "done" || !within(task.due_date, from, to)) continue;
    derived.push({
      id: `task:${task.id}`,
      owner_id: "",
      title: `Görev: ${task.title}`,
      description: null,
      event_type: "task",
      start_at: task.due_date,
      end_at: null,
      all_day: false,
      location: null,
      case_id: task.case_id ?? null,
      client_id: null,
      color: null,
      reminder_minutes: null,
      derived: "task",
      link: "/dashboard/tasks",
    });
  }
  return derived.sort((a, b) => a.start_at.localeCompare(b.start_at));
}

/** Ana sayfa özeti (arayüzden bağımsız mantık): yaklaşan duruşmalar, açık görevler, son davalar. Veri kullanıcıya özel RLS'li ofis uçlarından gelir. */

export interface HomeCase {
  id: string;
  title: string;
  case_no: string | null;
  court: string | null;
  status: string;
  next_hearing: string | null;
  created_at: string;
}

export interface HomeTask {
  id: string;
  title: string;
  status: string;
  due_date: string | null;
  case_id: string | null;
}

const DAY = 24 * 60 * 60 * 1000;

const startOfDay = (date: Date): number =>
  new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();

/** Tarih (YYYY-MM-DD ya da ISO) → yerel gün başlangıcı; geçersizse null. Saat dilimi kayması olmasın diye yalnız tarih kısmı okunur. */
export function localDay(value: string | null | undefined): number | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  // Date taşan değerleri kaydırır (13. ay, 45. gün): gidiş-dönüş tutmuyorsa geçersiz tarihtir.
  const valid =
    date.getFullYear() === Number(match[1]) &&
    date.getMonth() === Number(match[2]) - 1 &&
    date.getDate() === Number(match[3]);
  return valid ? date.getTime() : null;
}

/** Bugünden kaç gün sonra (negatif: geçmiş). */
export function daysUntil(value: string | null | undefined, now: Date = new Date()): number | null {
  const day = localDay(value);
  return day === null ? null : Math.round((day - startOfDay(now)) / DAY);
}

export function relativeDay(days: number | null): string {
  if (days === null) return "";
  if (days === 0) return "bugün";
  if (days === 1) return "yarın";
  if (days === -1) return "dün";
  return days > 0 ? `${days} gün sonra` : `${-days} gün gecikti`;
}

/** Bugün ve sonrası duruşması olan açık davalar, en yakın önce. Kapalı davalar listelenmez. */
export function upcomingHearings(
  cases: HomeCase[],
  now: Date = new Date(),
  limit = 5,
): (HomeCase & { days: number })[] {
  return cases
    .filter((item) => item.status !== "closed")
    .flatMap((item) => {
      const days = daysUntil(item.next_hearing, now);
      return days !== null && days >= 0 ? [{ ...item, days }] : [];
    })
    .sort((a, b) => a.days - b.days || a.title.localeCompare(b.title, "tr"))
    .slice(0, limit);
}

/** Tamamlanmamış görevler: önce süresi geçenler (en eski önce), sonra yaklaşanlar, süresizler en sonda. */
export function openTasks(
  tasks: HomeTask[],
  now: Date = new Date(),
  limit = 6,
): (HomeTask & { days: number | null })[] {
  return tasks
    .filter((task) => task.status !== "done")
    .map((task) => ({ ...task, days: daysUntil(task.due_date, now) }))
    .sort(
      (a, b) =>
        (a.days ?? Number.MAX_SAFE_INTEGER) - (b.days ?? Number.MAX_SAFE_INTEGER) ||
        a.title.localeCompare(b.title, "tr"),
    )
    .slice(0, limit);
}

export const overdueCount = (tasks: { days: number | null }[]): number =>
  tasks.filter((task) => task.days !== null && task.days < 0).length;

export function recentCases(cases: HomeCase[], limit = 5): HomeCase[] {
  return [...cases].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, limit);
}

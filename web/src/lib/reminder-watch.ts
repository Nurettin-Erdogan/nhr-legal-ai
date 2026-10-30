/**
 * Zamanı gelen hatırlatmaların seçimi (saf işlevler; bileşen ve zamanlayıcıdan bağımsız, test edilebilir).
 *
 * Hatırlatma zamanı geçince sessizce "Geçmiş" oluyordu: ne bildirim ne zil vardı. Kural: durumu `pending` olan ve zamanı gelmiş
 * her hatırlatma zilde görünür; kullanıcıya daha önce gösterilmemiş olanlar (`notified_at` boş) bir kez ekranda duyurulur.
 */
export interface WatchReminder {
  id: string;
  title: string;
  note?: string | null;
  remind_at: string;
  status: string;
  channel?: string | null;
  notified_at?: string | null;
}

const time = (value: string) => new Date(value).getTime();

/** Zamanı gelmiş, hâlâ bekleyen hatırlatmalar; en yeni zamanlı önce. Bozuk tarihli kayıt alınmaz. */
export function dueReminders<T extends WatchReminder>(list: T[], now: Date = new Date()): T[] {
  return list
    .filter(
      (item) =>
        item.status === "pending" &&
        Number.isFinite(time(item.remind_at)) &&
        time(item.remind_at) <= now.getTime(),
    )
    .sort((a, b) => time(b.remind_at) - time(a.remind_at));
}

/**
 * İlk kez duyurulacaklar. `seen`: bu tarayıcıda daha önce duyurulmuş kimlikler (sunucu `notified_at` yazamazsa yedek).
 * Bir günden eski hatırlatma duyurulmaz (uzun aradan sonra açılışta bildirim yağmuru olmasın); zilde yine görünür.
 */
export function toAnnounce<T extends WatchReminder>(
  list: T[],
  now: Date = new Date(),
  seen: ReadonlySet<string> = new Set(),
): T[] {
  const dayAgo = now.getTime() - 24 * 3600 * 1000;
  return dueReminders(list, now).filter(
    (item) => !item.notified_at && !seen.has(item.id) && time(item.remind_at) >= dayAgo,
  );
}

export function reminderTimeLabel(value: string, now: Date = new Date()): string {
  const date = new Date(value);
  const sameDay = date.toDateString() === now.toDateString();
  const clock = date.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
  return sameDay
    ? `Bugün ${clock}`
    : `${date.toLocaleDateString("tr-TR", { day: "2-digit", month: "short" })} ${clock}`;
}

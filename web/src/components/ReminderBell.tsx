import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, Check } from "lucide-react";
import { toast } from "sonner";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/components/AuthProvider";
import { useNavigate } from "@/lib/router-compat";
import { dueReminders, reminderTimeLabel, toAnnounce, type WatchReminder } from "@/lib/reminder-watch";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const POLL_MS = 60_000;
const SEEN_KEY = "jurisai.reminders.seen";

function readSeen(): Set<string> {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(SEEN_KEY) ?? "[]");
    return new Set(Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string").slice(-200) : []);
  } catch {
    return new Set();
  }
}

/**
 * Üst çubuktaki hatırlatma zili. Zamanı gelen hatırlatmaları dakikada bir yoklar, yenilerini ekranda bir kez duyurur ve zilde
 * sayısıyla gösterir. Duyurulan hatırlatmaya `notified_at` yazılır (başka cihazda/sayfada yeniden duyurulmaz); yazılamazsa bu
 * tarayıcıdaki liste yedek olur. Bildirim yalnız uygulama açıkken görünür: tarayıcı kapalıyken haber veren kanal e-postadır.
 */
export function ReminderBell() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [due, setDue] = useState<WatchReminder[]>([]);
  const seen = useRef<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    if (!user?.id) return;
    const nowIso = new Date().toISOString();
    let { data, error } = await supabase
      .from("reminders")
      .select("id, title, note, remind_at, status, channel, notified_at")
      .eq("status", "pending")
      .lte("remind_at", nowIso)
      .order("remind_at", { ascending: false })
      .limit(20);
    if (error) {
      // `notified_at` sütunu henüz yoksa (eski şema) onsuz okunur; tekrar duyuruyu tarayıcı listesi önler.
      ({ data, error } = await supabase
        .from("reminders")
        .select("id, title, note, remind_at, status, channel")
        .eq("status", "pending")
        .lte("remind_at", nowIso)
        .order("remind_at", { ascending: false })
        .limit(20));
    }
    if (error) return;
    const list = dueReminders((data ?? []) as WatchReminder[]);
    setDue(list);
    const fresh = toAnnounce(list, new Date(), seen.current);
    for (const item of fresh) {
      seen.current.add(item.id);
      toast(`Hatırlatma: ${item.title}`, { description: reminderTimeLabel(item.remind_at), duration: 15000 });
      void supabase.from("reminders").update({ notified_at: new Date().toISOString() }).eq("id", item.id);
    }
    if (fresh.length) {
      try {
        window.localStorage.setItem(SEEN_KEY, JSON.stringify([...seen.current].slice(-200)));
      } catch {
        // depolama kapalıysa yalnız bu oturumda hatırlanır
      }
    }
  }, [user?.id]);

  useEffect(() => {
    if (!user?.id) return;
    seen.current = readSeen();
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [user?.id, refresh]);

  const complete = async (id: string) => {
    const { error } = await supabase.from("reminders").update({ status: "done" }).eq("id", id);
    if (error) toast.error("Hatırlatma güncellenemedi");
    else setDue((list) => list.filter((item) => item.id !== id));
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="relative flex h-9 w-9 items-center justify-center rounded-full hover:bg-muted"
          aria-label={due.length ? `Hatırlatmalar: ${due.length} zamanı gelmiş` : "Hatırlatmalar"}
          data-testid="reminder-bell"
        >
          <Bell className="h-4 w-4" />
          {due.length > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold text-destructive-foreground">
              {due.length > 9 ? "9+" : due.length}
            </span>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>Zamanı gelen hatırlatmalar</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {due.length === 0 ? (
          <p className="px-2 py-3 text-sm text-muted-foreground">Zamanı gelmiş hatırlatma yok.</p>
        ) : (
          <ul className="max-h-80 space-y-1 overflow-y-auto px-1 py-1">
            {due.map((item) => (
              <li key={item.id} className="flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-muted/60">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{item.title}</p>
                  <p className="text-xs text-muted-foreground">{reminderTimeLabel(item.remind_at)}</p>
                  {item.note && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{item.note}</p>}
                </div>
                <button
                  type="button"
                  className="mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-background"
                  onClick={() => void complete(item.id)}
                >
                  <Check className="h-3 w-3" /> Tamamlandı
                </button>
              </li>
            ))}
          </ul>
        )}
        <DropdownMenuSeparator />
        <button type="button" className="w-full px-2 py-1.5 text-left text-sm underline" onClick={() => navigate("/dashboard/reminders")}>
          Tüm hatırlatmalar
        </button>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

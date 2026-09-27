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
import { Plus, Bell, Check, Loader2, Pencil, Trash2, MoreVertical, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import { useEffect, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/components/AuthProvider";
import { toast } from "sonner";
import { z } from "zod";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface Reminder {
  id: string;
  owner_id: string;
  title: string;
  note: string | null;
  remind_at: string;
  channel: string;
  status: string;
  case_id: string | null;
  task_id: string | null;
  event_id: string | null;
}
interface CaseLite {
  id: string;
  title: string;
  case_no: string | null;
}

const schema = z.object({
  title: z.string().trim().min(1, "Başlık gerekli").max(200),
  note: z.string().trim().max(1000).optional().or(z.literal("")),
  remind_at: z.string().min(1, "Zaman gerekli"),
  channel: z.enum(["in_app", "email"]),
  status: z.enum(["pending", "sent", "done", "cancelled"]),
  case_id: z.string().optional().or(z.literal("")),
});

type RForm = {
  title: string;
  note: string;
  remind_at: string;
  channel: "in_app" | "email";
  status: "pending" | "sent" | "done" | "cancelled";
  case_id: string;
};
const empty: RForm = {
  title: "",
  note: "",
  remind_at: "",
  channel: "in_app",
  status: "pending",
  case_id: "",
};

const statusLabel: Record<string, string> = {
  pending: "Bekliyor",
  sent: "Gönderildi",
  done: "Tamamlandı",
  cancelled: "İptal",
};
const channelLabel: Record<string, string> = { in_app: "Uygulama", email: "E-posta" };

const Reminders = () => {
  const { user } = useAuth();
  const [data, setData] = useState<Reminder[]>([]);
  const [cases, setCases] = useState<CaseLite[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Reminder | null>(null);
  const [form, setForm] = useState<RForm>(empty);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    const [{ data: r, error }, { data: cs }] = await Promise.all([
      supabase.from("reminders").select("*").order("remind_at", { ascending: true }),
      supabase.from("cases").select("id, title, case_no"),
    ]);
    if (error) toast.error(error.message);
    setData((r ?? []) as Reminder[]);
    setCases((cs ?? []) as CaseLite[]);
    setLoading(false);
  };
  useEffect(() => {
    load();
  }, []);

  const openCreate = () => {
    setEditing(null);
    const d = new Date();
    d.setMinutes(0, 0, 0);
    d.setHours(d.getHours() + 1);
    const iso = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    setForm({ ...empty, remind_at: iso });
    setOpen(true);
  };
  const openEdit = (r: Reminder) => {
    setEditing(r);
    const d = new Date(r.remind_at);
    setForm({
      title: r.title,
      note: r.note ?? "",
      remind_at: new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16),
      channel: r.channel as "in_app" | "email",
      status: r.status as RForm["status"],
      case_id: r.case_id ?? "",
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
      note: parsed.data.note || null,
      remind_at: new Date(parsed.data.remind_at).toISOString(),
      channel: parsed.data.channel,
      status: parsed.data.status,
      case_id: parsed.data.case_id || null,
    };
    if (editing) {
      const { error } = await supabase.from("reminders").update(payload).eq("id", editing.id);
      if (error) toast.error(error.message);
      else {
        toast.success("Hatırlatma güncellendi");
        setOpen(false);
        load();
      }
    } else {
      const { error } = await supabase.from("reminders").insert({ ...payload, owner_id: user.id });
      if (error) toast.error(error.message);
      else {
        toast.success("Hatırlatma eklendi");
        setOpen(false);
        load();
      }
    }
    setSaving(false);
  };

  const remove = async (id: string) => {
    const { error } = await supabase.from("reminders").delete().eq("id", id);
    if (error) toast.error(error.message);
    else {
      toast.success("Silindi");
      load();
    }
  };

  const setStatus = async (r: Reminder, status: RForm["status"]) => {
    const { error } = await supabase.from("reminders").update({ status }).eq("id", r.id);
    if (error) toast.error(error.message);
    else load();
  };

  const caseLabel = (id: string | null) => {
    if (!id) return null;
    const c = cases.find((x) => x.id === id);
    return c?.case_no ?? c?.title ?? null;
  };

  const isOverdue = (r: Reminder) => r.status === "pending" && new Date(r.remind_at) < new Date();

  return (
    <DashboardLayout
      title="Hatırlatmalar"
      subtitle="Duruşma, ödeme ve görev hatırlatmaları"
      actions={
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button variant="elite" size="sm" onClick={openCreate}>
              <Plus className="h-4 w-4" />
              Hatırlatma Ekle
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-xl">
            <DialogHeader>
              <DialogTitle>{editing ? "Hatırlatmayı Düzenle" : "Yeni Hatırlatma"}</DialogTitle>
            </DialogHeader>
            <div className="grid grid-cols-2 gap-4 py-2">
              <div className="col-span-2 space-y-1.5">
                <Label>Başlık *</Label>
                <Input
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="Örn: Müvekkili ara"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Zaman *</Label>
                <Input
                  type="datetime-local"
                  value={form.remind_at}
                  onChange={(e) => setForm({ ...form, remind_at: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Kanal</Label>
                <Select
                  value={form.channel}
                  onValueChange={(v: "in_app" | "email") => setForm({ ...form, channel: v })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="in_app">Uygulama içi</SelectItem>
                    <SelectItem value="email">E-posta</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Durum</Label>
                <Select
                  value={form.status}
                  onValueChange={(v: RForm["status"]) => setForm({ ...form, status: v })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="pending">Bekliyor</SelectItem>
                    <SelectItem value="sent">Gönderildi</SelectItem>
                    <SelectItem value="done">Tamamlandı</SelectItem>
                    <SelectItem value="cancelled">İptal</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>İlgili Dava</Label>
                <Select
                  value={form.case_id || "none"}
                  onValueChange={(v) => setForm({ ...form, case_id: v === "none" ? "" : v })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Yok" />
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
              <div className="col-span-2 space-y-1.5">
                <Label>Not</Label>
                <Textarea
                  rows={3}
                  value={form.note}
                  onChange={(e) => setForm({ ...form, note: e.target.value })}
                />
              </div>
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
      ) : data.length === 0 ? (
        <div className="text-center py-20 rounded-2xl bg-card border border-border">
          <Bell className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
          <h3 className="font-serif text-lg font-semibold mb-1">Henüz hatırlatma yok</h3>
          <p className="text-sm text-muted-foreground mb-4">İlk hatırlatmanı ekleyerek başla</p>
          <Button variant="elite" size="sm" onClick={openCreate}>
            <Plus className="h-4 w-4" />
            Hatırlatma Ekle
          </Button>
        </div>
      ) : (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
          {data.map((r) => {
            const overdue = isOverdue(r);
            const cl = caseLabel(r.case_id);
            return (
              <div
                key={r.id}
                className={cn(
                  "p-6 rounded-2xl bg-card border shadow-card-elite",
                  overdue ? "border-destructive/40" : "border-border",
                )}
              >
                <div className="flex items-start justify-between mb-4">
                  <div
                    className={cn(
                      "h-10 w-10 rounded-lg flex items-center justify-center",
                      r.status === "done"
                        ? "bg-success/10 text-success"
                        : overdue
                          ? "bg-destructive/10 text-destructive"
                          : "bg-accent-soft text-gold-deep",
                    )}
                  >
                    {r.status === "done" ? (
                      <Check className="h-5 w-5" />
                    ) : (
                      <Bell className="h-5 w-5" />
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    <span
                      className={cn(
                        "text-xs font-medium px-2.5 py-1 rounded-full border",
                        r.status === "done"
                          ? "bg-success/10 text-success border-success/20"
                          : r.status === "cancelled"
                            ? "bg-muted text-muted-foreground border-border"
                            : overdue
                              ? "bg-destructive/10 text-destructive border-destructive/20"
                              : "bg-warning/10 text-warning border-warning/20",
                      )}
                    >
                      {overdue && r.status === "pending" ? "Geçmiş" : statusLabel[r.status]}
                    </span>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button className="p-1 rounded hover:bg-secondary">
                          <MoreVertical className="h-4 w-4" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {r.status !== "done" && (
                          <DropdownMenuItem onClick={() => setStatus(r, "done")}>
                            Tamamla
                          </DropdownMenuItem>
                        )}
                        {r.status !== "cancelled" && (
                          <DropdownMenuItem onClick={() => setStatus(r, "cancelled")}>
                            İptal et
                          </DropdownMenuItem>
                        )}
                        <DropdownMenuItem onClick={() => openEdit(r)}>
                          <Pencil className="h-3.5 w-3.5 mr-2" />
                          Düzenle
                        </DropdownMenuItem>
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <DropdownMenuItem
                              onSelect={(e) => e.preventDefault()}
                              className="text-destructive"
                            >
                              <Trash2 className="h-3.5 w-3.5 mr-2" />
                              Sil
                            </DropdownMenuItem>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>Hatırlatmayı sil?</AlertDialogTitle>
                              <AlertDialogDescription>
                                Bu işlem geri alınamaz.
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>İptal</AlertDialogCancel>
                              <AlertDialogAction onClick={() => remove(r.id)}>
                                Sil
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>
                <h4 className="font-serif text-base font-semibold mb-1">{r.title}</h4>
                {r.note && (
                  <p className="text-xs text-muted-foreground mb-3 line-clamp-2">{r.note}</p>
                )}
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {new Date(r.remind_at).toLocaleString("tr-TR", {
                      dateStyle: "short",
                      timeStyle: "short",
                    })}
                  </span>
                  <span className="inline-flex items-center gap-1">{channelLabel[r.channel]}</span>
                </div>
                {cl && (
                  <div className="mt-3 pt-3 border-t border-border">
                    <span className="text-[10px] font-mono text-gold-deep">{cl}</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/reminders")({
  component: Reminders,
});

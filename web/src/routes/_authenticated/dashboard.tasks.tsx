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
  Plus,
  CheckCircle2,
  Circle,
  Clock,
  Loader2,
  Trash2,
  Pencil,
  MoreVertical,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useEffect, useMemo, useState } from "react";
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

interface Task {
  id: string;
  title: string;
  description: string | null;
  priority: string;
  status: string;
  due_date: string | null;
  case_id: string | null;
  owner_id: string;
  created_at: string;
}
interface CaseLite {
  id: string;
  title: string;
  case_no: string | null;
}

const schema = z.object({
  title: z.string().trim().min(1, "Başlık gerekli").max(200),
  description: z.string().trim().max(1000).optional().or(z.literal("")),
  priority: z.enum(["low", "medium", "high", "urgent"]),
  status: z.enum(["todo", "in_progress", "done"]),
  due_date: z.string().optional().or(z.literal("")),
  case_id: z.string().optional().or(z.literal("")),
});

type TaskForm = {
  title: string;
  description: string;
  priority: "low" | "medium" | "high" | "urgent";
  status: "todo" | "in_progress" | "done";
  due_date: string;
  case_id: string;
};
const empty: TaskForm = {
  title: "",
  description: "",
  priority: "medium",
  status: "todo",
  due_date: "",
  case_id: "",
};

const priorityColor: Record<string, string> = {
  urgent: "bg-destructive/10 text-destructive border-destructive/20",
  high: "bg-destructive/10 text-destructive border-destructive/20",
  medium: "bg-warning/10 text-warning border-warning/20",
  low: "bg-muted text-muted-foreground border-border",
};
const priorityLabel: Record<string, string> = {
  urgent: "Acil",
  high: "Yüksek",
  medium: "Orta",
  low: "Düşük",
};

const statusIcon = (s: string) => {
  if (s === "done") return <CheckCircle2 className="h-4 w-4 text-success" />;
  if (s === "in_progress") return <Clock className="h-4 w-4 text-gold" />;
  return <Circle className="h-4 w-4 text-muted-foreground" />;
};

const Tasks = () => {
  const { user } = useAuth();
  const [data, setData] = useState<Task[]>([]);
  const [cases, setCases] = useState<CaseLite[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Task | null>(null);
  const [form, setForm] = useState<TaskForm>(empty);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    const [{ data: t, error }, { data: cs }] = await Promise.all([
      supabase.from("tasks").select("*").order("created_at", { ascending: false }),
      supabase.from("cases").select("id, title, case_no").order("created_at", { ascending: false }),
    ]);
    if (error) toast.error(error.message);
    setData((t ?? []) as Task[]);
    setCases((cs ?? []) as CaseLite[]);
    setLoading(false);
  };
  useEffect(() => {
    load();
  }, []);

  const openCreate = () => {
    setEditing(null);
    setForm(empty);
    setOpen(true);
  };
  const openEdit = (t: Task) => {
    setEditing(t);
    setForm({
      title: t.title,
      description: t.description ?? "",
      priority: (t.priority as "low" | "medium" | "high" | "urgent") ?? "medium",
      status: (t.status as "todo" | "in_progress" | "done") ?? "todo",
      due_date: t.due_date ? t.due_date.slice(0, 16) : "",
      case_id: t.case_id ?? "",
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
      priority: parsed.data.priority,
      status: parsed.data.status,
      due_date: parsed.data.due_date ? new Date(parsed.data.due_date).toISOString() : null,
      case_id: parsed.data.case_id || null,
    };
    if (editing) {
      const { error } = await supabase.from("tasks").update(payload).eq("id", editing.id);
      if (error) toast.error(error.message);
      else {
        toast.success("Görev güncellendi");
        setOpen(false);
        load();
      }
    } else {
      const { error } = await supabase.from("tasks").insert({ ...payload, owner_id: user.id });
      if (error) toast.error(error.message);
      else {
        toast.success("Görev eklendi");
        setOpen(false);
        load();
      }
    }
    setSaving(false);
  };

  const remove = async (id: string) => {
    const { error } = await supabase.from("tasks").delete().eq("id", id);
    if (error) toast.error(error.message);
    else {
      toast.success("Silindi");
      load();
    }
  };

  const setStatus = async (t: Task, status: "todo" | "in_progress" | "done") => {
    const { error } = await supabase.from("tasks").update({ status }).eq("id", t.id);
    if (error) toast.error(error.message);
    else load();
  };

  const cols = useMemo(
    () => [
      { key: "todo", title: "Bekliyor", items: data.filter((t) => t.status === "todo") },
      {
        key: "in_progress",
        title: "Devam Ediyor",
        items: data.filter((t) => t.status === "in_progress"),
      },
      { key: "done", title: "Tamamlandı", items: data.filter((t) => t.status === "done") },
    ],
    [data],
  );

  const caseLabel = (id: string | null) => {
    if (!id) return null;
    const c = cases.find((x) => x.id === id);
    return c?.case_no ?? c?.title ?? null;
  };

  return (
    <DashboardLayout
      title="İş Takibi"
      subtitle="Ekip içi iş takibi"
      actions={
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button variant="elite" size="sm" onClick={openCreate}>
              <Plus className="h-4 w-4" />
              Yeni Görev
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-xl">
            <DialogHeader>
              <DialogTitle>{editing ? "Görevi Düzenle" : "Yeni Görev"}</DialogTitle>
            </DialogHeader>
            <div className="grid grid-cols-2 gap-4 py-2">
              <div className="col-span-2 space-y-1.5">
                <Label>Başlık *</Label>
                <Input
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="Örn: Dilekçe hazırla"
                />
              </div>
              <div className="col-span-2 space-y-1.5">
                <Label>Açıklama</Label>
                <Textarea
                  rows={3}
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Öncelik</Label>
                <Select
                  value={form.priority}
                  onValueChange={(v: "low" | "medium" | "high" | "urgent") =>
                    setForm({ ...form, priority: v })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="low">Düşük</SelectItem>
                    <SelectItem value="medium">Orta</SelectItem>
                    <SelectItem value="high">Yüksek</SelectItem>
                    <SelectItem value="urgent">Acil</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Durum</Label>
                <Select
                  value={form.status}
                  onValueChange={(v: "todo" | "in_progress" | "done") =>
                    setForm({ ...form, status: v })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="todo">Bekliyor</SelectItem>
                    <SelectItem value="in_progress">Devam Ediyor</SelectItem>
                    <SelectItem value="done">Tamamlandı</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Son Tarih</Label>
                <Input
                  type="datetime-local"
                  value={form.due_date}
                  onChange={(e) => setForm({ ...form, due_date: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label>İlgili Dava</Label>
                <Select
                  value={form.case_id}
                  onValueChange={(v) => setForm({ ...form, case_id: v })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Seçiniz (opsiyonel)" />
                  </SelectTrigger>
                  <SelectContent>
                    {cases.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        {c.case_no ? `${c.case_no} — ` : ""}
                        {c.title}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
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
      ) : (
        <div className="grid lg:grid-cols-3 gap-5">
          {cols.map((col) => (
            <div key={col.key} className="rounded-2xl bg-secondary/40 border border-border p-4">
              <div className="flex items-center justify-between mb-4 px-1">
                <h3 className="font-serif text-lg font-semibold">{col.title}</h3>
                <span className="text-xs px-2 py-0.5 rounded-full bg-card border border-border">
                  {col.items.length}
                </span>
              </div>
              <div className="space-y-3">
                {col.items.length === 0 && (
                  <div className="text-center text-xs text-muted-foreground py-8">Boş</div>
                )}
                {col.items.map((t) => {
                  const cl = caseLabel(t.case_id);
                  return (
                    <div
                      key={t.id}
                      className="p-4 rounded-xl bg-card border border-border shadow-card-elite hover:shadow-elegant transition"
                    >
                      <div className="flex items-start justify-between gap-2 mb-2">
                        <div className="flex items-start gap-2 flex-1 min-w-0">
                          {statusIcon(t.status)}
                          <div className="text-sm font-medium leading-snug">{t.title}</div>
                        </div>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button className="p-1 rounded hover:bg-secondary shrink-0">
                              <MoreVertical className="h-4 w-4" />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {t.status !== "todo" && (
                              <DropdownMenuItem onClick={() => setStatus(t, "todo")}>
                                Beklemeye al
                              </DropdownMenuItem>
                            )}
                            {t.status !== "in_progress" && (
                              <DropdownMenuItem onClick={() => setStatus(t, "in_progress")}>
                                Devam ettir
                              </DropdownMenuItem>
                            )}
                            {t.status !== "done" && (
                              <DropdownMenuItem onClick={() => setStatus(t, "done")}>
                                Tamamla
                              </DropdownMenuItem>
                            )}
                            <DropdownMenuItem onClick={() => openEdit(t)}>
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
                                  <AlertDialogTitle>Görevi sil?</AlertDialogTitle>
                                  <AlertDialogDescription>
                                    Bu işlem geri alınamaz.
                                  </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                  <AlertDialogCancel>İptal</AlertDialogCancel>
                                  <AlertDialogAction onClick={() => remove(t.id)}>
                                    Sil
                                  </AlertDialogAction>
                                </AlertDialogFooter>
                              </AlertDialogContent>
                            </AlertDialog>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                      {t.description && (
                        <p className="text-xs text-muted-foreground line-clamp-2 ml-6">
                          {t.description}
                        </p>
                      )}
                      <div className="mt-3 flex items-center justify-between text-xs">
                        <span
                          className={cn(
                            "inline-flex items-center px-2 py-0.5 rounded border font-medium",
                            priorityColor[t.priority],
                          )}
                        >
                          {priorityLabel[t.priority]}
                        </span>
                        {t.due_date && (
                          <span className="text-muted-foreground">
                            {new Date(t.due_date).toLocaleDateString("tr-TR")}
                          </span>
                        )}
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
            </div>
          ))}
        </div>
      )}
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/tasks")({
  component: Tasks,
});

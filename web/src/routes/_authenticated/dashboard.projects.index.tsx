import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Link } from "@/lib/router-compat";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Plus, FolderKanban, Loader2, Trash2 } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/components/AuthProvider";
import { toast } from "sonner";
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

interface Project {
  id: string;
  name: string;
  description: string | null;
  status: string;
  color: string | null;
  case_id: string | null;
  client_id: string | null;
  created_at: string;
}

interface CaseRow {
  id: string;
  title: string;
}
interface ClientRow {
  id: string;
  full_name: string;
}

function Projects() {
  const { session } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [clients, setClients] = useState<ClientRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    case_id: "",
    client_id: "",
    color: "#C8A24B",
  });

  const load = async () => {
    setLoading(true);
    const [{ data: pj }, { data: cs }, { data: cl }] = await Promise.all([
      supabase.from("projects").select("*").order("created_at", { ascending: false }),
      supabase
        .from("cases")
        .select("id, title")
        .order("created_at", { ascending: false })
        .limit(200),
      supabase
        .from("clients")
        .select("id, full_name")
        .order("created_at", { ascending: false })
        .limit(200),
    ]);
    setProjects((pj ?? []) as Project[]);
    setCases((cs ?? []) as CaseRow[]);
    setClients((cl ?? []) as ClientRow[]);
    setLoading(false);
  };
  useEffect(() => {
    load();
  }, []);

  const create = async () => {
    if (!session) return toast.error("Oturum gerekli");
    if (form.name.trim().length < 2) return toast.error("Proje adı gerekli");
    setSaving(true);
    const { error } = await supabase.from("projects").insert({
      owner_id: session.user.id,
      name: form.name.trim(),
      description: form.description.trim() || null,
      case_id: form.case_id || null,
      client_id: form.client_id || null,
      color: form.color || null,
    });
    setSaving(false);
    if (error) return toast.error(error.message);
    toast.success("Proje oluşturuldu");
    setOpen(false);
    setForm({ name: "", description: "", case_id: "", client_id: "", color: "#C8A24B" });
    load();
  };

  const remove = async (id: string) => {
    const { error } = await supabase.from("projects").delete().eq("id", id);
    if (error) return toast.error(error.message);
    toast.success("Silindi");
    load();
  };

  return (
    <DashboardLayout
      title="Projeler"
      subtitle="Davalarını workspace olarak yönet — notlar, AI çıktıları ve dosyalar tek yerde"
      actions={
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button variant="elite">
              <Plus className="h-4 w-4" /> Yeni Proje
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Yeni Proje</DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              <div>
                <Label>Proje adı</Label>
                <Input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="Ör. Ahmet Yılmaz - Tazminat Davası"
                />
              </div>
              <div>
                <Label>Açıklama</Label>
                <Textarea
                  rows={3}
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label>Bağlı Dava</Label>
                  <Select
                    value={form.case_id}
                    onValueChange={(v) => setForm({ ...form, case_id: v })}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Seçiniz (ops.)" />
                    </SelectTrigger>
                    <SelectContent>
                      {cases.map((c) => (
                        <SelectItem key={c.id} value={c.id}>
                          {c.title}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Müvekkil</Label>
                  <Select
                    value={form.client_id}
                    onValueChange={(v) => setForm({ ...form, client_id: v })}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Seçiniz (ops.)" />
                    </SelectTrigger>
                    <SelectContent>
                      {clients.map((c) => (
                        <SelectItem key={c.id} value={c.id}>
                          {c.full_name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div>
                <Label>Renk</Label>
                <Input
                  type="color"
                  value={form.color}
                  onChange={(e) => setForm({ ...form, color: e.target.value })}
                  className="h-10 w-20"
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setOpen(false)}>
                İptal
              </Button>
              <Button variant="elite" onClick={create} disabled={saving}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Oluştur
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      }
    >
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : projects.length === 0 ? (
        <div className="rounded-2xl border border-border bg-card p-16 text-center">
          <FolderKanban className="h-10 w-10 mx-auto text-muted-foreground mb-3" />
          <h3 className="font-serif text-lg font-semibold mb-1">Henüz proje yok</h3>
          <p className="text-sm text-muted-foreground mb-4">
            İlk projeni oluşturarak dava workspace'i kur.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <div
              key={p.id}
              className="group relative rounded-2xl bg-card border border-border shadow-card-elite overflow-hidden hover:shadow-elegant transition"
            >
              <div className="h-2" style={{ background: p.color || "hsl(var(--gold))" }} />
              <div className="p-5">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <Link
                    to={`/dashboard/projects/${p.id}`}
                    className="font-serif font-semibold text-lg hover:text-gold transition truncate"
                  >
                    {p.name}
                  </Link>
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-destructive opacity-0 group-hover:opacity-100 transition shrink-0"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Projeyi sil?</AlertDialogTitle>
                        <AlertDialogDescription>Tüm notlar da silinecek.</AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>İptal</AlertDialogCancel>
                        <AlertDialogAction onClick={() => remove(p.id)}>Sil</AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
                <p className="text-sm text-muted-foreground line-clamp-2 mb-3 min-h-[2.5rem]">
                  {p.description || "Açıklama yok"}
                </p>
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant="outline">{p.status}</Badge>
                  <span className="text-xs text-muted-foreground ml-auto">
                    {new Date(p.created_at).toLocaleDateString("tr-TR")}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </DashboardLayout>
  );
}

export const Route = createFileRoute("/_authenticated/dashboard/projects/")({
  component: Projects,
});

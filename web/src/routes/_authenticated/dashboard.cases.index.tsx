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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Plus, Search, Loader2, MoreHorizontal, Pencil, Trash2, Eye } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "@/lib/router-compat";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/components/AuthProvider";
import { toast } from "sonner";
import { z } from "zod";
import { cn } from "@/lib/utils";

interface Case {
  id: string;
  case_no: string | null;
  title: string;
  court: string | null;
  esas_no: string | null;
  case_type: string | null;
  opponent: string | null;
  status: string;
  opened_at: string | null;
  next_hearing: string | null;
  notes: string | null;
  client_id: string | null;
  owner_id: string;
  created_at: string;
}
interface ClientLite {
  id: string;
  full_name: string;
}

const schema = z.object({
  title: z.string().trim().min(1, "Başlık gerekli").max(200),
  case_no: z.string().trim().max(50).optional().or(z.literal("")),
  esas_no: z.string().trim().max(50).optional().or(z.literal("")),
  court: z.string().trim().max(120).optional().or(z.literal("")),
  case_type: z.string().trim().max(60).optional().or(z.literal("")),
  opponent: z.string().trim().max(120).optional().or(z.literal("")),
  status: z.enum(["active", "pending", "closed"]),
  opened_at: z.string().optional().or(z.literal("")),
  next_hearing: z.string().optional().or(z.literal("")),
  client_id: z.string().optional().or(z.literal("")),
  notes: z.string().trim().max(1000).optional().or(z.literal("")),
});

type CaseForm = {
  title: string;
  case_no: string;
  esas_no: string;
  court: string;
  case_type: string;
  opponent: string;
  status: "active" | "pending" | "closed";
  opened_at: string;
  next_hearing: string;
  client_id: string;
  notes: string;
};
const empty: CaseForm = {
  title: "",
  case_no: "",
  esas_no: "",
  court: "",
  case_type: "",
  opponent: "",
  status: "active",
  opened_at: "",
  next_hearing: "",
  client_id: "",
  notes: "",
};

const statusBadge: Record<string, string> = {
  active: "bg-success/10 text-success border-success/20",
  pending: "bg-warning/10 text-warning border-warning/20",
  closed: "bg-muted text-muted-foreground border-border",
};
const statusLabel: Record<string, string> = {
  active: "Aktif",
  pending: "Beklemede",
  closed: "Kapalı",
};

const Cases = () => {
  const { user } = useAuth();
  const [data, setData] = useState<Case[]>([]);
  const [clients, setClients] = useState<ClientLite[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "active" | "pending" | "closed">("all");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Case | null>(null);
  const [form, setForm] = useState<CaseForm>(empty);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    const [{ data: cs, error: e1 }, { data: cl }] = await Promise.all([
      supabase.from("cases").select("*").order("created_at", { ascending: false }),
      supabase.from("clients").select("id, full_name").order("full_name"),
    ]);
    if (e1) toast.error(e1.message);
    setData((cs ?? []) as Case[]);
    setClients((cl ?? []) as ClientLite[]);
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
  const openEdit = (c: Case) => {
    setEditing(c);
    setForm({
      title: c.title,
      case_no: c.case_no ?? "",
      esas_no: c.esas_no ?? "",
      court: c.court ?? "",
      case_type: c.case_type ?? "",
      opponent: c.opponent ?? "",
      status: (c.status as "active" | "pending" | "closed") ?? "active",
      opened_at: c.opened_at ?? "",
      next_hearing: c.next_hearing ? c.next_hearing.slice(0, 16) : "",
      client_id: c.client_id ?? "",
      notes: c.notes ?? "",
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
      case_no: parsed.data.case_no || null,
      esas_no: parsed.data.esas_no || null,
      court: parsed.data.court || null,
      case_type: parsed.data.case_type || null,
      opponent: parsed.data.opponent || null,
      status: parsed.data.status,
      opened_at: parsed.data.opened_at || null,
      next_hearing: parsed.data.next_hearing
        ? new Date(parsed.data.next_hearing).toISOString()
        : null,
      client_id: parsed.data.client_id || null,
      notes: parsed.data.notes || null,
    };
    if (editing) {
      const { error } = await supabase.from("cases").update(payload).eq("id", editing.id);
      if (error) toast.error(error.message);
      else {
        toast.success("Dava güncellendi");
        setOpen(false);
        load();
      }
    } else {
      const { error } = await supabase.from("cases").insert({ ...payload, owner_id: user.id });
      if (error) toast.error(error.message);
      else {
        toast.success("Dava eklendi");
        setOpen(false);
        load();
      }
    }
    setSaving(false);
  };

  const remove = async (id: string) => {
    const { error } = await supabase.from("cases").delete().eq("id", id);
    if (error) toast.error(error.message);
    else {
      toast.success("Silindi");
      load();
    }
  };

  const clientName = (id: string | null) => clients.find((c) => c.id === id)?.full_name ?? "—";

  const filtered = useMemo(
    () =>
      data.filter((c) => {
        if (filter !== "all" && c.status !== filter) return false;
        if (
          query &&
          !`${c.title} ${c.case_no ?? ""} ${c.opponent ?? ""} ${clientName(c.client_id)}`
            .toLowerCase()
            .includes(query.toLowerCase())
        )
          return false;
        return true;
      }),
    [data, filter, query, clients],
  );

  const stats = useMemo(
    () => ({
      open: data.filter((d) => d.status === "active").length,
      week: data.filter(
        (d) =>
          d.next_hearing &&
          new Date(d.next_hearing).getTime() - Date.now() < 7 * 86400000 &&
          new Date(d.next_hearing).getTime() > Date.now(),
      ).length,
      pending: data.filter((d) => d.status === "pending").length,
      closed: data.filter((d) => d.status === "closed").length,
    }),
    [data],
  );

  return (
    <DashboardLayout
      title="Davalar"
      subtitle="Tüm dava ve dosyalarınızın canlı durumu"
      actions={
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button variant="elite" size="sm" onClick={openCreate}>
              <Plus className="h-4 w-4" />
              Yeni Dava
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>{editing ? "Davayı Düzenle" : "Yeni Dava"}</DialogTitle>
            </DialogHeader>
            <div className="grid grid-cols-2 gap-4 py-2">
              <div className="col-span-2 space-y-1.5">
                <Label>Başlık *</Label>
                <Input
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="Örn: İşçilik Alacağı Davası"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Dosya No</Label>
                <Input
                  value={form.case_no}
                  onChange={(e) => setForm({ ...form, case_no: e.target.value })}
                  placeholder="2024/1234"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Esas No</Label>
                <Input
                  value={form.esas_no}
                  onChange={(e) => setForm({ ...form, esas_no: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Mahkeme</Label>
                <Input
                  value={form.court}
                  onChange={(e) => setForm({ ...form, court: e.target.value })}
                  placeholder="İstanbul 3. İş Mah."
                />
              </div>
              <div className="space-y-1.5">
                <Label>Dava Türü</Label>
                <Input
                  value={form.case_type}
                  onChange={(e) => setForm({ ...form, case_type: e.target.value })}
                  placeholder="İş Hukuku"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Müvekkil</Label>
                <Select
                  value={form.client_id}
                  onValueChange={(v) => setForm({ ...form, client_id: v })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Seçiniz" />
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
              <div className="space-y-1.5">
                <Label>Karşı Taraf</Label>
                <Input
                  value={form.opponent}
                  onChange={(e) => setForm({ ...form, opponent: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Durum</Label>
                <Select
                  value={form.status}
                  onValueChange={(v: "active" | "pending" | "closed") =>
                    setForm({ ...form, status: v })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="active">Aktif</SelectItem>
                    <SelectItem value="pending">Beklemede</SelectItem>
                    <SelectItem value="closed">Kapalı</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Açılış Tarihi</Label>
                <Input
                  type="date"
                  value={form.opened_at}
                  onChange={(e) => setForm({ ...form, opened_at: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Sonraki Duruşma</Label>
                <Input
                  type="datetime-local"
                  value={form.next_hearing}
                  onChange={(e) => setForm({ ...form, next_hearing: e.target.value })}
                />
              </div>
              <div className="col-span-2 space-y-1.5">
                <Label>Notlar</Label>
                <Textarea
                  rows={3}
                  value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
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
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[
          { l: "Aktif Davalar", v: stats.open },
          { l: "Bu Hafta Duruşma", v: stats.week },
          { l: "Beklemede", v: stats.pending },
          { l: "Kapalı", v: stats.closed },
        ].map((s) => (
          <div key={s.l} className="p-5 rounded-xl bg-card border border-border shadow-card-elite">
            <div className="text-xs text-muted-foreground">{s.l}</div>
            <div className="mt-2 font-serif text-3xl font-semibold">{s.v}</div>
          </div>
        ))}
      </div>

      <div className="rounded-2xl bg-card border border-border shadow-card-elite overflow-hidden">
        <div className="p-4 flex items-center gap-3 border-b border-border flex-wrap">
          <div className="relative flex-1 min-w-[200px] max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full h-10 pl-10 pr-4 rounded-lg bg-secondary/60 border border-transparent focus:border-gold/50 outline-none text-sm"
              placeholder="Dosya no, müvekkil veya karşı taraf..."
            />
          </div>
          <div className="flex items-center gap-1.5 text-xs">
            {[
              { k: "all" as const, l: "Tümü" },
              { k: "active" as const, l: "Aktif" },
              { k: "pending" as const, l: "Beklemede" },
              { k: "closed" as const, l: "Kapalı" },
            ].map((t) => (
              <button
                key={t.k}
                onClick={() => setFilter(t.k)}
                className={`px-3 py-1.5 rounded-md transition ${filter === t.k ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-secondary"}`}
              >
                {t.l}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="py-20 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="py-20 text-center">
            <div className="text-muted-foreground mb-4">Henüz dava yok.</div>
            <Button variant="elite" size="sm" onClick={openCreate}>
              <Plus className="h-4 w-4" />
              İlk davayı ekle
            </Button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground bg-secondary/40 uppercase tracking-wider">
                  <th className="font-medium px-6 py-3">Dosya No</th>
                  <th className="font-medium px-6 py-3">Başlık</th>
                  <th className="font-medium px-6 py-3">Müvekkil</th>
                  <th className="font-medium px-6 py-3">Karşı Taraf</th>
                  <th className="font-medium px-6 py-3">Tür</th>
                  <th className="font-medium px-6 py-3">Durum</th>
                  <th className="font-medium px-6 py-3">Duruşma</th>
                  <th className="font-medium px-6 py-3 w-12"></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => (
                  <tr
                    key={c.id}
                    className="border-t border-border hover:bg-secondary/30 transition"
                  >
                    <td className="px-6 py-4 font-mono text-xs">{c.case_no ?? "—"}</td>
                    <td className="px-6 py-4 font-medium">{c.title}</td>
                    <td className="px-6 py-4 text-muted-foreground">{clientName(c.client_id)}</td>
                    <td className="px-6 py-4 text-muted-foreground">{c.opponent ?? "—"}</td>
                    <td className="px-6 py-4 text-muted-foreground">{c.case_type ?? "—"}</td>
                    <td className="px-6 py-4">
                      <span
                        className={cn(
                          "inline-flex items-center px-2.5 py-1 rounded-full border text-xs font-medium",
                          statusBadge[c.status],
                        )}
                      >
                        {statusLabel[c.status]}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-xs">
                      {c.next_hearing
                        ? new Date(c.next_hearing).toLocaleString("tr-TR", {
                            dateStyle: "short",
                            timeStyle: "short",
                          })
                        : "—"}
                    </td>
                    <td className="px-6 py-4">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <button className="p-1.5 rounded-md hover:bg-secondary">
                            <MoreHorizontal className="h-4 w-4" />
                          </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem asChild>
                            <Link to={`/dashboard/cases/${c.id}`}>
                              <Eye className="h-3.5 w-3.5 mr-2" />
                              Detay
                            </Link>
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => openEdit(c)}>
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
                                <AlertDialogTitle>Davayı sil?</AlertDialogTitle>
                                <AlertDialogDescription>
                                  <strong>{c.title}</strong> kalıcı olarak silinecek.
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>İptal</AlertDialogCancel>
                                <AlertDialogAction onClick={() => remove(c.id)}>
                                  Sil
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/cases/")({
  component: Cases,
});

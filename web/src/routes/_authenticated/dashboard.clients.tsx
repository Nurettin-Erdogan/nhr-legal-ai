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
import { Plus, Search, Phone, Mail, MoreHorizontal, Pencil, Trash2, Loader2 } from "lucide-react";
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

interface Client {
  id: string;
  full_name: string;
  client_type: string;
  national_id: string | null;
  tax_id: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  notes: string | null;
  created_at: string;
  owner_id: string;
}

const clientSchema = z.object({
  full_name: z.string().trim().min(1, "Ad gerekli").max(120),
  client_type: z.enum(["individual", "corporate"]),
  email: z.string().trim().email("Geçersiz e-posta").max(255).optional().or(z.literal("")),
  phone: z.string().trim().max(40).optional().or(z.literal("")),
  national_id: z.string().trim().max(20).optional().or(z.literal("")),
  tax_id: z.string().trim().max(20).optional().or(z.literal("")),
  address: z.string().trim().max(500).optional().or(z.literal("")),
  notes: z.string().trim().max(1000).optional().or(z.literal("")),
});

const empty = {
  full_name: "",
  client_type: "individual",
  email: "",
  phone: "",
  national_id: "",
  tax_id: "",
  address: "",
  notes: "",
};

const Clients = () => {
  const { user } = useAuth();
  const [data, setData] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "individual" | "corporate">("all");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Client | null>(null);
  const [form, setForm] = useState<typeof empty>(empty);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    const { data, error } = await supabase
      .from("clients")
      .select("*")
      .order("created_at", { ascending: false });
    if (error) toast.error(error.message);
    setData((data ?? []) as Client[]);
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
  const openEdit = (c: Client) => {
    setEditing(c);
    setForm({
      full_name: c.full_name,
      client_type: c.client_type,
      email: c.email ?? "",
      phone: c.phone ?? "",
      national_id: c.national_id ?? "",
      tax_id: c.tax_id ?? "",
      address: c.address ?? "",
      notes: c.notes ?? "",
    });
    setOpen(true);
  };

  const save = async () => {
    const parsed = clientSchema.safeParse(form);
    if (!parsed.success) {
      toast.error(parsed.error.issues[0].message);
      return;
    }
    if (!user) {
      toast.error("Oturum bulunamadı");
      return;
    }
    setSaving(true);
    const payload = {
      full_name: parsed.data.full_name,
      client_type: parsed.data.client_type,
      email: parsed.data.email || null,
      phone: parsed.data.phone || null,
      national_id: parsed.data.national_id || null,
      tax_id: parsed.data.tax_id || null,
      address: parsed.data.address || null,
      notes: parsed.data.notes || null,
    };
    if (editing) {
      const { error } = await supabase.from("clients").update(payload).eq("id", editing.id);
      if (error) toast.error(error.message);
      else {
        toast.success("Müvekkil güncellendi");
        setOpen(false);
        load();
      }
    } else {
      const { error } = await supabase.from("clients").insert({ ...payload, owner_id: user.id });
      if (error) toast.error(error.message);
      else {
        toast.success("Müvekkil eklendi");
        setOpen(false);
        load();
      }
    }
    setSaving(false);
  };

  const remove = async (id: string) => {
    const { error } = await supabase.from("clients").delete().eq("id", id);
    if (error) toast.error(error.message);
    else {
      toast.success("Silindi");
      load();
    }
  };

  const filtered = useMemo(() => {
    return data.filter((c) => {
      if (filter !== "all" && c.client_type !== filter) return false;
      if (
        query &&
        !`${c.full_name} ${c.email ?? ""} ${c.phone ?? ""}`
          .toLowerCase()
          .includes(query.toLowerCase())
      )
        return false;
      return true;
    });
  }, [data, filter, query]);

  const stats = useMemo(
    () => ({
      total: data.length,
      ind: data.filter((d) => d.client_type === "individual").length,
      corp: data.filter((d) => d.client_type === "corporate").length,
      new7: data.filter((d) => Date.now() - new Date(d.created_at).getTime() < 7 * 86400000).length,
    }),
    [data],
  );

  return (
    <DashboardLayout
      title="Müvekkiller"
      subtitle="Tüm müvekkillerinizi tek panelden yönetin"
      actions={
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button variant="elite" size="sm" onClick={openCreate}>
              <Plus className="h-4 w-4" />
              Yeni Müvekkil
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>{editing ? "Müvekkili Düzenle" : "Yeni Müvekkil"}</DialogTitle>
            </DialogHeader>
            <div className="grid grid-cols-2 gap-4 py-2">
              <div className="col-span-2 space-y-1.5">
                <Label>Ad Soyad / Ünvan *</Label>
                <Input
                  value={form.full_name}
                  onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                  placeholder="Örn: Mehmet Yılmaz / ABC A.Ş."
                />
              </div>
              <div className="space-y-1.5">
                <Label>Tip</Label>
                <Select
                  value={form.client_type}
                  onValueChange={(v) => setForm({ ...form, client_type: v })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="individual">Gerçek Kişi</SelectItem>
                    <SelectItem value="corporate">Tüzel Kişi</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>{form.client_type === "corporate" ? "Vergi No" : "TC Kimlik No"}</Label>
                <Input
                  value={form.client_type === "corporate" ? form.tax_id : form.national_id}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      [form.client_type === "corporate" ? "tax_id" : "national_id"]: e.target.value,
                    })
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>Telefon</Label>
                <Input
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                  placeholder="+90 5xx xxx xx xx"
                />
              </div>
              <div className="space-y-1.5">
                <Label>E-posta</Label>
                <Input
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </div>
              <div className="col-span-2 space-y-1.5">
                <Label>Adres</Label>
                <Input
                  value={form.address}
                  onChange={(e) => setForm({ ...form, address: e.target.value })}
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
          { l: "Toplam Müvekkil", v: stats.total },
          { l: "Gerçek Kişi", v: stats.ind },
          { l: "Tüzel Kişi", v: stats.corp },
          { l: "Son 7 Gün", v: stats.new7 },
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
              placeholder="Müvekkil ara..."
            />
          </div>
          <div className="flex items-center gap-1.5 text-xs">
            {[
              { k: "all" as const, l: "Tümü" },
              { k: "individual" as const, l: "Gerçek" },
              { k: "corporate" as const, l: "Tüzel" },
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
            <div className="text-muted-foreground mb-4">Henüz müvekkil yok.</div>
            <Button variant="elite" size="sm" onClick={openCreate}>
              <Plus className="h-4 w-4" />
              İlk müvekkili ekle
            </Button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground bg-secondary/40 uppercase tracking-wider">
                  <th className="font-medium px-6 py-3">Müvekkil</th>
                  <th className="font-medium px-6 py-3">İletişim</th>
                  <th className="font-medium px-6 py-3">Tip</th>
                  <th className="font-medium px-6 py-3">Eklenme</th>
                  <th className="font-medium px-6 py-3 w-12"></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => (
                  <tr
                    key={c.id}
                    className="border-t border-border hover:bg-secondary/30 transition"
                  >
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div className="h-9 w-9 rounded-full bg-gradient-gold flex items-center justify-center font-serif font-semibold text-primary text-xs">
                          {c.full_name
                            .split(" ")
                            .map((n) => n[0])
                            .slice(0, 2)
                            .join("")
                            .toUpperCase()}
                        </div>
                        <div>
                          <div className="font-medium">{c.full_name}</div>
                          {c.notes && (
                            <div className="text-xs text-muted-foreground line-clamp-1">
                              {c.notes}
                            </div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      {c.phone && (
                        <div className="flex items-center gap-1.5 text-xs">
                          <Phone className="h-3 w-3 text-muted-foreground" />
                          {c.phone}
                        </div>
                      )}
                      {c.email && (
                        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                          <Mail className="h-3 w-3" />
                          {c.email}
                        </div>
                      )}
                    </td>
                    <td className="px-6 py-4 text-xs">
                      <span className="inline-flex items-center px-2.5 py-1 rounded-full border text-xs font-medium bg-secondary border-border">
                        {c.client_type === "corporate" ? "Tüzel" : "Gerçek"}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-muted-foreground text-xs">
                      {new Date(c.created_at).toLocaleDateString("tr-TR")}
                    </td>
                    <td className="px-6 py-4">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <button className="p-1.5 rounded-md hover:bg-secondary">
                            <MoreHorizontal className="h-4 w-4" />
                          </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
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
                                <AlertDialogTitle>Müvekkili sil?</AlertDialogTitle>
                                <AlertDialogDescription>
                                  <strong>{c.full_name}</strong> kalıcı olarak silinecek. Bağlı
                                  dosyalar etkilenebilir.
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

export const Route = createFileRoute("/_authenticated/dashboard/clients")({
  component: Clients,
});

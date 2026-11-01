import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { Loader2, Mail, Phone, Inbox } from "lucide-react";
import { cn } from "@/lib/utils";

type Basvuru = {
  id: string;
  ad_soyad: string;
  telefon: string | null;
  eposta: string | null;
  hukuk_alani: string | null;
  konu: string;
  sohbet_ozeti: string | null;
  durum: string;
  created_at: string;
};

const DURUMLAR = ["yeni", "görüşüldü", "dosya açıldı", "kapandı"];

const durumStyle = (d: string) =>
  d === "yeni"
    ? "bg-primary/10 text-primary"
    : d === "kapandı"
      ? "bg-muted text-muted-foreground"
      : "bg-secondary text-foreground";

function ApplicationsPage() {
  const [items, setItems] = useState<Basvuru[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [filter, setFilter] = useState<string>("tümü");
  const [openId, setOpenId] = useState<string | null>(null);

  const load = async () => {
    const { data, error } = await supabase
      .from("basvurular")
      .select("*")
      .order("created_at", { ascending: false });
    if (error) setLoadError(error.message);
    else {
      setLoadError("");
      setItems((data ?? []) as Basvuru[]);
    }
    setLoading(false);
  };

  useEffect(() => {
    load();
  }, []);

  const setDurum = async (id: string, durum: string) => {
    const { error } = await supabase.from("basvurular").update({ durum }).eq("id", id);
    if (error) return toast.error("Güncellenemedi");
    setItems((p) => p.map((b) => (b.id === id ? { ...b, durum } : b)));
    toast.success("Durum güncellendi");
  };

  const liste = filter === "tümü" ? items : items.filter((b) => b.durum === filter);

  return (
    <DashboardLayout title="Başvurular" subtitle="Siteden gelen vatandaş başvuruları">
      <div className="mx-auto max-w-4xl space-y-4">
        <div className="flex flex-wrap gap-2">
          {["tümü", ...DURUMLAR].map((d) => (
            <button
              key={d}
              onClick={() => setFilter(d)}
              className={cn(
                "rounded-full border px-3.5 py-1.5 text-sm font-medium capitalize transition-colors",
                filter === d
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-muted-foreground hover:text-foreground",
              )}
            >
              {d}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="flex justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : loadError ? (
          <p role="alert" className="rounded-lg border border-destructive/30 p-4 text-destructive">
            Başvurular yüklenemedi: {loadError}
          </p>
        ) : liste.length === 0 ? (
          <div className="flex flex-col items-center gap-3 rounded-2xl border border-border bg-card py-16 text-center">
            <Inbox className="h-8 w-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">Bu filtrede başvuru yok.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {liste.map((b) => (
              <div key={b.id} className="rounded-2xl border border-border bg-card p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{b.ad_soyad}</span>
                      <Badge className={cn("capitalize", durumStyle(b.durum))} variant="secondary">
                        {b.durum}
                      </Badge>
                      {b.hukuk_alani && (
                        <span className="text-xs text-muted-foreground">{b.hukuk_alani}</span>
                      )}
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-3 text-xs text-muted-foreground">
                      {b.telefon && (
                        <span className="inline-flex items-center gap-1">
                          <Phone className="h-3 w-3" /> {b.telefon}
                        </span>
                      )}
                      {b.eposta && (
                        <span className="inline-flex items-center gap-1">
                          <Mail className="h-3 w-3" /> {b.eposta}
                        </span>
                      )}
                      <span>{new Date(b.created_at).toLocaleString("tr-TR")}</span>
                    </div>
                  </div>
                  <Select value={b.durum} onValueChange={(v) => setDurum(b.id, v)}>
                    <SelectTrigger className="w-40">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {DURUMLAR.map((d) => (
                        <SelectItem key={d} value={d} className="capitalize">
                          {d}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">{b.konu}</p>

                {b.sohbet_ozeti && (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="mt-2 px-0 text-primary hover:bg-transparent"
                      onClick={() => setOpenId(openId === b.id ? null : b.id)}
                    >
                      {openId === b.id ? "Sohbeti gizle" : "AI sohbet geçmişini gör"}
                    </Button>
                    {openId === b.id && (
                      <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-muted p-3 text-xs leading-relaxed text-muted-foreground">
                        {b.sohbet_ozeti}
                      </pre>
                    )}
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </DashboardLayout>
  );
}

export const Route = createFileRoute("/_authenticated/dashboard/applications")({
  component: ApplicationsPage,
});

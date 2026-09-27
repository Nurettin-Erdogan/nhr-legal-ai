import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Filter, Download, Play, FileText, Phone } from "lucide-react";
import { cn } from "@/lib/utils";
import { useEffect, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/components/AuthProvider";

const filters = ["Tümü", "Gelen", "Giden", "Bugün"];

const statusColor: Record<string, string> = {
  answered: "bg-success/10 text-success border-success/20",
  missed: "bg-destructive/10 text-destructive border-destructive/20",
  voicemail: "bg-warning/10 text-warning border-warning/20",
};

type CallRow = {
  id: string;
  caller_name: string | null;
  phone: string;
  direction: string;
  status: string;
  duration_sec: number;
  started_at: string;
  ai_summary: string | null;
};

const formatDur = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

const Calls = () => {
  const { user } = useAuth();
  const [active, setActive] = useState("Tümü");
  const [calls, setCalls] = useState<CallRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) return;
    (async () => {
      setLoading(true);
      let q = supabase
        .from("calls")
        .select("*")
        .order("started_at", { ascending: false })
        .limit(100);
      if (active === "Gelen") q = q.eq("direction", "inbound");
      if (active === "Giden") q = q.eq("direction", "outbound");
      if (active === "Bugün") {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        q = q.gte("started_at", today.toISOString());
      }
      const { data } = await q;
      setCalls((data as CallRow[]) || []);
      setLoading(false);
    })();
  }, [user, active]);

  return (
    <DashboardLayout
      title="Aramalar"
      subtitle="Tüm gelen ve giden çağrıların detaylı kaydı"
      actions={
        <>
          <Button variant="outline" size="sm">
            <Filter className="h-4 w-4" />
            Filtre
          </Button>
          <Button variant="elite" size="sm">
            <Download className="h-4 w-4" />
            Dışa Aktar
          </Button>
        </>
      }
    >
      <div className="flex flex-wrap gap-2 mb-6">
        {filters.map((f) => (
          <button
            key={f}
            onClick={() => setActive(f)}
            className={cn(
              "px-4 py-2 rounded-full text-sm font-medium transition border",
              active === f
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-card border-border hover:border-gold/40 text-muted-foreground hover:text-foreground",
            )}
          >
            {f}
          </button>
        ))}
      </div>

      <div className="rounded-2xl bg-card border border-border shadow-card-elite overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-muted-foreground text-sm">Yükleniyor...</div>
        ) : calls.length === 0 ? (
          <div className="p-12 text-center">
            <Phone className="h-10 w-10 text-muted-foreground/40 mx-auto mb-3" />
            <p className="text-muted-foreground">Henüz arama kaydı yok</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground bg-secondary/40 uppercase tracking-wider">
                  <th className="font-medium px-6 py-4">Tarih</th>
                  <th className="font-medium px-6 py-4">Arayan</th>
                  <th className="font-medium px-6 py-4">Telefon</th>
                  <th className="font-medium px-6 py-4">Yön</th>
                  <th className="font-medium px-6 py-4">Durum</th>
                  <th className="font-medium px-6 py-4">Süre</th>
                  <th className="font-medium px-6 py-4 text-right">İşlem</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((c) => (
                  <tr
                    key={c.id}
                    className="border-t border-border hover:bg-secondary/30 transition"
                  >
                    <td className="px-6 py-4 font-mono text-xs">
                      {new Date(c.started_at).toLocaleString("tr-TR")}
                    </td>
                    <td className="px-6 py-4 font-medium">{c.caller_name || "—"}</td>
                    <td className="px-6 py-4 font-mono text-xs text-muted-foreground">{c.phone}</td>
                    <td className="px-6 py-4 text-muted-foreground capitalize">
                      {c.direction === "inbound" ? "Gelen" : "Giden"}
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={cn(
                          "inline-flex px-2.5 py-1 rounded-full border text-xs font-medium",
                          statusColor[c.status] || "bg-muted",
                        )}
                      >
                        {c.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 font-mono text-xs">{formatDur(c.duration_sec)}</td>
                    <td className="px-6 py-4">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          className="h-8 w-8 rounded-md hover:bg-secondary flex items-center justify-center"
                          title="Kayıt"
                        >
                          <Play className="h-3.5 w-3.5" />
                        </button>
                        <button
                          className="h-8 w-8 rounded-md hover:bg-secondary flex items-center justify-center"
                          title="Not"
                        >
                          <FileText className="h-3.5 w-3.5" />
                        </button>
                      </div>
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

export const Route = createFileRoute("/_authenticated/dashboard/calls")({
  component: Calls,
});

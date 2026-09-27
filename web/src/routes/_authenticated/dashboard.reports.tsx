import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { monthlyRevenue, leadFunnel, staff } from "@/data/mock";
import { Download, TrendingUp, TrendingDown } from "lucide-react";
import { cn } from "@/lib/utils";

const Reports = () => {
  const max = Math.max(...monthlyRevenue.map((m) => m.value));
  const funnelMax = leadFunnel[0].value;

  return (
    <DashboardLayout
      title="Raporlar"
      subtitle="Performans, dönüşüm ve gelir analitikleri"
      actions={
        <Button variant="elite" size="sm">
          <Download className="h-4 w-4" />
          PDF İndir
        </Button>
      }
    >
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[
          { l: "Lead Dönüşümü", v: "%24", c: "text-success", t: TrendingUp, ts: "+%4" },
          { l: "Arama Yanıt", v: "%97", c: "text-success", t: TrendingUp, ts: "+%2" },
          { l: "Randevu Oranı", v: "%32", c: "text-success", t: TrendingUp, ts: "+%6" },
          { l: "Kayıp Oran", v: "%8", c: "text-destructive", t: TrendingDown, ts: "-%2" },
        ].map((s) => (
          <div key={s.l} className="p-5 rounded-xl bg-card border border-border shadow-card-elite">
            <div className="text-xs text-muted-foreground">{s.l}</div>
            <div className={cn("mt-2 font-serif text-3xl font-semibold", s.c)}>{s.v}</div>
            <div className="mt-1 flex items-center gap-1 text-[11px]">
              <s.t className="h-3 w-3" /> {s.ts}
            </div>
          </div>
        ))}
      </div>

      <div className="grid lg:grid-cols-2 gap-6 mb-6">
        <div className="p-6 rounded-2xl bg-card border border-border shadow-card-elite">
          <h3 className="font-serif text-xl font-semibold mb-1">Aylık Tahsilat (₺ bin)</h3>
          <p className="text-sm text-muted-foreground mb-6">Son 6 ay</p>
          <div className="flex items-end gap-3 h-56">
            {monthlyRevenue.map((m) => (
              <div key={m.month} className="flex-1 flex flex-col items-center gap-2">
                <div className="w-full flex-1 flex items-end">
                  <div
                    className="w-full rounded-t-md bg-gradient-to-t from-primary to-primary-glow hover:opacity-80 transition"
                    style={{ height: `${(m.value / max) * 100}%` }}
                  />
                </div>
                <div className="text-[11px] text-muted-foreground">{m.month}</div>
                <div className="text-xs font-mono">{m.value}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="p-6 rounded-2xl bg-card border border-border shadow-card-elite">
          <h3 className="font-serif text-xl font-semibold mb-1">Lead Dönüşüm Hunisi</h3>
          <p className="text-sm text-muted-foreground mb-6">Son 30 gün</p>
          <div className="space-y-3">
            {leadFunnel.map((s, i) => (
              <div key={s.stage}>
                <div className="flex justify-between text-xs mb-1.5">
                  <span className="font-medium">{s.stage}</span>
                  <span className="font-mono text-muted-foreground">{s.value}</span>
                </div>
                <div className="h-3 rounded-full bg-secondary overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full",
                      i === 0
                        ? "bg-primary"
                        : i === 1
                          ? "bg-primary/80"
                          : i === 2
                            ? "bg-gold"
                            : "bg-gold-deep",
                    )}
                    style={{ width: `${(s.value / funnelMax) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="rounded-2xl bg-card border border-border shadow-card-elite overflow-hidden">
        <div className="p-6 border-b border-border">
          <h3 className="font-serif text-xl font-semibold">Personel Performansı</h3>
          <p className="text-sm text-muted-foreground">Açık dosya sayısı ve performans skoru</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground bg-secondary/40 uppercase tracking-wider">
                <th className="font-medium px-6 py-3">Üye</th>
                <th className="font-medium px-6 py-3">Rol</th>
                <th className="font-medium px-6 py-3 text-center">Açık Dosya</th>
                <th className="font-medium px-6 py-3">Performans</th>
              </tr>
            </thead>
            <tbody>
              {staff.map((s) => (
                <tr key={s.id} className="border-t border-border hover:bg-secondary/30">
                  <td className="px-6 py-4 font-medium">{s.name}</td>
                  <td className="px-6 py-4 text-muted-foreground">{s.role}</td>
                  <td className="px-6 py-4 text-center font-mono">{s.openCases}</td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className="flex-1 max-w-[200px] h-1.5 rounded-full bg-secondary overflow-hidden">
                        <div
                          className="h-full bg-gradient-gold"
                          style={{ width: `${s.performance}%` }}
                        />
                      </div>
                      <span className="text-xs font-mono w-10 text-right">%{s.performance}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/reports")({
  component: Reports,
});

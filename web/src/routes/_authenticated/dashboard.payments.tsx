import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { payments, monthlyRevenue } from "@/data/mock";
import { Plus, Download, Bell, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

const statusColor: Record<string, string> = {
  "Tahsil Edildi": "bg-success/10 text-success border-success/20",
  Bekliyor: "bg-blue-500/10 text-blue-600 border-blue-500/20",
  Gecikti: "bg-destructive/10 text-destructive border-destructive/20",
};

const PaymentsPage = () => {
  const max = Math.max(...monthlyRevenue.map((m) => m.value));

  return (
    <DashboardLayout
      title="Tahsilatlar"
      subtitle="Müvekkil ödemeleri ve tahsilat takibi"
      actions={
        <>
          <Button variant="outline" size="sm">
            <Download className="h-4 w-4" />
            Excel
          </Button>
          <Button variant="elite" size="sm">
            <Plus className="h-4 w-4" />
            Yeni Tahsilat
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        {[
          { l: "Bu Ay Tahsil Edilen", v: "₺ 245.000", c: "text-success", t: "+18% geçen aya göre" },
          { l: "Bekleyen Tahsilat", v: "₺ 98.500", c: "text-warning", t: "12 müvekkil" },
          {
            l: "Geciken Ödeme",
            v: "₺ 42.000",
            c: "text-destructive",
            t: "5 müvekkil — AI hatırlatma açık",
          },
        ].map((s) => (
          <div key={s.l} className="p-6 rounded-2xl bg-card border border-border shadow-card-elite">
            <div className="text-xs text-muted-foreground uppercase tracking-wider">{s.l}</div>
            <div className={cn("mt-3 font-serif text-4xl font-semibold", s.c)}>{s.v}</div>
            <div className="mt-2 text-xs text-foreground/70">{s.t}</div>
          </div>
        ))}
      </div>

      <div className="grid lg:grid-cols-3 gap-6 mb-6">
        <div className="lg:col-span-2 p-6 rounded-2xl bg-card border border-border shadow-card-elite">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h3 className="font-serif text-xl font-semibold">Aylık Tahsilat (₺ bin)</h3>
              <p className="text-sm text-muted-foreground">Son 6 ay</p>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-success font-medium">
              <TrendingUp className="h-3.5 w-3.5" /> +%18
            </div>
          </div>
          <div className="flex items-end gap-3 h-48">
            {monthlyRevenue.map((m) => (
              <div key={m.month} className="flex-1 flex flex-col items-center gap-2">
                <div className="w-full relative flex-1 flex items-end">
                  <div
                    className="w-full rounded-t-md bg-gradient-to-t from-gold-deep to-gold transition-all hover:opacity-80"
                    style={{ height: `${(m.value / max) * 100}%` }}
                  />
                </div>
                <div className="text-[11px] text-muted-foreground">{m.month}</div>
                <div className="text-xs font-mono font-medium">{m.value}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="p-6 rounded-2xl bg-gradient-hero text-primary-foreground shadow-elegant">
          <div className="text-xs text-gold uppercase tracking-wider font-semibold">
            AI Tahsilat Asistanı
          </div>
          <h3 className="mt-3 font-serif text-2xl font-semibold leading-snug">
            Geciken 5 ödeme için otomatik arama planlandı
          </h3>
          <p className="mt-3 text-sm text-primary-foreground/70">
            Yarın 10:00'da AI asistan müvekkilleri sırayla arayacak ve ödeme planı önerisinde
            bulunacak.
          </p>
          <Button variant="hero" className="mt-5">
            <Bell className="h-4 w-4" /> Şimdi Başlat
          </Button>
        </div>
      </div>

      <div className="rounded-2xl bg-card border border-border shadow-card-elite overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground bg-secondary/40 uppercase tracking-wider">
                <th className="font-medium px-6 py-3">Müvekkil</th>
                <th className="font-medium px-6 py-3 text-right">Tutar</th>
                <th className="font-medium px-6 py-3">Son Tarih</th>
                <th className="font-medium px-6 py-3">Durum</th>
                <th className="font-medium px-6 py-3">Hatırlatma</th>
                <th className="font-medium px-6 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {payments.map((p) => (
                <tr key={p.id} className="border-t border-border hover:bg-secondary/30 transition">
                  <td className="px-6 py-4 font-medium">{p.client}</td>
                  <td className="px-6 py-4 text-right font-mono">{p.amount}</td>
                  <td className="px-6 py-4 text-muted-foreground">{p.due}</td>
                  <td className="px-6 py-4">
                    <span
                      className={cn(
                        "inline-flex items-center px-2.5 py-1 rounded-full border text-xs font-medium",
                        statusColor[p.status],
                      )}
                    >
                      {p.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-xs text-muted-foreground">{p.reminded}</td>
                  <td className="px-6 py-4">
                    {p.status !== "Tahsil Edildi" && (
                      <Button variant="outline" size="sm">
                        <Bell className="h-3.5 w-3.5" /> AI Ara
                      </Button>
                    )}
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

export const Route = createFileRoute("/_authenticated/dashboard/payments")({
  component: PaymentsPage,
});

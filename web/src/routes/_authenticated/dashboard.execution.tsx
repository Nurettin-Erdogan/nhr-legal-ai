import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { executions } from "@/data/mock";
import { Bell, Plus, Download } from "lucide-react";
import { cn } from "@/lib/utils";

const statusColor: Record<string, string> = {
  "Haciz Aşaması": "bg-warning/10 text-warning border-warning/20",
  Tebligat: "bg-blue-500/10 text-blue-600 border-blue-500/20",
  "Ödeme Planı": "bg-gold/10 text-gold-deep border-gold/30",
  "Satış Aşaması": "bg-purple-500/10 text-purple-600 border-purple-500/20",
  Tamamlandı: "bg-success/10 text-success border-success/20",
};

const Execution = () => {
  return (
    <DashboardLayout
      title="İcra Takibi"
      subtitle="Aktif icra dosyaları ve tahsilat süreci"
      actions={
        <>
          <Button variant="outline" size="sm">
            <Download className="h-4 w-4" />
            Rapor
          </Button>
          <Button variant="elite" size="sm">
            <Plus className="h-4 w-4" />
            Yeni İcra
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[
          { l: "Toplam Alacak", v: "₺ 925K" },
          { l: "Tahsil Edilen", v: "₺ 165K", c: "text-success" },
          { l: "Bekleyen", v: "₺ 760K", c: "text-warning" },
          { l: "Aktif Dosya", v: "23" },
        ].map((s) => (
          <div key={s.l} className="p-5 rounded-xl bg-card border border-border shadow-card-elite">
            <div className="text-xs text-muted-foreground">{s.l}</div>
            <div className={cn("mt-2 font-serif text-3xl font-semibold", s.c)}>{s.v}</div>
          </div>
        ))}
      </div>

      <div className="rounded-2xl bg-card border border-border shadow-card-elite overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground bg-secondary/40 uppercase tracking-wider">
                <th className="font-medium px-6 py-3">Dosya No</th>
                <th className="font-medium px-6 py-3">Borçlu</th>
                <th className="font-medium px-6 py-3">Alacaklı</th>
                <th className="font-medium px-6 py-3 text-right">Tutar</th>
                <th className="font-medium px-6 py-3 text-right">Tahsil</th>
                <th className="font-medium px-6 py-3">Durum</th>
                <th className="font-medium px-6 py-3">Son Hatırlatma</th>
                <th className="font-medium px-6 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {executions.map((e) => (
                <tr key={e.id} className="border-t border-border hover:bg-secondary/30 transition">
                  <td className="px-6 py-4 font-mono text-xs">{e.no}</td>
                  <td className="px-6 py-4 font-medium">{e.debtor}</td>
                  <td className="px-6 py-4 text-muted-foreground">{e.creditor}</td>
                  <td className="px-6 py-4 text-right font-mono">{e.amount}</td>
                  <td className="px-6 py-4 text-right font-mono text-success">{e.collected}</td>
                  <td className="px-6 py-4">
                    <span
                      className={cn(
                        "inline-flex items-center px-2.5 py-1 rounded-full border text-xs font-medium",
                        statusColor[e.status],
                      )}
                    >
                      {e.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-xs text-muted-foreground">{e.lastReminder}</td>
                  <td className="px-6 py-4">
                    <Button variant="outline" size="sm">
                      <Bell className="h-3.5 w-3.5" />
                      AI Hatırlat
                    </Button>
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

export const Route = createFileRoute("/_authenticated/dashboard/execution")({
  component: Execution,
});

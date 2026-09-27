import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { upcomingAppointments } from "@/data/mock";
import { Plus, Calendar as CalIcon } from "lucide-react";

const Appointments = () => {
  const all = [
    ...upcomingAppointments,
    ...upcomingAppointments.map((a) => ({ ...a, id: a.id + 100 })),
  ];
  return (
    <DashboardLayout
      title="Randevular"
      subtitle="Tüm planlanmış görüşmeler ve danışmanlıklar"
      actions={
        <Button variant="elite" size="sm">
          <Plus className="h-4 w-4" />
          Randevu Ekle
        </Button>
      }
    >
      <div className="grid lg:grid-cols-3 gap-6">
        {["Bugün", "Yarın", "Bu Hafta"].map((label, i) => (
          <div
            key={label}
            className="rounded-2xl bg-card border border-border shadow-card-elite overflow-hidden"
          >
            <div className="px-6 py-4 border-b border-border flex items-center justify-between">
              <div>
                <div className="font-serif text-lg font-semibold">{label}</div>
                <div className="text-xs text-muted-foreground">
                  {all.filter((_, idx) => idx % 3 === i).length} randevu
                </div>
              </div>
              <div className="h-9 w-9 rounded-lg bg-gradient-gold flex items-center justify-center">
                <CalIcon className="h-4 w-4 text-primary" />
              </div>
            </div>
            <div className="divide-y divide-border max-h-[600px] overflow-y-auto">
              {all
                .filter((_, idx) => idx % 3 === i)
                .map((a) => (
                  <div key={a.id} className="p-5 hover:bg-secondary/30 transition">
                    <div className="flex items-baseline justify-between">
                      <div className="font-medium">{a.client}</div>
                      <div className="font-mono text-xs text-gold-deep">{a.time}</div>
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">{a.type}</div>
                    <div className="text-xs mt-2 text-foreground/70">{a.lawyer}</div>
                  </div>
                ))}
            </div>
          </div>
        ))}
      </div>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/appointments")({
  component: Appointments,
});

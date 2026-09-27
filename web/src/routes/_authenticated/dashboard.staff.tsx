import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { staff } from "@/data/mock";
import { Plus, Mail, Briefcase } from "lucide-react";

const Staff = () => {
  return (
    <DashboardLayout
      title="Personel"
      subtitle="Ekip üyeleri ve performans"
      actions={
        <Button variant="elite" size="sm">
          <Plus className="h-4 w-4" />
          Yeni Üye
        </Button>
      }
    >
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
        {staff.map((s) => (
          <div
            key={s.id}
            className="p-6 rounded-2xl bg-card border border-border shadow-card-elite hover:shadow-elegant transition"
          >
            <div className="flex items-start gap-4">
              <div className="h-14 w-14 rounded-full bg-gradient-gold flex items-center justify-center font-serif font-semibold text-primary text-lg shrink-0">
                {s.name
                  .split(" ")
                  .slice(-2)
                  .map((n: string) => n[0])
                  .join("")}
              </div>
              <div className="min-w-0 flex-1">
                <div className="font-medium truncate">{s.name}</div>
                <div className="text-xs text-gold-deep mt-0.5">{s.role}</div>
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground mt-2 truncate">
                  <Mail className="h-3 w-3" />
                  {s.email}
                </div>
              </div>
            </div>

            <div className="mt-5 grid grid-cols-2 gap-3 pt-4 border-t border-border">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Açık Dosya
                </div>
                <div className="font-serif text-2xl font-semibold mt-0.5 flex items-center gap-1.5">
                  <Briefcase className="h-4 w-4 text-gold" /> {s.openCases}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Performans
                </div>
                <div className="font-serif text-2xl font-semibold mt-0.5">%{s.performance}</div>
                <div className="mt-1 h-1.5 rounded-full bg-secondary overflow-hidden">
                  <div className="h-full bg-gradient-gold" style={{ width: `${s.performance}%` }} />
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/staff")({
  component: Staff,
});

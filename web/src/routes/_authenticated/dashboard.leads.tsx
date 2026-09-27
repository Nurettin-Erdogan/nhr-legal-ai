import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { leads } from "@/data/mock";
import { Plus, Phone, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";

const statusColor: Record<string, string> = {
  Sıcak: "bg-destructive/10 text-destructive border-destructive/20",
  İlgili: "bg-warning/10 text-warning border-warning/20",
  Soğuk: "bg-muted text-muted-foreground border-border",
};

const Leads = () => {
  return (
    <DashboardLayout
      title="Müvekkil Adayları"
      subtitle="AI tarafından kayıt altına alınan potansiyel müvekkiller"
      actions={
        <Button variant="elite" size="sm">
          <Plus className="h-4 w-4" />
          Yeni Aday
        </Button>
      }
    >
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
        {[...leads, ...leads.map((l) => ({ ...l, id: l.id + 100 }))].map((l) => (
          <div
            key={l.id}
            className="p-6 rounded-2xl bg-card border border-border shadow-card-elite hover:shadow-elegant hover:border-gold/40 transition-all"
          >
            <div className="flex items-start justify-between">
              <div className="h-11 w-11 rounded-full bg-gradient-gold flex items-center justify-center font-serif font-semibold text-primary">
                {l.name
                  .split(" ")
                  .map((n: string) => n[0])
                  .join("")}
              </div>
              <span
                className={cn(
                  "inline-flex px-2.5 py-1 rounded-full border text-xs font-medium",
                  statusColor[l.status],
                )}
              >
                {l.status}
              </span>
            </div>
            <div className="mt-4 font-medium">{l.name}</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {l.topic} · {l.date}
            </div>
            <div className="font-mono text-xs text-muted-foreground mt-2">{l.phone}</div>
            <div className="mt-5 pt-5 border-t border-border flex gap-2">
              <Button variant="outline" size="sm" className="flex-1">
                <Phone className="h-3.5 w-3.5" />
                Ara
              </Button>
              <Button variant="ghost" size="sm" className="flex-1">
                <MessageSquare className="h-3.5 w-3.5" />
                Mesaj
              </Button>
            </div>
          </div>
        ))}
      </div>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/leads")({
  component: Leads,
});

import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { modules } from "@/data/mock";
import {
  Phone,
  Calendar,
  FolderSearch,
  PhoneOutgoing,
  FileText,
  MessageSquare,
  BarChart3,
  Database,
  Settings as SettingsIcon,
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

const iconMap: Record<string, any> = {
  Phone,
  Calendar,
  FolderSearch,
  PhoneOutgoing,
  FileText,
  MessageSquare,
  BarChart3,
  Database,
};

const Modules = () => {
  const [items, setItems] = useState(modules);
  const toggle = (id: string) =>
    setItems(items.map((m) => (m.id === id ? { ...m, active: !m.active } : m)));

  return (
    <DashboardLayout title="Modüller" subtitle="İhtiyacınıza göre modülleri açın veya kapatın">
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
        {items.map((m) => {
          const Icon = iconMap[m.icon] || Phone;
          return (
            <div
              key={m.id}
              className={cn(
                "group p-6 rounded-2xl border shadow-card-elite transition-all",
                m.active
                  ? "bg-card border-gold/30 hover:shadow-elegant"
                  : "bg-card border-border opacity-75 hover:opacity-100",
              )}
            >
              <div className="flex items-start justify-between mb-4">
                <div
                  className={cn(
                    "h-11 w-11 rounded-xl flex items-center justify-center transition",
                    m.active
                      ? "bg-gradient-gold text-primary"
                      : "bg-secondary text-muted-foreground",
                  )}
                >
                  <Icon className="h-5 w-5" />
                </div>
                <button
                  onClick={() => toggle(m.id)}
                  className={cn(
                    "relative h-6 w-11 rounded-full transition-colors",
                    m.active ? "bg-gold" : "bg-muted",
                  )}
                  aria-label="toggle"
                >
                  <span
                    className={cn(
                      "absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform",
                      m.active ? "translate-x-5" : "translate-x-0.5",
                    )}
                  />
                </button>
              </div>
              <h3 className="font-serif text-lg font-semibold">{m.name}</h3>
              <p className="mt-2 text-sm text-muted-foreground leading-relaxed line-clamp-2">
                {m.desc}
              </p>
              <div className="mt-5 pt-5 border-t border-border flex items-center justify-between">
                <span
                  className={cn(
                    "text-[10px] uppercase font-semibold tracking-wider",
                    m.active ? "text-success" : "text-muted-foreground",
                  )}
                >
                  {m.active ? "● Aktif" : "○ Pasif"}
                </span>
                <Button variant="ghost" size="sm">
                  <SettingsIcon className="h-3.5 w-3.5" />
                  Ayarla
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/modules")({
  component: Modules,
});

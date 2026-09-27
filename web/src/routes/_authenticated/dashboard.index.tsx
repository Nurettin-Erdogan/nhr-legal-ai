import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Scale, FileSearch, Gavel, BookOpen, Camera, Inbox, FolderOpen } from "lucide-react";
import { Link } from "@/lib/router-compat";

const items = [
  {
    to: "/dashboard/applications",
    icon: Inbox,
    title: "Başvurular",
    desc: "Siteden gelen vatandaş başvuruları",
  },
  {
    to: "/dashboard/files",
    icon: FolderOpen,
    title: "Dosyalar",
    desc: "Dosya yükle ve UYAP senkronizasyonu",
  },
  {
    to: "/dashboard/ai",
    icon: Scale,
    title: "Hukuk Asistanı",
    desc: "Sorularınızı sorun, anında yanıt alın",
  },
  {
    to: "/dashboard/legislation",
    icon: BookOpen,
    title: "Mevzuat",
    desc: "Kanun, yönetmelik ve tebliğler",
  },
  {
    to: "/dashboard/research",
    icon: FileSearch,
    title: "Hukuki Araştırma",
    desc: "Kapsamlı analiz ve değerlendirme",
  },
  {
    to: "/dashboard/case-law",
    icon: Gavel,
    title: "İçtihat",
    desc: "Emsal kararlara hızlı erişim",
  },
  {
    to: "/dashboard/scanner",
    icon: Camera,
    title: "Belge Tarayıcı",
    desc: "Telefon kamerasıyla belge tarayın",
  },
];

const Dashboard = () => {
  return (
    <DashboardLayout title="Ana Sayfa" subtitle="Hızlı erişim">
      <div className="max-w-5xl mx-auto grid sm:grid-cols-2 gap-4">
        {items.map((a) => (
          <Link
            key={a.to}
            to={a.to}
            className="group relative p-6 rounded-xl bg-card border border-border hover:border-foreground/20 transition-colors flex items-center gap-4"
          >
            <div className="flex-1 min-w-0">
              <div className="text-base font-medium">{a.title}</div>
              <div className="text-sm text-muted-foreground mt-1">{a.desc}</div>
            </div>
            <div className="h-10 w-10 rounded-lg bg-muted flex items-center justify-center shrink-0">
              <a.icon className="h-5 w-5 text-foreground" />
            </div>
          </Link>
        ))}
      </div>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/")({
  component: Dashboard,
});

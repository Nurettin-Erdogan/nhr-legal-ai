import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";

const Modules = () => (
  <DashboardLayout title="Modüller" subtitle="Entegrasyon durumu">
    <section role="status" className="max-w-2xl rounded-xl border border-border bg-card p-6">
      <h2 className="text-xl font-semibold">Harici modüller bağlı değil</h2>
      <p className="mt-3 text-sm text-muted-foreground">
        Telefon, WhatsApp ve CRM bağlantıları için sağlayıcı hesabı ve sunucu entegrasyonu
        gerekiyor. Bu ekrandaki eski aç/kapat düğmeleri yalnız tarayıcıda görünümü değiştiriyordu;
        gerçek bir hizmeti etkinleştirmiyordu. Bağlantı kurulana kadar etkin durum gösterilmez.
      </p>
    </section>
  </DashboardLayout>
);

export const Route = createFileRoute("/_authenticated/dashboard/modules")({
  component: Modules,
});

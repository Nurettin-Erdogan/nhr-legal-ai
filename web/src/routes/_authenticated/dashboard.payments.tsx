import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";

const PaymentsPage = () => (
  <DashboardLayout title="Tahsilatlar" subtitle="Ödeme entegrasyonu durumu">
    <section role="status" className="max-w-2xl rounded-xl border border-border bg-card p-6">
      <h2 className="text-xl font-semibold">Ödeme hizmeti bağlı değil</h2>
      <p className="mt-3 text-sm text-muted-foreground">
        Bu kurulumda tahsilat kayıtları, ödeme sağlayıcısı ve otomatik ödeme hatırlatması bağlı
        değil. Gerçek finansal kayıt bulunmadan tutar, gelir grafiği veya arama sonucu gösterilmez.
      </p>
    </section>
  </DashboardLayout>
);

export const Route = createFileRoute("/_authenticated/dashboard/payments")({
  component: PaymentsPage,
});

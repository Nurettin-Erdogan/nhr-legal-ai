import { DashboardLayout } from "@/components/DashboardLayout";
import { Link } from "@/lib/router-compat";

export function UnavailableOfficeFeature({
  title,
  reason,
  alternative,
}: {
  title: string;
  reason: string;
  alternative?: { to: string; label: string };
}) {
  return (
    <DashboardLayout title={title} subtitle="Entegrasyon durumu">
      <section role="status" className="max-w-2xl rounded-xl border border-border bg-card p-6">
        <h2 className="text-xl font-semibold">Bu özellik henüz bağlı değil</h2>
        <p className="mt-3 text-sm text-muted-foreground">{reason}</p>
        {alternative && (
          <Link to={alternative.to} className="mt-4 inline-block text-sm text-primary underline">
            {alternative.label}
          </Link>
        )}
      </section>
    </DashboardLayout>
  );
}

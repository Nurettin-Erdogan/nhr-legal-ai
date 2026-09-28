import { createFileRoute } from "@tanstack/react-router";
import { UnavailableOfficeFeature } from "@/components/UnavailableOfficeFeature";

export const Route = createFileRoute("/_authenticated/dashboard/staff")({
  component: () => (
    <UnavailableOfficeFeature
      title="Personel"
      reason="Çok kullanıcılı ekip üyeliği ve rol yönetimi bu çalışma alanına henüz bağlı değil. Yeni üye ekleme ya da performans sayısı gösterilmez."
    />
  ),
});

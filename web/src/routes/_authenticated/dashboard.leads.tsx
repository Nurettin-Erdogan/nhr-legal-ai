import { createFileRoute } from "@tanstack/react-router";
import { UnavailableOfficeFeature } from "@/components/UnavailableOfficeFeature";

export const Route = createFileRoute("/_authenticated/dashboard/leads")({
  component: () => (
    <UnavailableOfficeFeature
      title="Müvekkil Adayları"
      reason="Aday takibi ve otomatik arama entegrasyonu bağlı değil. Yetkiliyseniz siteden gelen gerçek başvuruları Başvurular ekranında görebilirsiniz."
      alternative={{ to: "/dashboard/applications", label: "Başvurulara git" }}
    />
  ),
});

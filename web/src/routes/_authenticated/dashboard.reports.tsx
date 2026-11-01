import { createFileRoute } from "@tanstack/react-router";
import { UnavailableOfficeFeature } from "@/components/UnavailableOfficeFeature";

export const Route = createFileRoute("/_authenticated/dashboard/reports")({
  component: () => (
    <UnavailableOfficeFeature
      title="Raporlar"
      reason="Çağrı dönüşümü, personel performansı ve gelir raporları için doğrulanmış veri bağlantısı henüz yok. Ölçülmeyen oranlar ve gönderilmemiş raporlar gösterilmez."
    />
  ),
});

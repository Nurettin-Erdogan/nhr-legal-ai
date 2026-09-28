import { createFileRoute } from "@tanstack/react-router";
import { UnavailableOfficeFeature } from "@/components/UnavailableOfficeFeature";

export const Route = createFileRoute("/_authenticated/dashboard/execution")({
  component: () => (
    <UnavailableOfficeFeature
      title="İcra Takibi"
      reason="İcra dosyası ve tahsilat kayıtları için kullanıcıya özel veri modeli ve işlem akışı henüz bağlı değil. Gerçek kayıt olmadan alacak tutarı veya aktif dosya sayısı gösterilmez."
      alternative={{ to: "/dashboard/cases", label: "Kayıtlı davalara git" }}
    />
  ),
});

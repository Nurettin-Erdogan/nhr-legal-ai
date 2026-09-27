import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { AIRunner } from "@/components/AIRunner";

function AutoSummary() {
  return (
    <DashboardLayout
      title="Toplu Özet & Karşılaştırma"
      subtitle="Birden fazla belgeyi tek seferde özetle, karşılaştır ve risk değerlendirmesi al."
    >
      <AIRunner
        module="auto_summary"
        placeholder={`Belgelerinizi aşağıdaki formatta yapıştırın:\n\n=== BELGE 1: Kira Sözleşmesi ===\n[belge metni]\n\n=== BELGE 2: Hizmet Sözleşmesi ===\n[belge metni]\n\n=== BELGE 3: Gizlilik Sözleşmesi ===\n[belge metni]`}
        examples={[
          "3 farklı kira sözleşmesini karşılaştır, en riskli olanı belirle",
          "İki iş sözleşmesini karşılaştır: maaş, süre, rekabet yasağı, fesih şartları",
          "Verilen 4 dilekçeyi özetle ve ortak hukuki argümanları çıkar",
        ]}
      />
    </DashboardLayout>
  );
}

export const Route = createFileRoute("/_authenticated/dashboard/auto-summary")({
  component: AutoSummary,
});

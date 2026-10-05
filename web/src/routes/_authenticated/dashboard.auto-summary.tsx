import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { AIRunner } from "@/components/AIRunner";

function AutoSummary() {
  return (
    <DashboardLayout
      title="Toplu Özet"
      subtitle="Birden fazla belgeyi tek seferde özetleyin (en çok 4). Kayıtlı dava belgeleri için Dava > Dosya Özeti ve Belge Kıyasla sekmelerini kullanın."
    >
      <AIRunner
        module="auto_summary"
        placeholder={`Belgelerinizi aşağıdaki formatta yapıştırın:\n\n=== BELGE 1: Kira Sözleşmesi ===\n[belge metni]\n\n=== BELGE 2: Hizmet Sözleşmesi ===\n[belge metni]\n\n=== BELGE 3: Gizlilik Sözleşmesi ===\n[belge metni]`}
        examples={[
          "3 farklı kira sözleşmesinin bedel ve sürelerini özetle",
          "İki iş sözleşmesindeki maaş, süre ve fesih bilgilerini özetle",
          "Verilen 4 dilekçeyi ayrı ayrı özetle",
        ]}
      />
    </DashboardLayout>
  );
}

export const Route = createFileRoute("/_authenticated/dashboard/auto-summary")({
  component: AutoSummary,
});

import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { AIRunner } from "@/components/AIRunner";

const examples = [
  "Aşağıdaki kira sözleşmesinin tarafları, bedeli ve süresi nedir?\n\n[sözleşme metnini buraya yapıştırın]",
  "Şu iş sözleşmesindeki tarih, tutar ve süre bilgilerini özetle:\n\n[metin]",
  "Bu dilekçedeki talepleri ve dayanılan olguları özetle:\n\n[metin]",
];

const DocumentAnalysis = () => (
  <DashboardLayout
    title="Belge Analizi"
    subtitle="Yapıştırdığınız belgenin özeti, belgede geçen tarih/tutar/numaralar ve ilgili resmî kaynaklar. Hukuki değerlendirme yapılmaz."
  >
    <AIRunner
      module="document_analysis"
      placeholder="Belge metnini buraya yapıştırın. Özet belgeyle doğrulanır; belgede olmayan bilgi gösterilmez. Uzun belgelerin yalnız ilk bölümü özetlenir ve bu belirtilir."
      examples={examples}
    />
  </DashboardLayout>
);

export const Route = createFileRoute("/_authenticated/dashboard/document-analysis")({
  component: DocumentAnalysis,
});

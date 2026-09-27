import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { AIRunner } from "@/components/AIRunner";

const examples = [
  "Aşağıdaki kira sözleşmesinin tahliye taahhütnamesi açısından geçerliliğini analiz et:\n\n[sözleşme metnini buraya yapıştırın]",
  "Şu iş sözleşmesinde işçi aleyhine olan hükümleri ve geçersizlik risklerini değerlendir:\n\n[metin]",
  "Bu hisse devir sözleşmesindeki garanti hükümleri yeterli mi? Riskleri belirt:\n\n[metin]",
];

const DocumentAnalysis = () => (
  <DashboardLayout title="Belge Analizi" subtitle="Sözleşme, dilekçe ve kararları AI ile analiz et">
    <AIRunner
      module="document_analysis"
      placeholder="Analiz edilecek belge metnini buraya yapıştırın. AI; tarafları, anahtar hükümleri, riskleri ve tavsiyeleri çıkaracak..."
      examples={examples}
    />
  </DashboardLayout>
);

export const Route = createFileRoute("/_authenticated/dashboard/document-analysis")({
  component: DocumentAnalysis,
});

import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { AIRunner } from "@/components/AIRunner";
import { CaseLawDatabasePanel } from "@/components/CaseLawDatabasePanel";
import { DecisionSearch } from "@/components/DecisionSearch";

const examples = [
  "Yargıtay'ın haksız fesih davalarında işverenin ispat yüküne ilişkin son içtihat eğilimi nedir?",
  "AYM'nin ifade özgürlüğü ile kişilik hakları çatışması konusundaki yaklaşımı",
  "Danıştay'ın iptal davalarında menfaat kavramına ilişkin emsal kararları",
  "Yargıtay 11. HD'nin marka tecavüzünde tazminat hesaplama yöntemi",
];

const searchExamples = ["kıdem tazminatı", "ihtiyati tedbir", "4857 sayılı Kanun 25", "haksız fesih ispat yükü"];
const narrativeExamples = [
  "İşçi haklı nedenle iş akdini feshetti, son 3 maaşı ödenmedi; kıdem ve ihbar tazminatı talep edebilir mi?",
  "Kiracı sözleşme süresi dolmadan anahtarı teslim etti, ev sahibi kalan aylar için kira istiyor.",
];

const CaseLaw = () => (
  <DashboardLayout
    title="İçtihat Araştırması"
    subtitle="Yargıtay, Danıştay ve AYM kararları üzerinden AI analizi"
  >
    <CaseLawDatabasePanel />
    <DecisionSearch examples={searchExamples} narrativeExamples={narrativeExamples} />
    <AIRunner
      module="case_law"
      placeholder="Aradığınız içtihat konusunu yazın... Örn: Yargıtay 9. HD'nin işçi alacaklarında zamanaşımı yaklaşımı"
      examples={examples}
    />
  </DashboardLayout>
);

export const Route = createFileRoute("/_authenticated/dashboard/case-law")({
  component: CaseLaw,
});

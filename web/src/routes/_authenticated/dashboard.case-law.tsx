import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { AIRunner } from "@/components/AIRunner";
import { CaseLawDatabasePanel } from "@/components/CaseLawDatabasePanel";

const examples = [
  "Yargıtay'ın haksız fesih davalarında işverenin ispat yüküne ilişkin son içtihat eğilimi nedir?",
  "AYM'nin ifade özgürlüğü ile kişilik hakları çatışması konusundaki yaklaşımı",
  "Danıştay'ın iptal davalarında menfaat kavramına ilişkin emsal kararları",
  "Yargıtay 11. HD'nin marka tecavüzünde tazminat hesaplama yöntemi",
];

const CaseLaw = () => (
  <DashboardLayout
    title="İçtihat Araştırması"
    subtitle="Yargıtay, Danıştay ve AYM kararları üzerinden AI analizi"
  >
    <CaseLawDatabasePanel />
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

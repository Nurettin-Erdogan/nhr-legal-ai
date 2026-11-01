import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { AIRunner } from "@/components/AIRunner";
import { CaseLawDatabasePanel } from "@/components/CaseLawDatabasePanel";
import { DecisionSearch } from "@/components/DecisionSearch";
import { useAuth } from "@/components/AuthContext";
import { isAdmin } from "@/lib/admin-panel";

const examples = [
  "Yargıtay'ın haksız fesih davalarında işverenin ispat yüküne ilişkin son içtihat eğilimi nedir?",
  "AYM'nin ifade özgürlüğü ile kişilik hakları çatışması konusundaki yaklaşımı",
  "Danıştay'ın iptal davalarında menfaat kavramına ilişkin emsal kararları",
  "Yargıtay 11. HD'nin marka tecavüzünde tazminat hesaplama yöntemi",
];

const searchExamples = [
  "kıdem tazminatı",
  "ihtiyati tedbir",
  "4857 sayılı Kanun 25",
  "haksız fesih ispat yükü",
];
const narrativeExamples = [
  "İşçi haklı nedenle iş akdini feshetti, son 3 maaşı ödenmedi; kıdem ve ihbar tazminatı talep edebilir mi?",
  "Kiracı sözleşme süresi dolmadan anahtarı teslim etti, ev sahibi kalan aylar için kira istiyor.",
];

const CaseLawPage = () => (
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

/** İçtihat araştırması şimdilik yalnız yöneticiye açık: menüde de görünmez, adrese elle gidenler bilgilendirilir. */
const CaseLaw = () => {
  const { roles } = useAuth();
  if (!isAdmin(roles)) {
    return (
      <DashboardLayout title="İçtihat" subtitle="">
        <section role="status" className="max-w-xl rounded-xl border bg-card p-6">
          <h2 className="font-semibold">Bu sayfa şu an yalnız yöneticilere açıktır</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Karar ve mevzuat araştırması için Hukuk Asistanı ve Mevzuat sayfalarını
            kullanabilirsiniz.
          </p>
        </section>
      </DashboardLayout>
    );
  }
  return <CaseLawPage />;
};

export const Route = createFileRoute("/_authenticated/dashboard/case-law")({
  component: CaseLaw,
});

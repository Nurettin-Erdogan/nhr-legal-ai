import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { AIRunner } from "@/components/AIRunner";
import { CaseLawDatabasePanel } from "@/components/CaseLawDatabasePanel";
import { DecisionSearch } from "@/components/DecisionSearch";

const examples = [
  "Müvekkil 5 yıldır aynı işyerinde çalışıyor, son 3 ay maaşı geç ve eksik ödendi. İş akdini haklı nedenle feshetmek istiyor. Kıdem tazminatı alabilir mi, emsal kararlar nedir?",
  "Kira sözleşmesinde 1 yıllık süre var. Kiracı 8. ayda anahtar teslim ederek çıktı. Ev sahibi 4 aylık kira bedelini talep edebilir mi?",
  "Boşanma davasında, eşin sosyal medya yazışmaları delil olarak sunulabilir mi? Yargıtay yaklaşımı nedir?",
  "Trafik kazasında %20 kusurlu olan müvekkilin manevi tazminat talebi mahkemece kabul edilir mi?",
  "Tüketici, online aldığı ürünü 14 gün içinde iade etti ama satıcı kargo bedelini iade etmiyor. Hukuki durum?",
];

const searchExamples = ["kıdem tazminatı", "kira bedelinin tespiti", "boşanmada delil", "tüketici iade hakkı"];

const SemanticCaseSearch = () => (
  <DashboardLayout
    title="Semantik İçtihat Arama"
    subtitle="Anahtar kelime değil: olayı anlatın, benzer karar ve maddeler listelensin (deneysel; kaynaklar doğrulama rozetiyle gösterilir)."
  >
    <CaseLawDatabasePanel />
    <DecisionSearch initialMode="narrative" examples={searchExamples} narrativeExamples={examples.slice(0, 3)} />
    <AIRunner
      module="semantic_case_search"
      placeholder="Olayı doğal dilde tarif edin: müvekkilin durumu, karşı tarafın iddiası, anahtar olgular..."
      examples={examples}
    />
  </DashboardLayout>
);

export const Route = createFileRoute("/_authenticated/dashboard/semantic-search")({
  component: SemanticCaseSearch,
});

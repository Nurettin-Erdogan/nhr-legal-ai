import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { AIRunner } from "@/components/AIRunner";

function RiskAnalysis() {
  return (
    <DashboardLayout
      title="Risk Analizi"
      subtitle="Olayı anlatın; mevzuat, yargı kararları ve süre/ispat açısından kaynaklı inceleme alın. Dava sonucu tahmini yapılmaz."
    >
      <AIRunner
        module="risk_analysis"
        placeholder="Olayı olgularla anlatın: taraflar, tarihler, tutarlar, elinizdeki deliller. Örn: Müvekkil kira sözleşmesinde 6 ay erken tahliye etti; sözleşmede 3 aylık cezai şart var, karşı taraf 6 ay kira + cezai şart istiyor."
        examples={[
          "İşçi 5 yıl çalıştığı şirketten haksız fesih iddiasıyla işe iade davası açtı. Şirketin elinde fesih tutanağı var, tanık zayıf.",
          "Ticari satış sözleşmesinde teslim gecikti; alıcı cezai şart ve zarar talep ediyor, satıcı mücbir sebep savunması yapıyor.",
          "Trafik kazasında kusur oranı tartışmalı; maddi ve manevi tazminat davası düşünülüyor.",
          "Boşanma davasında tarafların kusur durumu tartışmalı; tazminat ve nafaka talepleri olacak.",
        ]}
      />
    </DashboardLayout>
  );
}

export const Route = createFileRoute("/_authenticated/dashboard/risk-analysis")({
  component: RiskAnalysis,
});

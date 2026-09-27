import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { AIRunner } from "@/components/AIRunner";

function RiskAnalysis() {
  return (
    <DashboardLayout
      title="Risk Analizi & Dava Sonuç Tahmini"
      subtitle="Sözleşme, dilekçe veya dava özetinizi girin; AI risk skorlaması ve sonuç olasılığı tahmini yapsın."
    >
      <AIRunner
        module="risk_analysis"
        placeholder="Örn: Müvekkilim, karşı taraf ile imzaladığı kira sözleşmesinde 6 ay erken tahliye etti. Sözleşmede 3 aylık cezai şart var. Karşı taraf 6 ay kira + cezai şart talep ediyor. Risk ve sonuç tahmini yapar mısın?"
        examples={[
          "İşçi, 5 yıl çalıştığı şirketten haksız fesih iddiasıyla işe iade davası açtı. Şirketin elinde tutanak var ama tanık zayıf. Risk değerlendirmesi yap.",
          "Ticari satış sözleşmesinde teslim gecikti, alıcı %30 cezai şart + zarar talep ediyor. Mücbir sebep savunması var. Dava sonuç tahmini.",
          "Trafik kazasında kusur oranı tartışmalı (%50-%50 vs %70-%30). Maddi-manevi tazminat davasının lehte sonuçlanma olasılığı nedir?",
          "Boşanma davasında müvekkil kusurlu görünüyor ama karşı tarafın aldatma delili var. Tazminat ve nafaka açısından risk analizi.",
        ]}
      />
    </DashboardLayout>
  );
}

export const Route = createFileRoute("/_authenticated/dashboard/risk-analysis")({
  component: RiskAnalysis,
});

import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { AIRunner } from "@/components/AIRunner";

function AgentResearch() {
  return (
    <DashboardLayout
      title="Agent Derin Araştırma"
      subtitle="Çok adımlı, kapsamlı hukuki araştırma raporu"
    >
      <AIRunner
        module="agent_research"
        placeholder="Derinlemesine araştırılmasını istediğin hukuki soruyu yaz. Agent soruyu parçalara ayıracak; mevzuat, içtihat, doktrin ve karşılaştırmalı hukuk perspektifinden çok katmanlı bir rapor üretecek..."
        examples={[
          "Yapay zeka ile üretilen eserlerde telif hakkı sahipliği Türk hukukunda kime aittir?",
          "Kripto varlıkların miras yoluyla intikalinde uygulanacak hukuk ve pratik sorunlar nelerdir?",
          "İşçinin uzaktan çalışmada iş kazası geçirmesi halinde işverenin sorumluluğunun kapsamı",
          "Ticari sözleşmelerde mücbir sebep olarak salgın hastalık: Yargıtay yaklaşımı ve sözleşme uyarlama",
        ]}
      />
    </DashboardLayout>
  );
}

export const Route = createFileRoute("/_authenticated/dashboard/agent-research")({
  component: AgentResearch,
});

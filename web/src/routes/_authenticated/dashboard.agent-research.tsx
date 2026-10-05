import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { DeepResearch } from "@/components/DeepResearch";

function AgentResearch() {
  return (
    <DashboardLayout
      title="Derin Araştırma"
      subtitle="Çok adımlı araştırma: mevzuat, yargı kararları ve süre/ispat/usul ayrı ayrı, kaynaklı ve doğrulanmış rapor"
    >
      <DeepResearch
        examples={[
          "İşçinin iş kazası geçirmesi halinde işverenin sorumluluğunun kapsamı nedir?",
          "Kıdem tazminatına hak kazanma şartları nelerdir ve zamanaşımı ne zaman başlar?",
          "Kira sözleşmesinde kiracının erken tahliyesi halinde ev sahibinin talep hakları nelerdir?",
          "İhtiyati tedbir kararının şartları ve tedbir kararına itiraz usulü",
        ]}
      />
    </DashboardLayout>
  );
}

export const Route = createFileRoute("/_authenticated/dashboard/agent-research")({
  component: AgentResearch,
});

import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { AssistantWorkspace } from "@/components/AssistantWorkspace";

const AIAssistant = () => (
  <DashboardLayout
    title="Hukuk Asistanı"
    subtitle="Araştırma, belge analizi ve özetler tek çalışma alanında"
  >
    <AssistantWorkspace />
  </DashboardLayout>
);

export const Route = createFileRoute("/_authenticated/dashboard/ai")({
  component: AIAssistant,
});

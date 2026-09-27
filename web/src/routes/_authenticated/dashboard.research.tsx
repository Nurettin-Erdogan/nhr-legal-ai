import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { LegalChat } from "@/components/LegalChat";

const ORNEKLER = [
  "Kira sözleşmesinde TÜFE üzerinde artış istenirse ne yapılır?",
  "İşçinin haksız feshinde kıdem hesabı nasıl yapılır?",
  "Boşanmada ortak velayet hangi şartlarda verilir?",
  "İcra takibinde itirazın iptali davası süresi nedir?",
];

const LegalResearch = () => (
  <DashboardLayout
    title="Anlık Hukuki Destek"
    subtitle="Mevzuat ve içtihat için kaynaklı AI hukuk asistanı"
  >
    <LegalChat
      title="Anlık Hukuki Destek"
      examples={ORNEKLER}
      intro="Mevzuat ve içtihat sorularınızı yazın; cevap yalnızca getirilen kaynaklara dayanır."
    />
  </DashboardLayout>
);

export const Route = createFileRoute("/_authenticated/dashboard/research")({
  component: LegalResearch,
});

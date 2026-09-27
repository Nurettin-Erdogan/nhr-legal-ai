import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { LegalChat } from "@/components/LegalChat";

const ORNEKLER = [
  "Kira sözleşmesinde TÜFE üzerinde artış istenirse ne yapılır?",
  "İşçinin haksız feshinde kıdem tazminatı nasıl hesaplanır?",
  "Boşanmada ortak velayet hangi şartlarda verilir?",
  "İcra takibinde itirazın iptali davası süresi nedir?",
];

const AIAssistant = () => (
  <DashboardLayout title="Akıllı Hukuk Asistanı" subtitle="Türk hukuku üzerine sohbet edin">
    <LegalChat
      title="Akıllı Hukuk Asistanı"
      examples={ORNEKLER}
      intro="Türk mevzuatı ve içtihatlar üzerine sorularınızı sorun. Cevaplar korpustaki kaynaklara atıfla verilir; doğrulanmamış kaynaklar ayrıca işaretlenir."
    />
  </DashboardLayout>
);

export const Route = createFileRoute("/_authenticated/dashboard/ai")({
  component: AIAssistant,
});

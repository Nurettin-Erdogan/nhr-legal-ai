import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { LegislationBrowser } from "@/components/LegislationBrowser";

const Legislation = () => (
  <DashboardLayout title="Mevzuat" subtitle="Kanun, KHK, yönetmelik ve tebliğleri ara, maddeleri oku; yalnız resmî kaynaklarla doğrulanmış güncel metinler">
    <LegislationBrowser />
  </DashboardLayout>
);

export const Route = createFileRoute("/_authenticated/dashboard/legislation")({
  component: Legislation,
});

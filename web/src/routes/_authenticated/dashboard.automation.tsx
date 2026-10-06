import { createFileRoute } from "@tanstack/react-router";
import { Navigate } from "@/lib/router-compat";

// Belge İşleme sayfasının başındaki "Tam Otomatik Dilekçe Akışı" ile aynı akıştı; eski adres oraya yönlendirir.
export const Route = createFileRoute("/_authenticated/dashboard/automation")({
  component: () => <Navigate to="/dashboard/document-processing" replace />,
});

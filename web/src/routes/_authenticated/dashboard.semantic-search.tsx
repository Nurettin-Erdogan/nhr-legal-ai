import { createFileRoute } from "@tanstack/react-router";
import { Navigate } from "@/lib/router-compat";

// İçtihat sayfasındaki "Olayı anlat" kipiyle aynı aramaydı; eski adres İçtihat sayfasına yönlendirir.
export const Route = createFileRoute("/_authenticated/dashboard/semantic-search")({
  component: () => <Navigate to="/dashboard/case-law" replace />,
});

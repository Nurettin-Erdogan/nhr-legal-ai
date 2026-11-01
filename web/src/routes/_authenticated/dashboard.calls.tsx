import { createFileRoute } from "@tanstack/react-router";
import { Navigate } from "@/lib/router-compat";

// Telefon hizmeti bağlı değil: çalışmayan Filtre/Dışa Aktar düğmeleri olan eski sayfa yerine durumu açıkça söyleyen sayfa gösterilir.
export const Route = createFileRoute("/_authenticated/dashboard/calls")({
  component: () => <Navigate to="/dashboard/call-center" replace />,
});

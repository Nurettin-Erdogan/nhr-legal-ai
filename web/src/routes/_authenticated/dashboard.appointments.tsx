import { createFileRoute } from "@tanstack/react-router";
import { Navigate } from "@/lib/router-compat";

// Randevular gerçek calendar_events kayıtlarıyla Takvim ekranında yönetilir.
export const Route = createFileRoute("/_authenticated/dashboard/appointments")({
  component: () => <Navigate to="/dashboard/calendar" replace />,
});

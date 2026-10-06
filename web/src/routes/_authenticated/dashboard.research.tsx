import { createFileRoute } from "@tanstack/react-router";
import { Navigate } from "@/lib/router-compat";

// Hukuk Asistanı ile aynı sohbetti (ayrı adla ikinci kez sunuluyordu); eski adres asistana yönlendirir.
export const Route = createFileRoute("/_authenticated/dashboard/research")({
  component: () => <Navigate to="/dashboard/ai" replace />,
});

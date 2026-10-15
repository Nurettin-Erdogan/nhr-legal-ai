import { createFileRoute } from "@tanstack/react-router";
import { Navigate } from "@/lib/router-compat";

export const Route = createFileRoute("/_authenticated/dashboard/auto-summary")({
  component: () => <Navigate to="/dashboard/ai?mode=summary" replace />,
});

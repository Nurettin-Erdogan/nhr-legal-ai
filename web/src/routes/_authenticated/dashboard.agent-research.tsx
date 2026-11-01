import { createFileRoute } from "@tanstack/react-router";
import { Navigate } from "@/lib/router-compat";

export const Route = createFileRoute("/_authenticated/dashboard/agent-research")({
  component: () => <Navigate to="/dashboard/ai?mode=deep" replace />,
});

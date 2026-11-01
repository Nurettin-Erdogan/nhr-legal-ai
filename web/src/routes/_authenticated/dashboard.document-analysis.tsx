import { createFileRoute } from "@tanstack/react-router";
import { Navigate } from "@/lib/router-compat";

export const Route = createFileRoute("/_authenticated/dashboard/document-analysis")({
  component: () => <Navigate to="/dashboard/ai?mode=analysis" replace />,
});

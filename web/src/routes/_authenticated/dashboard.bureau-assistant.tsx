import { createFileRoute } from "@tanstack/react-router";
import { BureauAssistant } from "@/components/BureauAssistant";

export const Route = createFileRoute("/_authenticated/dashboard/bureau-assistant")({
  component: BureauAssistant,
});

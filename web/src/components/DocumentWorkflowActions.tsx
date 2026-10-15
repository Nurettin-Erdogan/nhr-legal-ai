import { useAuth } from "@/components/AuthProvider";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DOCUMENT_MODES, saveDocumentContext, workflowPath } from "@/lib/document-workflow";
import { useNavigate } from "@/lib/router-compat";
import { Sparkles, ChevronDown } from "lucide-react";
import { toast } from "sonner";

export function DocumentWorkflowActions({
  ids,
  caseId,
  officeProjectId,
  disabled = false,
}: {
  ids: string[];
  caseId?: string;
  officeProjectId?: string;
  disabled?: boolean;
}) {
  const { user } = useAuth();
  const navigate = useNavigate();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" variant="outline" disabled={disabled || !ids.length}>
          <Sparkles className="h-4 w-4" /> Seçili belgelerle çalış{" "}
          <ChevronDown className="h-3 w-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>{ids.length} belge seçili</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {Object.entries(DOCUMENT_MODES).map(([mode, config]) => (
          <DropdownMenuItem
            key={mode}
            disabled={ids.length > config.max}
            onSelect={() => {
              if (!user) return toast.error("Oturum gerekli.");
              try {
                const context = saveDocumentContext(
                  user.id,
                  ids,
                  caseId,
                  undefined,
                  officeProjectId,
                );
                navigate(workflowPath(mode as keyof typeof DOCUMENT_MODES, context));
              } catch (error) {
                toast.error(error instanceof Error ? error.message : "Belge seçimi taşınamadı.");
              }
            }}
          >
            {config.label}
            {ids.length > config.max ? ` (en fazla ${config.max})` : ""}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

import { AlertTriangle, ShieldQuestion } from "lucide-react";
import { useEffect, useState } from "react";
import { registerConfirmationHost, type PendingConfirmation } from "@/lib/confirmation";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { buttonVariants } from "@/components/ui/button-variants";
import { cn } from "@/lib/utils";

/** Tarayıcının `window.confirm` penceresi yerine uygulamanın kendi onay penceresi ("localhost:3000 web sitesinin mesajı"
 * yayında görünmesin, 2026-10-24). Kullanım: `if (!(await confirmAction({ title, description }))) return;` */
export function ConfirmDialogHost() {
  const [request, setRequest] = useState<PendingConfirmation | null>(null);

  useEffect(() => {
    return registerConfirmationHost((next) =>
      setRequest((current) => {
        current?.resolve(false); // açık bir soru varken yenisi gelirse eskisi "vazgeç" sayılır
        return next;
      }),
    );
  }, []);

  const finish = (ok: boolean) => {
    request?.resolve(ok);
    setRequest(null);
  };
  const Icon = request?.destructive ? AlertTriangle : ShieldQuestion;

  return (
    <AlertDialog open={request !== null} onOpenChange={(open) => !open && finish(false)}>
      <AlertDialogContent className="max-w-md">
        <AlertDialogHeader>
          <div className="flex items-start gap-3">
            <span
              className={cn(
                "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
                request?.destructive
                  ? "bg-destructive/15 text-destructive"
                  : "bg-primary/15 text-primary",
              )}
              aria-hidden="true"
            >
              <Icon className="h-5 w-5" />
            </span>
            <div className="space-y-1.5 text-left">
              <AlertDialogTitle>{request?.title}</AlertDialogTitle>
              {request?.description && (
                <AlertDialogDescription className="whitespace-pre-line">
                  {request.description}
                </AlertDialogDescription>
              )}
            </div>
          </div>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => finish(false)}>
            {request?.cancelLabel ?? "Vazgeç"}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={() => finish(true)}
            className={cn(request?.destructive && buttonVariants({ variant: "destructive" }))}
          >
            {request?.confirmLabel ?? "Onayla"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

import { useState } from "react";
import { MessageSquarePlus } from "lucide-react";
import { toast } from "sonner";
import { useLocation } from "@/lib/router-compat";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { FEEDBACK_CATEGORIES, MAX_FEEDBACK, canSendFeedback, sendFeedback, type FeedbackCategory } from "@/lib/feedback";

/** Panelin köşesindeki "Geri bildirim" düğmesi: pilot kullanıcılar hata, öneri ya da beğeni gönderir. */
export function FeedbackButton() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState<FeedbackCategory>("hata");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!canSendFeedback(message) || busy) return;
    setBusy(true);
    try {
      await sendFeedback({ category, message, pathname: location.pathname });
      toast.success("Geri bildiriminiz alındı, teşekkürler.");
      setMessage("");
      setOpen(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Geri bildirim gönderilemedi.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-4 right-4 z-30 inline-flex items-center gap-2 rounded-full border border-border bg-card px-4 py-2 text-sm font-medium shadow-md hover:bg-accent"
        data-testid="feedback-open"
      >
        <MessageSquarePlus className="h-4 w-4" /> Geri bildirim
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Geri bildirim</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div role="radiogroup" aria-label="Geri bildirim türü" className="flex flex-wrap gap-2 text-sm">
              {FEEDBACK_CATEGORIES.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  role="radio"
                  aria-checked={category === item.value}
                  onClick={() => setCategory(item.value)}
                  className={`rounded-full border px-3 py-1 ${category === item.value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent"}`}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <Textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              rows={5}
              maxLength={MAX_FEEDBACK}
              aria-label="Geri bildirim metni"
              placeholder="Ne yapmaya çalışıyordunuz, ne oldu? Müvekkil adı gibi kişisel bilgi yazmayın."
            />
            <p className="text-xs text-muted-foreground">Açık olduğunuz sayfa ({location.pathname}) mesajla birlikte gönderilir; belge ve sohbet içeriği gönderilmez.</p>
            <Button className="w-full" disabled={!canSendFeedback(message) || busy} onClick={() => void submit()}>
              {busy ? "Gönderiliyor…" : "Gönder"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

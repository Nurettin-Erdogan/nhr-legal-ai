import { invokeFunction } from "@/lib/backend";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card } from "@/components/ui/card";
import { Loader2, Send } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { toast } from "sonner";

function Legislation() {
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState("");

  const ask = async () => {
    if (!q.trim()) return;
    setLoading(true);
    setAnswer("");
    try {
      const { data, error } = await invokeFunction("legal-chat", {
        body: { messages: [{ role: "user", content: q }] },
      });
      if (error) throw error;
      setAnswer(data?.content || data?.message || "Cevap alınamadı.");
    } catch (e: any) {
      toast.error(e.message || "Bir hata oluştu");
    } finally {
      setLoading(false);
    }
  };

  return (
    <DashboardLayout title="Güncel Mevzuat Erişimi">
      <div className="max-w-3xl mx-auto space-y-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            ask();
          }}
          className="space-y-3"
        >
          <Textarea
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Hukuki sorunuzu yazın..."
            rows={4}
          />
          <Button type="submit" disabled={loading} className="w-full">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Sor
          </Button>
        </form>

        {(loading || answer) && (
          <Card className="p-6">
            {loading ? (
              <div className="flex items-center gap-3 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> Araştırılıyor...
              </div>
            ) : (
              <article className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap">
                {answer}
              </article>
            )}
          </Card>
        )}
      </div>
    </DashboardLayout>
  );
}

export const Route = createFileRoute("/_authenticated/dashboard/legislation")({
  component: Legislation,
});

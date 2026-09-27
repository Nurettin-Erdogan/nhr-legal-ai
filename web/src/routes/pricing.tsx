import { createFileRoute } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { Sparkles } from "lucide-react";
import { useNavigate } from "@/lib/router-compat";

const Pricing = () => {
  const navigate = useNavigate();
  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4">
      <div className="max-w-md w-full text-center rounded-2xl border bg-card p-10 shadow-card-elite">
        <div className="mx-auto h-14 w-14 rounded-full bg-primary/10 flex items-center justify-center mb-4">
          <Sparkles className="h-7 w-7 text-primary" />
        </div>
        <h1 className="font-serif text-3xl font-semibold">Şu an ücretsiz</h1>
        <p className="mt-3 text-muted-foreground">
          Tüm özellikler şimdilik herkese açık ve ücretsizdir. Ödeme planları ileride eklenecektir.
        </p>
        <Button className="mt-8 w-full" variant="elite" onClick={() => navigate("/dashboard")}>
          Panele Git
        </Button>
      </div>
    </div>
  );
};

export const Route = createFileRoute("/pricing")({
  component: Pricing,
});

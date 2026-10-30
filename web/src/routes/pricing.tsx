import { createFileRoute } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { Sparkles } from "lucide-react";
import { useNavigate } from "@/lib/router-hooks";
import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";

/** Fiyat sayfası diğer açık sayfalarla aynı üst menü ve alt bilgiyi taşır (önceden menüsüz, tek kartlık bir sayfaydı). */
const Pricing = () => {
  const navigate = useNavigate();
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SiteHeader />
      <main className="flex flex-1 items-center justify-center px-4 py-16">
        <div className="max-w-md w-full text-center rounded-2xl border bg-card p-10 shadow-card-elite">
          <div className="mx-auto h-14 w-14 rounded-full bg-primary/10 flex items-center justify-center mb-4">
            <Sparkles className="h-7 w-7 text-primary" />
          </div>
          <h1 className="font-serif text-3xl font-semibold">Şu an ücretsiz</h1>
          <p className="mt-3 text-muted-foreground">
            Tüm özellikler şimdilik herkese açık ve ücretsizdir. Ücretli planlar eklenirse önceden
            duyurulur; mevcut kullanıcılardan habersiz ücret alınmaz.
          </p>
          <Button className="mt-8 w-full" variant="elite" onClick={() => navigate("/dashboard")}>
            Panele Git
          </Button>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
};

export const Route = createFileRoute("/pricing")({
  head: () => ({ meta: [{ title: "Fiyatlandırma — JurisAI" }] }),
  component: Pricing,
});

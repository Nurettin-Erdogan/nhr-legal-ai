import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";
import { BasvuruDialog } from "@/components/BasvuruDialog";
import { Button } from "@/components/ui/button";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { cn } from "@/lib/utils";
import { FAQ_CATEGORIES, FAQ_NOTE, basisLabel, faqByCategory } from "@/lib/faq";
import { MessageSquare } from "lucide-react";

function SSSPage() {
  const [kategori, setKategori] = useState<string>("Tümü");
  const [basvuruOpen, setBasvuruOpen] = useState(false);

  const liste = faqByCategory(kategori);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SiteHeader />

      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-10">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Sık Sorulan Sorular</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Hizmetlerimiz ve süreçler hakkında bilgi edinin.
        </p>

        <div className="mt-6 flex flex-wrap gap-2">
          {FAQ_CATEGORIES.map((k) => (
            <button
              key={k}
              onClick={() => setKategori(k)}
              className={cn(
                "rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors",
                kategori === k
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-muted-foreground hover:text-foreground",
              )}
            >
              {k}
            </button>
          ))}
        </div>

        <div className="mt-6 rounded-2xl border border-border bg-card px-4 shadow-card-elite">
          <Accordion type="single" collapsible>
            {liste.map((s, i) => (
              <AccordionItem key={s.q} value={`item-${i}`}>
                <AccordionTrigger className="text-left text-sm font-medium">{s.q}</AccordionTrigger>
                <AccordionContent className="text-sm leading-relaxed text-muted-foreground">
                  {s.a}
                  {s.dayanak && (
                    <p className="mt-2 text-xs" data-testid="faq-basis">
                      <span className="font-medium text-foreground">Dayanak:</span>{" "}
                      {basisLabel(s.dayanak)}
                    </p>
                  )}
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>

        <p
          className="mt-4 text-xs leading-relaxed text-muted-foreground"
          role="note"
          data-testid="faq-note"
        >
          {FAQ_NOTE}
        </p>

        <div className="mt-8 flex flex-col items-center gap-3 rounded-2xl bg-secondary p-6 text-center">
          <p className="text-sm text-muted-foreground">
            Sorunuzun cevabını bulamadınız mı? Durumunuzu bir avukata iletin.
          </p>
          <Button className="rounded-full" onClick={() => setBasvuruOpen(true)}>
            <MessageSquare className="h-4 w-4" /> Avukata Yönlendir
          </Button>
        </div>
      </main>

      <SiteFooter />
      <BasvuruDialog open={basvuruOpen} onOpenChange={setBasvuruOpen} />
    </div>
  );
}

export const Route = createFileRoute("/sss")({
  head: () => ({
    meta: [
      { title: "Sık Sorulan Sorular — JurisAI" },
      {
        name: "description",
        content:
          "İşten çıkarılma, boşanma, nafaka, vekâletname ve dava süreleri hakkında en çok sorulan hukuki soruların yanıtları.",
      },
      { property: "og:title", content: "Sık Sorulan Sorular — JurisAI" },
      {
        property: "og:description",
        content: "Hukuki süreçler, belgeler ve haklarınız hakkında merak edilenler.",
      },
    ],
  }),
  component: SSSPage,
});

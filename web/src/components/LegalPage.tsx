import type { ReactNode } from "react";
import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";
import { LEGAL_DRAFT } from "@/lib/legal";

export interface LegalSection {
  title: string;
  body: ReactNode;
}

/** Hukuki metin sayfası: başlık, sürüm, taslak uyarısı ve numaralı bölümler. */
export function LegalPage({ title, version, intro, sections }: { title: string; version: string; intro?: ReactNode; sections: LegalSection[] }) {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SiteHeader />
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-10">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1 text-xs text-muted-foreground" data-testid="legal-version">
          Sürüm: {version}
        </p>
        {LEGAL_DRAFT && (
          <p role="note" className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-amber-800 dark:text-amber-300" data-testid="legal-draft">
            Bu metin <strong>taslaktır</strong>: yayından önce bir hukuk danışmanı tarafından gözden geçirilmeli ve köşeli parantezli alanlar (veri sorumlusu bilgileri, saklama süreleri)
            doldurulmalıdır.
          </p>
        )}
        {intro && <div className="mt-4 text-sm leading-relaxed text-muted-foreground">{intro}</div>}
        <div className="mt-8 space-y-8">
          {sections.map((section, index) => (
            <section key={section.title} aria-labelledby={`bolum-${index + 1}`} className="space-y-2 text-sm leading-relaxed">
              <h2 id={`bolum-${index + 1}`} className="text-base font-semibold">
                {index + 1}. {section.title}
              </h2>
              {section.body}
            </section>
          ))}
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}

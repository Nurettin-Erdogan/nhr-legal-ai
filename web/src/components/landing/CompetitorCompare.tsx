import { Check, X, Minus, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

type Cell = "yes" | "no" | "partial" | string;

const ROWS: {
  feature: string;
  apilex: Cell;
  manual: Cell;
  excel: Cell;
  legacy: Cell;
  note?: string;
}[] = [
  {
    feature: "Semantik karar arama (anlam tabanlı)",
    apilex: "yes",
    manual: "no",
    excel: "no",
    legacy: "partial",
  },
  {
    feature: "AI hukuk asistanı (gerçek atıflarla)",
    apilex: "yes",
    manual: "no",
    excel: "no",
    legacy: "no",
  },
  {
    feature: "Otomatik dilekçe & sözleşme taslağı",
    apilex: "yes",
    manual: "no",
    excel: "no",
    legacy: "partial",
  },
  {
    feature: "Doküman analiz & risk tespiti",
    apilex: "yes",
    manual: "no",
    excel: "no",
    legacy: "no",
  },
  {
    feature: "Akıllı çalışma alanı (Projeler)",
    apilex: "yes",
    manual: "no",
    excel: "partial",
    legacy: "partial",
  },
  {
    feature: "AI çağrı asistanı (7/24 Türkçe)",
    apilex: "yes",
    manual: "no",
    excel: "no",
    legacy: "no",
  },
  {
    feature: "UYAP entegre takvim & duruşma takibi",
    apilex: "yes",
    manual: "partial",
    excel: "no",
    legacy: "yes",
  },
  {
    feature: "Tahsilat otomasyonu & hatırlatma",
    apilex: "yes",
    manual: "no",
    excel: "no",
    legacy: "partial",
  },
  {
    feature: "KVKK + ISO 27001 uyumlu altyapı",
    apilex: "yes",
    manual: "no",
    excel: "no",
    legacy: "partial",
  },
  {
    feature: "5 dakikada kurulum, sıfır donanım",
    apilex: "yes",
    manual: "no",
    excel: "yes",
    legacy: "no",
  },
  {
    feature: "Ortalama aylık zaman kazancı",
    apilex: "~38 saat",
    manual: "0",
    excel: "~3 saat",
    legacy: "~12 saat",
  },
];

type Col = {
  key: "apilex" | "manual" | "excel" | "legacy";
  label: string;
  sub: string;
  highlight?: boolean;
};
const COLS: Col[] = [
  { key: "apilex", label: "JurisAI", sub: "Yeni nesil hukuk SaaS", highlight: true },
  { key: "manual", label: "Manuel", sub: "Klasör + Word + telefon" },
  { key: "excel", label: "Excel + Drive", sub: "Tablo bazlı takip" },
  { key: "legacy", label: "Eski yazılımlar", sub: "On-premise / klasik" },
];

function CellIcon({ value }: { value: Cell }) {
  if (value === "yes") return <Check className="h-5 w-5 text-success" strokeWidth={3} />;
  if (value === "no") return <X className="h-5 w-5 text-destructive/70" strokeWidth={2.5} />;
  if (value === "partial")
    return <Minus className="h-5 w-5 text-muted-foreground" strokeWidth={2.5} />;
  return <span className="text-sm font-semibold text-foreground">{value}</span>;
}

export function CompetitorCompare() {
  return (
    <section className="py-24 lg:py-32 bg-background">
      <div className="container-elite">
        <div className="max-w-2xl mx-auto text-center mb-14">
          <span className="text-xs font-semibold tracking-[0.2em] text-gold uppercase">
            Karşılaştırma
          </span>
          <h2 className="mt-4 font-serif text-4xl md:text-5xl font-semibold">
            JurisAI vs. Diğer Çözümler
          </h2>
          <p className="mt-4 text-muted-foreground">
            Hukuk ofisleri JurisAI'ya geçtiğinde ne kazanır? Manuel iş akışları, tablolar ve eski
            yazılımlarla doğrudan karşılaştırma.
          </p>
        </div>

        <div className="rounded-3xl border border-border bg-gradient-card shadow-elegant overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left px-5 py-5 font-semibold text-muted-foreground text-xs uppercase tracking-wider">
                    Özellik
                  </th>
                  {COLS.map((c) => (
                    <th
                      key={c.key}
                      className={cn(
                        "px-4 py-5 text-center align-bottom",
                        c.highlight && "bg-gradient-to-b from-gold/10 to-transparent",
                      )}
                    >
                      <div
                        className={cn(
                          "inline-flex flex-col items-center gap-1",
                          c.highlight && "text-gold-deep",
                        )}
                      >
                        {c.highlight && (
                          <span className="inline-flex items-center gap-1 text-[10px] font-semibold tracking-wider uppercase text-gold-deep mb-1">
                            <Sparkles className="h-3 w-3" /> Önerilen
                          </span>
                        )}
                        <span
                          className={cn(
                            "font-serif text-lg font-semibold",
                            c.highlight ? "text-gold-deep" : "text-foreground",
                          )}
                        >
                          {c.label}
                        </span>
                        <span className="text-[11px] font-normal text-muted-foreground">
                          {c.sub}
                        </span>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ROWS.map((row, i) => (
                  <tr
                    key={row.feature}
                    className={cn(
                      "border-b border-border/60 last:border-b-0",
                      i % 2 === 1 && "bg-secondary/20",
                    )}
                  >
                    <td className="px-5 py-4 font-medium text-foreground/90">{row.feature}</td>
                    {COLS.map((c) => (
                      <td
                        key={c.key}
                        className={cn("px-4 py-4 text-center", c.highlight && "bg-gold/[0.04]")}
                      >
                        <div className="inline-flex items-center justify-center">
                          <CellIcon value={row[c.key as keyof typeof row] as Cell} />
                        </div>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Bottom bar */}
          <div className="px-5 py-5 border-t border-border bg-secondary/30 flex flex-col sm:flex-row items-center justify-between gap-3">
            <div className="text-xs text-muted-foreground flex items-center gap-2">
              <Check className="h-3.5 w-3.5 text-success" /> Tam destek
              <span className="mx-1">·</span>
              <Minus className="h-3.5 w-3.5 text-muted-foreground" /> Kısmi
              <span className="mx-1">·</span>
              <X className="h-3.5 w-3.5 text-destructive/70" /> Yok
            </div>
            <a
              href="#pricing"
              className="text-xs font-semibold text-gold-deep hover:text-gold transition inline-flex items-center gap-1"
            >
              Fiyat planlarına bak →
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}

import { Building2 } from "lucide-react";

const LOGOS = [
  "Yılmaz & Partners",
  "Akhukuk",
  "Demir Legal",
  "Öztürk Avukatlık",
  "Kaya Hukuk Bürosu",
  "Aydın & Co.",
  "Erdem Legal Group",
  "Çelik Hukuk",
  "Polat Avukatlık",
  "Şahin Legal",
  "Arslan & Partners",
  "Doğan Hukuk",
];

export function LogoMarquee() {
  return (
    <section className="py-14 lg:py-16 bg-background border-b border-border">
      <div className="container-elite">
        <p className="text-center text-xs font-semibold tracking-[0.25em] text-muted-foreground uppercase mb-8">
          Türkiye'nin önde gelen <span className="text-gold-deep">350+ hukuk ofisi</span> AvukatAI
          kullanıyor
        </p>

        <div
          className="relative overflow-hidden"
          style={{
            maskImage: "linear-gradient(to right, transparent, black 12%, black 88%, transparent)",
            WebkitMaskImage:
              "linear-gradient(to right, transparent, black 12%, black 88%, transparent)",
          }}
        >
          <div className="flex gap-12 animate-marquee whitespace-nowrap">
            {[...LOGOS, ...LOGOS].map((name, i) => (
              <div
                key={i}
                className="flex items-center gap-2.5 shrink-0 opacity-60 hover:opacity-100 transition"
              >
                <Building2 className="h-5 w-5 text-gold-deep" />
                <span className="font-serif text-lg md:text-xl font-semibold tracking-tight text-foreground/80">
                  {name}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

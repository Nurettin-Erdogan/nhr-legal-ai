import { useEffect, useState } from "react";
import { Search, Sparkles, FileText, Scale, ArrowRight, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

type Query = {
  q: string;
  answer: string;
  refs: { title: string; meta: string }[];
};

const QUERIES: Query[] = [
  {
    q: "İşçinin fazla mesai alacağı zamanaşımı süresi nedir?",
    answer:
      "İş Kanunu m.32 ve Borçlar Kanunu m.147/1 uyarınca fazla mesai ücreti alacakları **5 yıllık zamanaşımı** süresine tabidir. Süre, alacağın muaccel olduğu tarihten itibaren işler. Yargıtay 9. HD'nin yerleşik içtihatları da bu yöndedir.",
    refs: [
      {
        title: "Yargıtay 9. HD, 2022/14523 E.",
        meta: "Fazla mesai · Zamanaşımı · Karar tarihi 14.03.2023",
      },
      {
        title: "Yargıtay HGK, 2021/9-487 E.",
        meta: "İş alacakları · 5 yıllık zamanaşımı uygulaması",
      },
      { title: "İş Kanunu m.32 / TBK m.147", meta: "Mevzuat referansı" },
    ],
  },
  {
    q: "Kira artış oranı TÜFE sınırı nasıl uygulanır?",
    answer:
      "6098 sayılı TBK m.344 uyarınca konut ve çatılı işyeri kiralarında yıllık artış, **bir önceki kira yılının TÜFE on iki aylık ortalamasını** aşamaz. 7409 sayılı geçici düzenleme ile konut kiralarında %25 üst sınır da uygulanmıştır.",
    refs: [
      { title: "Yargıtay 3. HD, 2023/2891 E.", meta: "Kira tespiti · TÜFE sınırı · 09.05.2024" },
      { title: "TBK m.344 / 7409 sayılı Kanun", meta: "Mevzuat ve geçici hüküm" },
      { title: "Yargıtay HGK 2022/3-118", meta: "Üst sınır emredici nitelikte" },
    ],
  },
  {
    q: "Boşanmada ortak velayet hangi şartlarda verilir?",
    answer:
      "11. Protokol sonrası Yargıtay 2. HD ortak velayetin **çocuğun üstün yararına uygunluğu, ebeveynler arasında işbirliği imkanı** ve çocuğun rızası gibi kriterler birlikte sağlandığında ortak velayetin tesis edilebileceğini kabul etmektedir.",
    refs: [
      { title: "Yargıtay 2. HD, 2017/11337 E.", meta: "Ortak velayet · İlk emsal karar" },
      { title: "Yargıtay 2. HD, 2023/4421 E.", meta: "Çocuğun üstün yararı kriteri" },
      { title: "TMK m.336 / 11 No'lu Protokol", meta: "Mevzuat referansı" },
    ],
  },
];

export function InteractiveDemo() {
  const [activeIdx, setActiveIdx] = useState(0);
  const [typed, setTyped] = useState("");
  const [phase, setPhase] = useState<"typing" | "thinking" | "answer">("typing");
  const [revealedRefs, setRevealedRefs] = useState(0);

  const current = QUERIES[activeIdx];

  // Typing animation for the search query
  useEffect(() => {
    setTyped("");
    setPhase("typing");
    setRevealedRefs(0);

    let i = 0;
    const typer = setInterval(() => {
      i++;
      setTyped(current.q.slice(0, i));
      if (i >= current.q.length) {
        clearInterval(typer);
        setTimeout(() => setPhase("thinking"), 400);
      }
    }, 35);

    return () => clearInterval(typer);
  }, [activeIdx, current.q]);

  // Thinking → answer transition
  useEffect(() => {
    if (phase !== "thinking") return;
    const t = setTimeout(() => setPhase("answer"), 1100);
    return () => clearTimeout(t);
  }, [phase]);

  // Stagger reference reveal
  useEffect(() => {
    if (phase !== "answer") return;
    let n = 0;
    const refTimer = setInterval(() => {
      n++;
      setRevealedRefs(n);
      if (n >= current.refs.length) clearInterval(refTimer);
    }, 280);

    // Auto-advance to next query
    const advance = setTimeout(() => {
      setActiveIdx((i) => (i + 1) % QUERIES.length);
    }, 6500);

    return () => {
      clearInterval(refTimer);
      clearTimeout(advance);
    };
  }, [phase, current.refs.length]);

  return (
    <section className="relative py-20 lg:py-28 bg-background overflow-hidden">
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 h-[480px] w-[760px] rounded-full bg-gold/5 blur-3xl" />
      </div>

      <div className="container-elite relative">
        <div className="max-w-2xl mx-auto text-center mb-12">
          <span className="text-xs font-semibold tracking-[0.2em] text-gold uppercase">
            Canlı Demo
          </span>
          <h2 className="mt-4 font-serif text-4xl md:text-5xl font-semibold">
            Soruyu yazın.{" "}
            <span className="text-gold-deep">JurisAI saniyeler içinde cevaplasın.</span>
          </h2>
          <p className="mt-4 text-muted-foreground">
            Aşağıdaki demo gerçek bir semantik arama akışını simüle eder — milyonlarca karar
            arasından emsal niteliği taşıyanları getirir.
          </p>
        </div>

        <div className="max-w-4xl mx-auto">
          {/* Browser chrome */}
          <div className="rounded-3xl border border-border bg-gradient-card shadow-elegant overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3 border-b border-border bg-secondary/40">
              <div className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-destructive/60" />
                <span className="h-2.5 w-2.5 rounded-full bg-gold/60" />
                <span className="h-2.5 w-2.5 rounded-full bg-success/60" />
              </div>
              <div className="text-[11px] font-mono text-muted-foreground tracking-wide">
                apilex.ai/asistan
              </div>
              <div className="inline-flex items-center gap-1 text-[10px] font-medium text-success">
                <span className="h-1.5 w-1.5 rounded-full bg-success animate-pulse" /> Canlı
              </div>
            </div>

            {/* Search bar */}
            <div className="p-5 md:p-7 border-b border-border">
              <div className="flex items-center gap-3 px-4 py-4 rounded-2xl border border-border bg-background shadow-soft">
                <Search className="h-5 w-5 text-gold-deep shrink-0" />
                <div className="flex-1 text-sm md:text-base font-medium text-foreground min-h-[1.5em]">
                  {typed}
                  <span
                    className={cn(
                      "inline-block w-[2px] h-[1em] align-middle bg-gold-deep ml-0.5",
                      phase === "typing" ? "animate-pulse" : "opacity-0",
                    )}
                  />
                </div>
                <button
                  className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-medium"
                  type="button"
                  tabIndex={-1}
                >
                  Ara <ArrowRight className="h-3 w-3" />
                </button>
              </div>

              {/* Query chips */}
              <div className="mt-4 flex flex-wrap gap-2">
                <span className="text-[11px] uppercase tracking-wider text-muted-foreground self-center mr-1">
                  Örnekler:
                </span>
                {QUERIES.map((q, i) => (
                  <button
                    key={i}
                    onClick={() => setActiveIdx(i)}
                    className={cn(
                      "text-xs px-3 py-1.5 rounded-full border transition",
                      i === activeIdx
                        ? "border-gold/60 bg-gold/10 text-gold-deep font-medium"
                        : "border-border text-muted-foreground hover:border-gold/30 hover:text-foreground",
                    )}
                  >
                    {q.q.length > 42 ? q.q.slice(0, 42) + "…" : q.q}
                  </button>
                ))}
              </div>
            </div>

            {/* Result area */}
            <div className="p-5 md:p-7 min-h-[320px] bg-background">
              {phase === "thinking" && (
                <div className="flex items-center gap-3 text-muted-foreground animate-fade-in">
                  <Loader2 className="h-4 w-4 animate-spin text-gold-deep" />
                  <span className="text-sm">JurisAI emsal kararları analiz ediyor…</span>
                </div>
              )}

              {phase === "answer" && (
                <div className="grid md:grid-cols-5 gap-6 animate-fade-up">
                  {/* AI Answer */}
                  <div className="md:col-span-3 space-y-3">
                    <div className="inline-flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-gold-deep">
                      <Sparkles className="h-3.5 w-3.5" /> AI Cevabı
                    </div>
                    <p
                      className="text-[15px] leading-relaxed text-foreground"
                      dangerouslySetInnerHTML={{
                        __html: current.answer.replace(
                          /\*\*(.+?)\*\*/g,
                          '<strong class="text-gold-deep font-semibold">$1</strong>',
                        ),
                      }}
                    />
                    <div className="flex items-center gap-2 pt-2 text-xs text-muted-foreground">
                      <Scale className="h-3.5 w-3.5" />
                      <span>
                        Cevap, aşağıdaki{" "}
                        <strong className="text-foreground">
                          {current.refs.length} emsal kaynak
                        </strong>{" "}
                        referans alınarak oluşturuldu.
                      </span>
                    </div>
                  </div>

                  {/* References */}
                  <div className="md:col-span-2 space-y-2">
                    <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                      Emsal Kararlar
                    </div>
                    {current.refs.map((r, i) => (
                      <div
                        key={i}
                        className={cn(
                          "p-3 rounded-xl border border-border bg-card hover:border-gold/40 transition cursor-pointer group",
                          i < revealedRefs
                            ? "opacity-100 translate-y-0"
                            : "opacity-0 translate-y-2",
                          "transition-all duration-500",
                        )}
                      >
                        <div className="flex items-start gap-2.5">
                          <div className="h-8 w-8 rounded-lg bg-accent-soft flex items-center justify-center shrink-0">
                            <FileText className="h-4 w-4 text-gold-deep" />
                          </div>
                          <div className="min-w-0">
                            <div className="text-sm font-medium leading-tight group-hover:text-gold-deep transition truncate">
                              {r.title}
                            </div>
                            <div className="text-[11px] text-muted-foreground mt-0.5 truncate">
                              {r.meta}
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Footnote */}
          <p className="mt-6 text-center text-xs text-muted-foreground">
            Demo verileri tanıtım amaçlıdır. Gerçek kullanımda JurisAI, milyonlarca
            Yargıtay/Danıştay kararı + ofis arşivinizden cevap üretir.
          </p>
        </div>
      </div>
    </section>
  );
}

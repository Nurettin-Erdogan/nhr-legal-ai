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
import { MessageSquare } from "lucide-react";

const KATEGORILER = ["Tümü", "Genel", "İş Hukuku", "Aile Hukuku", "Belgeler"] as const;

const SORULAR: Array<{ kategori: string; q: string; a: string }> = [
  {
    kategori: "Genel",
    q: "İlk görüşme ücretli mi?",
    a: "NHR Hukuk üzerinden yaptığınız ön görüşme ve bilgilendirme tamamen ücretsizdir. Dosyanız avukata aktarıldıktan sonra ücret, işin kapsamına göre baro asgari ücret tarifesi esas alınarak belirlenir ve başlamadan önce size yazılı olarak bildirilir.",
  },
  {
    kategori: "Genel",
    q: "Hangi alanlarda hizmet veriyorsunuz?",
    a: "İş hukuku, aile hukuku (boşanma, nafaka, velayet), kira ve borçlar hukuku, icra takipleri, tazminat davaları, ceza hukuku, miras ve tüketici uyuşmazlıkları başlıca çalışma alanlarımızdır.",
  },
  {
    kategori: "Genel",
    q: "Dava süreci ne kadar sürer?",
    a: "Süre; mahkemenin iş yüküne, delillerin durumuna ve dosyanın niteliğine göre değişir. İlk derece mahkemelerinde ortalama 1–2 yıl, istinaf ve temyiz aşamalarıyla birlikte 2–4 yıl arasında sonuçlanır. Arabuluculuk zorunlu olan uyuşmazlıklarda süreç birkaç ay içinde çözülebilir.",
  },
  {
    kategori: "Genel",
    q: "Bilgilerim gizli tutulur mu?",
    a: "Evet. Paylaştığınız bilgiler avukatın sır saklama yükümlülüğü ve KVKK kapsamında korunur; yalnızca başvurunuzu değerlendirmek için kullanılır.",
  },
  {
    kategori: "İş Hukuku",
    q: "İşten çıkarıldım, hangi haklarım var?",
    a: "Haklı bir neden gösterilmeden yapılan fesihte kıdem ve ihbar tazminatı, kullanılmayan yıllık izin ücreti, varsa fazla mesai ve prim alacaklarınızı talep edebilirsiniz. 30 veya daha fazla işçi çalıştıran iş yerinde ve 6 aylık kıdemin varsa işe iade davası açma hakkınız da bulunur.",
  },
  {
    kategori: "İş Hukuku",
    q: "İşe iade davası için süre sınırı var mı?",
    a: "Fesih bildiriminin size tebliğinden itibaren 1 ay içinde arabulucuya başvurmanız gerekir. Arabuluculuk anlaşmazlıkla sonuçlanırsa, son tutanağın düzenlendiği tarihten itibaren 2 hafta içinde dava açılmalıdır.",
  },
  {
    kategori: "İş Hukuku",
    q: "Fazla mesai ücretimi nasıl ispatlarım?",
    a: "Puantaj kayıtları, giriş-çıkış turnike verileri, mesajlar, e-postalar ve tanık beyanları kullanılabilir. Kayıt tutmanız ve yazışmaları saklamanız ispatı kolaylaştırır.",
  },
  {
    kategori: "Aile Hukuku",
    q: "Boşanma süreci nasıl işler?",
    a: "Taraflar anlaşırsa protokolle anlaşmalı boşanma tek duruşmada sonuçlanabilir (1 yıllık evlilik şartıyla). Anlaşma yoksa çekişmeli boşanma davasında deliller ve tanıklar dinlenir; süreç genellikle 1–2 yıl sürer.",
  },
  {
    kategori: "Aile Hukuku",
    q: "Nafaka miktarı nasıl belirlenir?",
    a: "Tarafların gelir durumu, çocuğun ihtiyaçları, yaşı ve eğitim durumu dikkate alınır. Tedbir nafakası dava süresince, iştirak nafakası çocuk için, yoksulluk nafakası ise yoksulluğa düşen eş için hükmedilir.",
  },
  {
    kategori: "Aile Hukuku",
    q: "Velayet kime verilir?",
    a: "Belirleyici ölçüt çocuğun üstün yararıdır. Küçük yaştaki çocuklarda anne bakımına öncelik verilme eğilimi olsa da mahkeme, tarafların yaşam koşullarını ve çocuğun idrak yaşındaysa görüşünü de değerlendirir.",
  },
  {
    kategori: "Belgeler",
    q: "Başvuru için hangi belgeleri hazırlamalıyım?",
    a: "Kimlik fotokopisi, konuya ilişkin sözleşmeler, bordro veya SGK hizmet dökümü, ihtarname ve tebligatlar, yazışma ekran görüntüleri ve varsa mahkeme evrakları yeterlidir.",
  },
  {
    kategori: "Belgeler",
    q: "Vekâletname nasıl çıkarılır?",
    a: "Herhangi bir notere kimliğinizle giderek avukatın bilgileriyle genel dava vekâletnamesi düzenletebilirsiniz. Boşanma davalarında fotoğraflı vekâletname zorunludur.",
  },
  {
    kategori: "Belgeler",
    q: "Belgelerimi dijital olarak iletebilir miyim?",
    a: "Evet. Başvurunuz alındıktan sonra tarafımızdan iletilecek güvenli bağlantı üzerinden ya da e-posta ile belgelerinizi paylaşabilirsiniz.",
  },
];

function SSSPage() {
  const [kategori, setKategori] = useState<string>("Tümü");
  const [basvuruOpen, setBasvuruOpen] = useState(false);

  const liste = kategori === "Tümü" ? SORULAR : SORULAR.filter((s) => s.kategori === kategori);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SiteHeader />

      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-10">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Sık Sorulan Sorular</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Hizmetlerimiz ve süreçler hakkında bilgi edinin.
        </p>

        <div className="mt-6 flex flex-wrap gap-2">
          {KATEGORILER.map((k) => (
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
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>

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
      { title: "Sık Sorulan Sorular — NHR Hukuk" },
      {
        name: "description",
        content:
          "İşten çıkarılma, boşanma, nafaka, vekâletname ve dava süreleri hakkında en çok sorulan hukuki soruların yanıtları.",
      },
      { property: "og:title", content: "Sık Sorulan Sorular — NHR Hukuk" },
      {
        property: "og:description",
        content: "Hukuki süreçler, belgeler ve haklarınız hakkında merak edilenler.",
      },
    ],
  }),
  component: SSSPage,
});

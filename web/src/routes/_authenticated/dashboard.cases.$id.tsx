import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { useParams, Link } from "@/lib/router-compat";
import { cases } from "@/data/mock";
import { ArrowLeft, FileText, MessageSquare, Phone, Sparkles, Clock, Wallet } from "lucide-react";

const tabs = ["Özet", "Evraklar", "Notlar", "Zaman Çizelgesi", "Tahsilat", "Aramalar", "AI Özet"];

const CaseDetail = () => {
  const { id } = useParams();
  const c: any = cases.find((x: any) => String(x.id) === id) || {
    no: id ?? "—",
    client: "—",
    opponent: "—",
    court: "—",
    type: "—",
    status: "—",
    lawyer: "—",
    hearing: "—",
  };

  return (
    <DashboardLayout
      title={`Dosya ${c.no}`}
      subtitle={`${c.client} vs ${c.opponent}`}
      actions={
        <Link to="/dashboard/cases">
          <Button variant="outline" size="sm">
            <ArrowLeft className="h-4 w-4" />
            Listeye Dön
          </Button>
        </Link>
      }
    >
      <div className="grid lg:grid-cols-3 gap-6 mb-6">
        <div className="lg:col-span-2 p-6 rounded-2xl bg-card border border-border shadow-card-elite">
          <div className="flex flex-wrap gap-2 mb-4 border-b border-border pb-4">
            {tabs.map((t, i) => (
              <button
                key={t}
                className={`px-3.5 py-1.5 rounded-md text-xs font-medium transition ${i === 0 ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-secondary"}`}
              >
                {t}
              </button>
            ))}
          </div>

          <h3 className="font-serif text-xl font-semibold mb-4">Dosya Özeti</h3>
          <dl className="grid sm:grid-cols-2 gap-x-8 gap-y-3 text-sm">
            <div>
              <dt className="text-xs text-muted-foreground">Mahkeme</dt>
              <dd className="mt-0.5">{c.court}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Dava Türü</dt>
              <dd className="mt-0.5">{c.type}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Durum</dt>
              <dd className="mt-0.5">{c.status}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Sorumlu Avukat</dt>
              <dd className="mt-0.5">{c.lawyer}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Son İşlem</dt>
              <dd className="mt-0.5">{c.lastAction}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Sıradaki Duruşma</dt>
              <dd className="mt-0.5 text-gold-deep font-medium">{c.hearing}</dd>
            </div>
          </dl>

          <div className="mt-6 p-4 rounded-xl bg-gradient-to-br from-accent-soft to-transparent border border-gold/30">
            <div className="flex items-center gap-2 text-xs font-semibold text-gold-deep uppercase tracking-wider mb-2">
              <Sparkles className="h-3.5 w-3.5" /> AI Özet
            </div>
            <p className="text-sm leading-relaxed">
              Dosyada bilirkişi raporuna {c.lawyer} tarafından itiraz edildi. Karşı taraf vekili ek
              süre talep etti. Önümüzdeki duruşmada tanık dinlenmesi planlanıyor. Başarı tahmini:{" "}
              <strong>%72</strong>.
            </p>
          </div>
        </div>

        <div className="space-y-4">
          <div className="p-5 rounded-2xl bg-card border border-border shadow-card-elite">
            <h4 className="font-serif font-semibold mb-3">Hızlı İşlemler</h4>
            <div className="space-y-2">
              <Button variant="outline" className="w-full justify-start">
                <FileText className="h-4 w-4" /> Evrak Yükle
              </Button>
              <Button variant="outline" className="w-full justify-start">
                <MessageSquare className="h-4 w-4" /> Not Ekle
              </Button>
              <Button variant="outline" className="w-full justify-start">
                <Phone className="h-4 w-4" /> AI Bilgilendirme Ara
              </Button>
              <Button variant="outline" className="w-full justify-start">
                <Wallet className="h-4 w-4" /> Tahsilat Ekle
              </Button>
            </div>
          </div>

          <div className="p-5 rounded-2xl bg-card border border-border shadow-card-elite">
            <h4 className="font-serif font-semibold mb-3 flex items-center gap-2">
              <Clock className="h-4 w-4 text-gold" /> Son Aktivite
            </h4>
            <ul className="space-y-3 text-xs">
              {[
                "Bilirkişi raporu UYAP'tan indirildi",
                "Av. Selim Korkmaz not ekledi",
                "Müvekkile AI bilgilendirme yapıldı",
                "Duruşma tutanağı eklendi",
              ].map((a, i) => (
                <li key={i} className="flex gap-3">
                  <span className="h-1.5 w-1.5 rounded-full bg-gold mt-1.5 shrink-0" />
                  <div>
                    <div>{a}</div>
                    <div className="text-muted-foreground mt-0.5">{i + 1} gün önce</div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/cases/$id")({
  component: CaseDetail,
});

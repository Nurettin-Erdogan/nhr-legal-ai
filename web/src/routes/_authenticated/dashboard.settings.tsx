import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { Building2, Clock, Mic, Phone, Plug, Bell } from "lucide-react";

const tabs = [
  { id: "office", label: "Ofis Bilgileri", icon: Building2 },
  { id: "hours", label: "Çalışma Saatleri", icon: Clock },
  { id: "voice", label: "AI Konuşma Tarzı", icon: Mic },
  { id: "phone", label: "Telefon Ayarları", icon: Phone },
  { id: "integrations", label: "Entegrasyonlar", icon: Plug },
  { id: "notifications", label: "Bildirimler", icon: Bell },
];

const voiceStyles = [
  { id: "formal", name: "Resmi", desc: "Klasik, mesafeli ve protokol odaklı." },
  { id: "natural", name: "Doğal", desc: "Akıcı, günlük konuşma diline yakın." },
  { id: "warm", name: "Sıcak", desc: "Empatik, samimi ve güven verici." },
  { id: "premium", name: "Premium", desc: "Ölçülü, üst düzey kurumsal tonlama." },
  { id: "concise", name: "Kısa ve Net", desc: "Hızlı, doğrudan ve verimli." },
];

const Field = ({ label, ...props }: any) => (
  <label className="block">
    <span className="block text-xs font-medium uppercase tracking-wider text-muted-foreground mb-2">
      {label}
    </span>
    <input
      {...props}
      className="w-full h-11 px-4 rounded-lg bg-card border border-border focus:border-gold/50 outline-none transition text-sm"
    />
  </label>
);

const Settings = () => {
  const [tab, setTab] = useState("office");
  const [voice, setVoice] = useState("premium");

  return (
    <DashboardLayout title="Ayarlar" subtitle="Asistan davranışını ve entegrasyonları yönetin">
      <div className="grid lg:grid-cols-[260px_1fr] gap-6">
        <aside className="rounded-2xl bg-card border border-border shadow-card-elite p-2 h-fit">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                "flex items-center gap-3 w-full px-4 py-3 text-sm rounded-lg transition",
                tab === t.id
                  ? "bg-primary text-primary-foreground"
                  : "hover:bg-secondary text-foreground/70",
              )}
            >
              <t.icon className="h-4 w-4" />
              {t.label}
            </button>
          ))}
        </aside>

        <div className="rounded-2xl bg-card border border-border shadow-card-elite p-8">
          {tab === "office" && (
            <div className="space-y-6">
              <h2 className="font-serif text-2xl font-semibold divider-gold">Ofis Bilgileri</h2>
              <div className="grid md:grid-cols-2 gap-5">
                <Field label="Ofis Adı" defaultValue="Korkmaz Hukuk Bürosu" />
                <Field label="Yetkili Kişi" defaultValue="Av. Selim Korkmaz" />
                <Field label="Telefon" defaultValue="+90 212 555 00 00" />
                <Field label="WhatsApp" defaultValue="+90 532 555 00 00" />
                <Field label="Adres" defaultValue="Levent, İstanbul" />
                <Field label="E-posta" defaultValue="iletisim@korkmazhukuk.com" />
              </div>
              <div className="pt-4 flex justify-end gap-3">
                <Button variant="outline">İptal</Button>
                <Button variant="elite">Kaydet</Button>
              </div>
            </div>
          )}

          {tab === "hours" && (
            <div className="space-y-6">
              <h2 className="font-serif text-2xl font-semibold divider-gold">Çalışma Saatleri</h2>
              <div className="grid md:grid-cols-2 gap-5">
                <Field label="Başlangıç" type="time" defaultValue="09:00" />
                <Field label="Bitiş" type="time" defaultValue="18:00" />
              </div>
              <label className="flex items-center justify-between p-4 rounded-lg border border-border">
                <div>
                  <div className="font-medium">Hafta Sonu Açık</div>
                  <div className="text-xs text-muted-foreground">
                    Cumartesi-Pazar AI yine cevap versin
                  </div>
                </div>
                <input type="checkbox" className="h-5 w-5 accent-gold" />
              </label>
              <label className="flex items-center justify-between p-4 rounded-lg border border-border">
                <div>
                  <div className="font-medium">Ön görüşme ücretli</div>
                  <div className="text-xs text-muted-foreground">
                    İlk danışmanlık için ücret bilgisi verilsin
                  </div>
                </div>
                <input type="checkbox" className="h-5 w-5 accent-gold" defaultChecked />
              </label>
              <div className="pt-4 flex justify-end gap-3">
                <Button variant="elite">Kaydet</Button>
              </div>
            </div>
          )}

          {tab === "voice" && (
            <div className="space-y-6">
              <h2 className="font-serif text-2xl font-semibold divider-gold">AI Konuşma Tarzı</h2>
              <p className="text-muted-foreground text-sm">
                Asistanınızın müvekkillerle nasıl konuşmasını istediğinizi seçin.
              </p>
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {voiceStyles.map((v) => (
                  <button
                    key={v.id}
                    onClick={() => setVoice(v.id)}
                    className={cn(
                      "text-left p-5 rounded-xl border-2 transition-all",
                      voice === v.id
                        ? "border-gold bg-accent-soft shadow-gold"
                        : "border-border hover:border-gold/40",
                    )}
                  >
                    <div className="font-serif text-lg font-semibold">{v.name}</div>
                    <div className="text-xs text-muted-foreground mt-1">{v.desc}</div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {tab === "phone" && (
            <div className="space-y-6">
              <h2 className="font-serif text-2xl font-semibold divider-gold">Telefon Ayarları</h2>
              <Field label="AI Numarası" defaultValue="+90 850 000 12 34" />
              <Field label="Yönlendirilecek Avukat Hattı" defaultValue="+90 532 555 00 00" />
              <div className="pt-4 flex justify-end gap-3">
                <Button variant="elite">Kaydet</Button>
              </div>
            </div>
          )}

          {tab === "integrations" && (
            <div className="space-y-4">
              <h2 className="font-serif text-2xl font-semibold divider-gold">Entegrasyonlar</h2>
              {[
                { name: "Google Calendar", status: "Bağlı" },
                { name: "Google Sheets", status: "Bağlı" },
                { name: "WhatsApp Business", status: "Bağlı Değil" },
                { name: "CRM", status: "Bağlı Değil" },
              ].map((i) => (
                <div
                  key={i.name}
                  className="flex items-center justify-between p-5 rounded-xl border border-border"
                >
                  <div className="font-medium">{i.name}</div>
                  <Button variant={i.status === "Bağlı" ? "outline" : "elite"} size="sm">
                    {i.status === "Bağlı" ? "Bağlantıyı Kes" : "Bağlan"}
                  </Button>
                </div>
              ))}
            </div>
          )}

          {tab === "notifications" && (
            <div className="space-y-4">
              <h2 className="font-serif text-2xl font-semibold divider-gold">Bildirimler</h2>
              {[
                "Yeni müvekkil adayı",
                "Kaçan çağrı",
                "Randevu oluşturuldu",
                "Günlük özet raporu",
              ].map((n) => (
                <label
                  key={n}
                  className="flex items-center justify-between p-5 rounded-xl border border-border"
                >
                  <span className="font-medium">{n}</span>
                  <input type="checkbox" defaultChecked className="h-5 w-5 accent-gold" />
                </label>
              ))}
            </div>
          )}
        </div>
      </div>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/settings")({
  component: Settings,
});

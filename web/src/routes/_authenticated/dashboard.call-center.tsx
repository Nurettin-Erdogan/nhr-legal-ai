import { createFileRoute } from "@tanstack/react-router";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import {
  PhoneIncoming,
  PhoneOutgoing,
  Phone,
  Mic,
  Sliders,
  BarChart3,
  Sparkles,
  CheckCircle2,
  PlayCircle,
  Plus,
  Settings as SettingsIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/components/AuthProvider";

type CallLog = {
  id: string;
  started_at: string;
  direction: string;
  phone: string;
  duration_sec: number;
  ai_summary: string | null;
  status: string;
};

const tabs = [
  { id: "inbound", label: "Inbound AI", icon: PhoneIncoming },
  { id: "outbound", label: "Outbound AI", icon: PhoneOutgoing },
  { id: "phone", label: "Telefon Bağlantısı", icon: Phone },
  { id: "voice", label: "Ses Ayarları", icon: Mic },
  { id: "prompt", label: "Prompt Ayarları", icon: Sliders },
  { id: "reports", label: "Çağrı Raporları", icon: BarChart3 },
];

const formatTime = (s: string) =>
  new Date(s).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
const formatDur = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

const CallCenter = () => {
  const { user } = useAuth();
  const [tab, setTab] = useState("inbound");
  const [logs, setLogs] = useState<CallLog[]>([]);

  useEffect(() => {
    if (!user) return;
    supabase
      .from("calls")
      .select("*")
      .order("started_at", { ascending: false })
      .limit(10)
      .then(({ data }) => setLogs((data as CallLog[]) || []));
  }, [user]);

  return (
    <DashboardLayout
      title="AI Call Center"
      subtitle="Inbound & Outbound AI · Türkçe doğal ses · 7/24 müvekkil iletişimi"
      actions={
        <>
          <Button variant="outline" size="sm">
            <PlayCircle className="h-4 w-4" />
            Test Araması
          </Button>
          <Button variant="elite" size="sm">
            <SettingsIcon className="h-4 w-4" />
            Yapılandır
          </Button>
        </>
      }
    >
      {/* KPI */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        {[
          { label: "Bugünkü Aramalar", value: "47", icon: Phone, sub: "+12% dün" },
          { label: "Inbound", value: "32", icon: PhoneIncoming, sub: "%94 doğru anlama" },
          { label: "Outbound", value: "15", icon: PhoneOutgoing, sub: "12 söz alındı" },
          { label: "Oluşturulan Randevu", value: "12", icon: CheckCircle2, sub: "Bugün" },
        ].map((s) => (
          <div
            key={s.label}
            className="p-4 rounded-xl bg-card border border-border shadow-card-elite"
          >
            <div className="flex items-center justify-between mb-2">
              <div className="h-8 w-8 rounded-lg bg-gradient-gold flex items-center justify-center">
                <s.icon className="h-4 w-4 text-primary" />
              </div>
            </div>
            <div className="font-serif text-2xl font-semibold">{s.value}</div>
            <div className="text-[11px] text-muted-foreground">{s.label}</div>
            <div className="text-[10px] mt-1 text-foreground/60">{s.sub}</div>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="rounded-2xl bg-card border border-border shadow-card-elite overflow-hidden mb-6">
        <div className="flex flex-wrap border-b border-border">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                "flex items-center gap-2 px-5 py-3.5 text-sm font-medium border-b-2 transition",
                tab === t.id
                  ? "border-gold text-gold-deep bg-gold/5"
                  : "border-transparent text-muted-foreground hover:text-foreground hover:bg-secondary/40",
              )}
            >
              <t.icon className="h-4 w-4" /> {t.label}
            </button>
          ))}
        </div>

        <div className="p-6 lg:p-8">
          {tab === "inbound" && <InboundPanel />}
          {tab === "outbound" && <OutboundPanel />}
          {tab === "phone" && <PhonePanel />}
          {tab === "voice" && <VoicePanel />}
          {tab === "prompt" && <PromptPanel />}
          {tab === "reports" && <ReportsPanel />}
        </div>
      </div>

      {/* Recent calls */}
      <div className="rounded-2xl bg-card border border-border shadow-card-elite overflow-hidden">
        <div className="p-6 border-b border-border">
          <h3 className="font-serif text-xl font-semibold">Son Çağrı Kayıtları</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground bg-secondary/40 uppercase tracking-wider">
                <th className="px-6 py-3 font-medium">Saat</th>
                <th className="px-6 py-3 font-medium">Yön</th>
                <th className="px-6 py-3 font-medium">Numara</th>
                <th className="px-6 py-3 font-medium">Süre</th>
                <th className="px-6 py-3 font-medium">Durum</th>
                <th className="px-6 py-3 font-medium text-right">Özet</th>
              </tr>
            </thead>
            <tbody>
              {logs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-sm text-muted-foreground">
                    Henüz çağrı yok
                  </td>
                </tr>
              ) : (
                logs.map((c) => (
                  <tr key={c.id} className="border-t border-border hover:bg-secondary/30">
                    <td className="px-6 py-3 font-mono text-xs text-muted-foreground">
                      {formatTime(c.started_at)}
                    </td>
                    <td className="px-6 py-3">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border",
                          c.direction === "inbound"
                            ? "bg-blue-500/10 text-blue-600 border-blue-500/20"
                            : "bg-gold/10 text-gold-deep border-gold/20",
                        )}
                      >
                        {c.direction === "inbound" ? (
                          <PhoneIncoming className="h-3 w-3" />
                        ) : (
                          <PhoneOutgoing className="h-3 w-3" />
                        )}
                        {c.direction === "inbound" ? "Gelen" : "Giden"}
                      </span>
                    </td>
                    <td className="px-6 py-3 font-mono text-xs">{c.phone}</td>
                    <td className="px-6 py-3 font-mono text-xs">{formatDur(c.duration_sec)}</td>
                    <td className="px-6 py-3 text-muted-foreground">{c.status}</td>
                    <td className="px-6 py-3 text-right text-xs text-muted-foreground max-w-xs truncate">
                      {c.ai_summary || "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </DashboardLayout>
  );
};

const FeatureToggle = ({
  name,
  desc,
  active = true,
}: {
  name: string;
  desc: string;
  active?: boolean;
}) => (
  <div className="flex items-start justify-between gap-4 p-4 rounded-xl bg-secondary/30 border border-border">
    <div>
      <div className="font-medium text-sm">{name}</div>
      <div className="text-xs text-muted-foreground mt-0.5">{desc}</div>
    </div>
    <label className="relative inline-flex items-center cursor-pointer shrink-0 mt-1">
      <input type="checkbox" defaultChecked={active} className="sr-only peer" />
      <div className="w-10 h-5 bg-secondary peer-checked:bg-gradient-gold rounded-full transition relative after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:bg-card after:rounded-full after:h-4 after:w-4 after:transition peer-checked:after:translate-x-5" />
    </label>
  </div>
);

const InboundPanel = () => (
  <div>
    <h3 className="font-serif text-xl font-semibold mb-1">Inbound AI — Gelen Aramalar</h3>
    <p className="text-sm text-muted-foreground mb-6">
      Müvekkilleriniz aradığında AI asistanınız Türkçe karşılar, gerekli işlemi yapar.
    </p>
    <div className="grid md:grid-cols-2 gap-3">
      <FeatureToggle name="Gelen aramaları karşıla" desc="7/24 doğal Türkçe karşılama" />
      <FeatureToggle name="Müvekkil bilgisi topla" desc="Ad, telefon, konu otomatik kayıt" />
      <FeatureToggle name="Randevu oluştur" desc="Müsait saatlere göre" />
      <FeatureToggle name="Dosya sorgulama" desc="Müvekkile dosya durumu bildir" />
      <FeatureToggle name="Avukat dönüş talebi" desc="Önemli aramaları işaretle" />
      <FeatureToggle name="WhatsApp özet gönder" desc="Görüşme sonrası özet" active={false} />
    </div>
  </div>
);

const OutboundPanel = () => (
  <div>
    <h3 className="font-serif text-xl font-semibold mb-1">Outbound AI — Otomatik Hatırlatmalar</h3>
    <p className="text-sm text-muted-foreground mb-6">
      AI asistanınız müvekkillerinizi planlanan zamanda arar ve hatırlatma yapar.
    </p>
    <div className="grid md:grid-cols-2 gap-3">
      <FeatureToggle name="Randevu hatırlatma" desc="Randevudan 1 gün önce" />
      <FeatureToggle name="Duruşma hatırlatma" desc="Duruşmadan 2 gün önce" />
      <FeatureToggle name="Evrak hatırlatma" desc="Eksik evrak bildirimi" />
      <FeatureToggle name="Ödeme hatırlatma" desc="Vade tarihinde otomatik" />
      <FeatureToggle name="Geri arama takibi" desc="Cevapsız aramalar için" />
      <FeatureToggle name="Anket / Memnuniyet" desc="Görüşme sonrası" active={false} />
    </div>
  </div>
);

const PhonePanel = () => (
  <div>
    <h3 className="font-serif text-xl font-semibold mb-1">Telefon Bağlantısı</h3>
    <p className="text-sm text-muted-foreground mb-6">
      Mevcut numaranızı yönlendirin veya yeni AI numarası alın.
    </p>
    <div className="grid md:grid-cols-3 gap-4">
      {[
        {
          title: "Mevcut Numarayı Yönlendir",
          desc: "Sabit/cep hattınızı AI'ya yönlendirin",
          btn: "Yönlendirme Talimatları",
        },
        {
          title: "Yeni AI Numarası",
          desc: "Size özel 0212/0850 numarası tahsis edelim",
          btn: "Numara Al",
        },
        {
          title: "SIP Trunk Bağlantısı",
          desc: "Kurumsal SIP altyapınıza bağlayın",
          btn: "SIP Yapılandır",
        },
      ].map((c) => (
        <div
          key={c.title}
          className="p-5 rounded-xl border border-border bg-secondary/30 hover:border-gold/40 transition"
        >
          <Phone className="h-7 w-7 text-gold mb-3" />
          <h4 className="font-semibold mb-1">{c.title}</h4>
          <p className="text-xs text-muted-foreground mb-4">{c.desc}</p>
          <Button variant="outline" size="sm" className="w-full">
            <Plus className="h-3.5 w-3.5" />
            {c.btn}
          </Button>
        </div>
      ))}
    </div>
    <div className="mt-6 p-4 rounded-xl bg-success/5 border border-success/20 text-sm">
      <span className="font-semibold text-success">Aktif numara:</span> +90 (212) 555 0 123 —
      Inbound AI etkin
    </div>
  </div>
);

const VoicePanel = () => (
  <div>
    <h3 className="font-serif text-xl font-semibold mb-1">Ses & Konuşma Tarzı</h3>
    <p className="text-sm text-muted-foreground mb-6">
      Müvekkillerinize hangi sesle ve nasıl hitap edilsin?
    </p>
    <div className="grid md:grid-cols-2 gap-6">
      <div>
        <div className="text-xs uppercase tracking-wider text-muted-foreground font-semibold mb-3">
          Ses
        </div>
        <div className="grid grid-cols-2 gap-2">
          {["Selma — Doğal", "Defne — Sıcak", "Atlas — Resmi", "İris — Premium"].map((v, i) => (
            <button
              key={v}
              className={cn(
                "p-4 rounded-xl border text-left transition",
                i === 2 ? "border-gold bg-gold/5" : "border-border hover:border-gold/40",
              )}
            >
              <Mic
                className={cn("h-4 w-4 mb-2", i === 2 ? "text-gold" : "text-muted-foreground")}
              />
              <div className="text-sm font-medium">{v}</div>
              <button className="text-xs text-gold-deep mt-1 underline-offset-2 hover:underline">
                Önizle
              </button>
            </button>
          ))}
        </div>
      </div>
      <div>
        <div className="text-xs uppercase tracking-wider text-muted-foreground font-semibold mb-3">
          Tarz
        </div>
        <div className="flex flex-wrap gap-2">
          {["Resmi", "Doğal", "Sıcak", "Premium", "Kısa ve net"].map((t, i) => (
            <button
              key={t}
              className={cn(
                "px-4 py-2 rounded-full text-sm border transition",
                i === 0
                  ? "border-gold bg-gold text-primary font-medium"
                  : "border-border hover:border-gold/40",
              )}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="mt-6">
          <div className="text-xs uppercase tracking-wider text-muted-foreground font-semibold mb-2">
            Karşılama Cümlesi
          </div>
          <textarea
            rows={3}
            defaultValue="Merhaba, Korkmaz Hukuk Bürosu'na hoş geldiniz. Ben dijital asistanınız Selma. Size nasıl yardımcı olabilirim?"
            className="w-full px-3 py-2 rounded-lg bg-secondary/40 border border-transparent focus:border-gold/40 focus:bg-background outline-none text-sm"
          />
        </div>
      </div>
    </div>
  </div>
);

const PromptPanel = () => (
  <div>
    <h3 className="font-serif text-xl font-semibold mb-1">Prompt Ayarları</h3>
    <p className="text-sm text-muted-foreground mb-6">
      AI asistanınızın davranış kurallarını belirleyin.
    </p>
    <div className="space-y-4">
      {[
        {
          label: "Sistem Talimatı",
          val: "Sen Korkmaz Hukuk Bürosu'nun resmi telefon asistanısın. Müvekkillere saygılı, profesyonel ve net cevaplar ver. Hukuki tavsiye verme; yalnızca randevu, dosya durumu ve genel bilgi sağla.",
        },
        {
          label: "Yasaklı Konular",
          val: "Hukuki tavsiye, dava sonucu tahmini, ücret garantisi, davaya kabul taahhüdü.",
        },
        {
          label: "Aktarma Tetikleyicileri",
          val: "Acil dava, mahkeme öncesi son gün, basın açıklaması, mevcut müvekkil VIP.",
        },
      ].map((p) => (
        <div key={p.label}>
          <label className="text-xs uppercase tracking-wider text-muted-foreground font-semibold mb-2 block">
            {p.label}
          </label>
          <textarea
            rows={3}
            defaultValue={p.val}
            className="w-full px-3 py-2 rounded-lg bg-secondary/40 border border-transparent focus:border-gold/40 focus:bg-background outline-none text-sm font-mono"
          />
        </div>
      ))}
      <Button variant="elite">
        <Sparkles className="h-4 w-4" />
        AI ile İyileştir
      </Button>
    </div>
  </div>
);

const ReportsPanel = () => (
  <div>
    <h3 className="font-serif text-xl font-semibold mb-1">Çağrı Raporları</h3>
    <p className="text-sm text-muted-foreground mb-6">
      Performans metrikleri ve dönüşüm analizleri.
    </p>
    <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
      {[
        { l: "Toplam Çağrı (Ay)", v: "1.247" },
        { l: "Ortalama Süre", v: "2:41" },
        { l: "Lead Dönüşüm", v: "%34" },
        { l: "Doğru Anlama", v: "%94" },
      ].map((s) => (
        <div key={s.l} className="p-4 rounded-xl bg-secondary/40 border border-border">
          <div className="text-xs text-muted-foreground mb-1">{s.l}</div>
          <div className="font-serif text-2xl font-semibold">{s.v}</div>
        </div>
      ))}
    </div>
    <div className="mt-6 p-5 rounded-xl bg-gradient-hero text-primary-foreground">
      <BarChart3 className="h-7 w-7 text-gold mb-2" />
      <div className="font-serif text-lg font-semibold">
        Detaylı haftalık rapor mailinize gönderildi
      </div>
      <p className="text-sm text-primary-foreground/70 mt-1">
        Pazartesi 09:00 — selim@korkmaz.av.tr
      </p>
    </div>
  </div>
);

export const Route = createFileRoute("/_authenticated/dashboard/call-center")({
  component: CallCenter,
});

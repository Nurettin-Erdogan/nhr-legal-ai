import { useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { submitApplication } from "@/lib/office-api";
import { PRIVACY_NOTICE_VERSION } from "@/lib/legal";
import { toast } from "sonner";
import { ArrowLeft, CheckCircle2, Loader2 } from "lucide-react";

export const HUKUK_ALANLARI = [
  "İş Hukuku",
  "Aile Hukuku",
  "Ceza Hukuku",
  "Borçlar / Kira",
  "İcra & İflas",
  "Ticaret Hukuku",
  "Miras Hukuku",
  "Tüketici Hukuku",
  "Diğer",
];

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Sohbet geçmişinden otomatik özet */
  sohbetOzeti?: string;
}

export const BasvuruDialog = ({ open, onOpenChange, sohbetOzeti }: Props) => {
  const [step, setStep] = useState(1);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);
  const [consent, setConsent] = useState(false);
  const [form, setForm] = useState({
    hukuk_alani: "",
    konu: "",
    ad_soyad: "",
    telefon: "",
    eposta: "",
  });

  const set = (k: keyof typeof form, v: string) => setForm((p) => ({ ...p, [k]: v }));

  const reset = () => {
    setStep(1);
    setDone(false);
    setConsent(false);
    setForm({ hukuk_alani: "", konu: "", ad_soyad: "", telefon: "", eposta: "" });
  };

  const close = (v: boolean) => {
    onOpenChange(v);
    if (!v) setTimeout(reset, 200);
  };

  const submit = async () => {
    if (!form.ad_soyad.trim()) return toast.error("Ad soyad gereklidir");
    if (!form.telefon.trim() && !form.eposta.trim())
      return toast.error("Telefon veya e-posta girin");
    if (!consent) return toast.error("Aydınlatma metnini okuduğunuzu onaylayın");
    setSaving(true);
    let error: Error | null = null;
    try {
      await submitApplication({
        ad_soyad: form.ad_soyad.trim(),
        telefon: form.telefon.trim() || null,
        eposta: form.eposta.trim() || null,
        hukuk_alani: form.hukuk_alani || null,
        konu: form.konu.trim(),
        sohbet_ozeti: sohbetOzeti?.slice(0, 8000) || null,
        aydinlatma_okundu: true,
        aydinlatma_surum: PRIVACY_NOTICE_VERSION,
      });
    } catch (e) {
      error = e instanceof Error ? e : new Error("Gönderilemedi");
    }
    setSaving(false);
    if (error) {
      toast.error("Başvuru gönderilemedi, lütfen tekrar deneyin");
      return;
    }
    setDone(true);
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold">
            {done ? "Başvurunuz alındı" : "Başvuru Formu"}
          </DialogTitle>
        </DialogHeader>

        {done ? (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <CheckCircle2 className="h-12 w-12 text-primary" />
            <p className="text-sm text-muted-foreground">
              Avukatlarımız başvurunuzu inceleyip en kısa sürede size dönecek.
            </p>
            <Button className="mt-2 w-full rounded-full" onClick={() => close(false)}>
              Kapat
            </Button>
          </div>
        ) : step === 1 ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Hukuk alanı</Label>
              <Select value={form.hukuk_alani} onValueChange={(v) => set("hukuk_alani", v)}>
                <SelectTrigger>
                  <SelectValue placeholder="Seçin" />
                </SelectTrigger>
                <SelectContent>
                  {HUKUK_ALANLARI.map((a) => (
                    <SelectItem key={a} value={a}>
                      {a}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Konunuzu kısaca anlatın</Label>
              <Textarea
                rows={4}
                value={form.konu}
                onChange={(e) => set("konu", e.target.value)}
                placeholder="Örn: 3 yıl çalıştığım iş yerinden tazminatsız çıkarıldım..."
                className="resize-none"
              />
            </div>
            <Button
              className="w-full rounded-full"
              disabled={!form.konu.trim()}
              onClick={() => setStep(2)}
            >
              Devam →
            </Button>
            <p className="text-center text-[11px] text-muted-foreground">
              Bilgileriniz yalnızca başvurunuzu değerlendirmek için kullanılır.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Ad soyad</Label>
              <Input value={form.ad_soyad} onChange={(e) => set("ad_soyad", e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Telefon</Label>
              <Input
                value={form.telefon}
                onChange={(e) => set("telefon", e.target.value)}
                placeholder="05xx xxx xx xx"
                inputMode="tel"
              />
            </div>
            <div className="space-y-2">
              <Label>E-posta</Label>
              <Input
                type="email"
                value={form.eposta}
                onChange={(e) => set("eposta", e.target.value)}
              />
            </div>
            <label className="flex items-start gap-2 text-xs leading-relaxed text-muted-foreground">
              <input type="checkbox" className="mt-0.5" checked={consent} onChange={(event) => setConsent(event.target.checked)} data-testid="kvkk-consent" />
              <span>
                <a href="/gizlilik" target="_blank" rel="noreferrer" className="underline">
                  KVKK aydınlatma metnini
                </a>{" "}
                okudum; bilgilerimin başvurumu değerlendirmek için işlenmesini anladım.
              </span>
            </label>
            <div className="flex gap-2">
              <Button variant="outline" className="rounded-full" onClick={() => setStep(1)}>
                <ArrowLeft className="h-4 w-4" />
              </Button>
              <Button className="flex-1 rounded-full" disabled={saving || !consent} onClick={submit}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Başvuruyu Gönder"}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};

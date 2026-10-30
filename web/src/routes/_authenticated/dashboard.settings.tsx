import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { IntegrationSettings } from "@/components/IntegrationSettings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/components/AuthContext";
import { db } from "@/lib/db";
import { beginGoogleLogin, googleAccountLinked, googleLoginAvailable } from "@/lib/auth-api";
import { downloadMyData } from "@/lib/account-data";
import { AccountDeletion, AccountProfile } from "@/components/AccountSettings";
import { useAccountSecurity } from "@/components/account-security";

type CallPreferences = {
  greeting: string;
  business_hours_start: string;
  business_hours_end: string;
  voicemail_enabled: boolean;
  ai_summary_enabled: boolean;
};

const defaults: CallPreferences = {
  greeting: "",
  business_hours_start: "09:00",
  business_hours_end: "18:00",
  voicemail_enabled: false,
  ai_summary_enabled: false,
};

function DataRights() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  const run = async () => {
    setBusy(true);
    setMessage("");
    setFailed(false);
    try {
      setMessage(await downloadMyData());
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : "Veriler indirilemedi.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section
      className="space-y-3 rounded-xl border border-border bg-card p-6"
      data-testid="data-rights"
    >
      <h2 className="text-xl font-semibold">Verilerim (KVKK)</h2>
      <p>
        Hesabınızdaki müvekkil, dava, görev, takvim, belge üst verileri, yapay zekâ çıktıları ve
        sohbet geçmişinizi JSON dosyası olarak indirebilirsiniz. Parola ve bağlantı anahtarları
        güvenlik nedeniyle dahil edilmez; belge dosyalarının kendisi Dosyalar sayfasından tek tek
        indirilir. Verileriniz yerel sunucumuzda tutulur, yapay zekâ modeli eğitiminde kullanılmaz.
      </p>
      <Button type="button" variant="outline" onClick={() => void run()} disabled={busy}>
        {busy ? "Hazırlanıyor…" : "Verilerimi indir (JSON)"}
      </Button>
      {message && (
        <p
          role={failed ? "alert" : "status"}
          className={failed ? "text-destructive" : "text-emerald-700"}
        >
          {message}
        </p>
      )}
    </section>
  );
}

const Settings = () => {
  const { user } = useAuth();
  const userId = user?.id;
  const security = useAccountSecurity();
  const [values, setValues] = useState<CallPreferences>(defaults);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [loadFailed, setLoadFailed] = useState(false);
  const [notice, setNotice] = useState("");
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [googleAvailable, setGoogleAvailable] = useState(false);
  const [googleLinked, setGoogleLinked] = useState(false);
  const [googleLoadedFor, setGoogleLoadedFor] = useState<string | null>(null);

  useEffect(() => {
    if (!userId) {
      setGoogleLoadedFor(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const available = await googleLoginAvailable();
        const linked = available ? await googleAccountLinked() : false;
        if (!cancelled) {
          setGoogleAvailable(available);
          setGoogleLinked(linked);
          setGoogleLoadedFor(userId);
        }
      } catch {
        if (!cancelled) {
          setGoogleAvailable(false);
          setGoogleLinked(false);
          setGoogleLoadedFor(userId);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  useEffect(() => {
    if (!userId) {
      setLoading(false);
      setLoadedFor(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    setLoadFailed(false);
    setNotice("");
    void (async () => {
      const { data, error: loadError } = await db
        .from("call_settings")
        .select(
          "greeting,business_hours_start,business_hours_end,voicemail_enabled,ai_summary_enabled",
        )
        .maybeSingle();
      if (cancelled) return;
      if (loadError) {
        setValues(defaults);
        setError(loadError.message);
        setLoadFailed(true);
      } else if (data) {
        const saved = data as CallPreferences;
        setValues({
          greeting: saved.greeting ?? "",
          business_hours_start: saved.business_hours_start?.slice(0, 5) ?? "09:00",
          business_hours_end: saved.business_hours_end?.slice(0, 5) ?? "18:00",
          voicemail_enabled: saved.voicemail_enabled ?? false,
          ai_summary_enabled: saved.ai_summary_enabled ?? false,
        });
      } else setValues(defaults);
      setLoadedFor(userId);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  const save = async () => {
    setNotice("");
    setError("");
    if (!userId || loadedFor !== userId) return setError("Tercihler yüklenmedi.");
    if (loadFailed) return setError("Tercihler yüklenemedi; sayfayı yenileyin.");
    if (
      !/^\d{2}:\d{2}$/.test(values.business_hours_start) ||
      !/^\d{2}:\d{2}$/.test(values.business_hours_end) ||
      values.business_hours_start >= values.business_hours_end
    ) {
      return setError("Bitiş saati başlangıç saatinden sonra olmalı.");
    }
    setSaving(true);
    try {
      const { error: saveError } = await db
        .from("call_settings")
        .upsert(values, { onConflict: "owner_id" });
      if (saveError) throw new Error(saveError.message);
      setNotice("Tercihler kaydedildi. Telefon hizmeti bağlı olmadığı için arama başlatılmaz.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Tercihler kaydedilemedi.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <DashboardLayout title="Ayarlar" subtitle="Hesabınız, verileriniz ve büro tercihleri">
      <div className="max-w-3xl space-y-6">
        <AccountProfile security={security} />
        <DataRights />
        <IntegrationSettings />
        <section className="space-y-5 rounded-xl border border-border bg-card p-6">
          <h2 className="text-xl font-semibold">Çağrı tercihleri</h2>
          <p
            role="status"
            className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm"
          >
            Telefon hattı, sesli AI, Google Takvim, WhatsApp ve ödeme sağlayıcısı bu kurulumda bağlı
            değil. Aşağıdaki tercihler veritabanına kaydedilir; tek başına arama veya bildirim
            göndermez.
          </p>
          {!userId ? (
            <p>Tercihler için oturum açın.</p>
          ) : loading || loadedFor !== userId ? (
            <p>Tercihler yükleniyor…</p>
          ) : (
            <>
              <label className="block space-y-2">
                <span>Karşılama metni</span>
                <Textarea
                  value={values.greeting}
                  maxLength={2000}
                  onChange={(event) => setValues({ ...values, greeting: event.target.value })}
                />
              </label>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block space-y-2">
                  <span>Çalışma başlangıcı</span>
                  <Input
                    type="time"
                    value={values.business_hours_start}
                    onChange={(event) =>
                      setValues({ ...values, business_hours_start: event.target.value })
                    }
                  />
                </label>
                <label className="block space-y-2">
                  <span>Çalışma bitişi</span>
                  <Input
                    type="time"
                    value={values.business_hours_end}
                    onChange={(event) =>
                      setValues({ ...values, business_hours_end: event.target.value })
                    }
                  />
                </label>
              </div>
              <label className="flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={values.voicemail_enabled}
                  onChange={(event) =>
                    setValues({ ...values, voicemail_enabled: event.target.checked })
                  }
                />
                Sesli mesaj tercihi
              </label>
              <label className="flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={values.ai_summary_enabled}
                  onChange={(event) =>
                    setValues({ ...values, ai_summary_enabled: event.target.checked })
                  }
                />
                Çağrı özeti tercihi
              </label>
              {error && (
                <p role="alert" className="text-destructive">
                  {error}
                </p>
              )}
              {notice && (
                <p role="status" className="text-emerald-700">
                  {notice}
                </p>
              )}
              <Button onClick={() => void save()} disabled={saving || loadFailed}>
                {saving ? "Kaydediliyor…" : "Tercihleri kaydet"}
              </Button>
            </>
          )}
        </section>
        <section className="space-y-3 rounded-xl border border-border bg-card p-6">
          <h2 className="text-xl font-semibold">Google hesabı</h2>
          {!userId || googleLoadedFor !== userId ? (
            <p>Bağlantı durumu yükleniyor…</p>
          ) : googleLinked ? (
            <p>Google hesabı bu oturuma bağlı. Google ile giriş yapabilirsiniz.</p>
          ) : googleAvailable ? (
            <>
              <p>Mevcut hesabınızı doğrulanmış, aynı e-postalı Google hesabınıza bağlayın.</p>
              <Button type="button" variant="outline" onClick={() => beginGoogleLogin(true)}>
                Google hesabını bağla
              </Button>
            </>
          ) : (
            <p>Google girişi bu ortamda henüz yapılandırılmadı.</p>
          )}
        </section>
        <AccountDeletion security={security} />
      </div>
    </DashboardLayout>
  );
};

export const Route = createFileRoute("/_authenticated/dashboard/settings")({
  component: Settings,
});

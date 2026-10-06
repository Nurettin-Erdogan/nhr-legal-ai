import { createFileRoute, Outlet, useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "@/lib/router-compat";
import { beginGoogleLogin, googleLoginAvailable, login, register, requestPasswordReset } from "@/lib/auth-api";
import { authErrorMessage, MIN_PASSWORD_LENGTH } from "@/lib/account-forms";
import { TERMS_VERSION } from "@/lib/legal";
import { useAuth } from "@/components/AuthProvider";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { ArrowLeft, Eye, EyeOff, Loader2 } from "lucide-react";

type Mode = "login" | "signup" | "forgot";

const statusOf = (error: unknown): number | undefined =>
  error instanceof Error && "status" in error && typeof error.status === "number" ? error.status : undefined;

function AuthPage() {
  const { user, loading: authLoading, refreshAuth } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("login");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [showPass, setShowPass] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [googleAvailable, setGoogleAvailable] = useState(false);

  useEffect(() => {
    void googleLoginAvailable()
      .then(setGoogleAvailable)
      .catch(() => setGoogleAvailable(false));
  }, []);

  useEffect(() => {
    if (!authLoading && user) navigate("/dashboard");
  }, [user, authLoading, navigate]);

  const switchMode = (next: Mode) => {
    setMode(next);
    setError(null);
    setNotice(null);
    setPassword2("");
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setNotice(null);

    const mail = email.trim().toLowerCase();
    if (!mail.includes("@") || mail.length < 5) return setError("Geçerli bir e-posta adresi girin.");

    if (mode === "forgot") {
      setBusy(true);
      try {
        const result = await requestPasswordReset(mail);
        setNotice(
          result.delivery === "email"
            ? "Bu e-postayla kayıtlı bir hesap varsa, şifre sıfırlama bağlantısı gönderildi. Bağlantı 60 dakika geçerlidir; gelen kutunuzu ve gereksiz klasörünü kontrol edin."
            : "Bu kurulumda e-posta gönderimi yapılandırılmadığı için bağlantı e-postayla gönderilemiyor. Sıfırlama bağlantısı için sistem yöneticinize başvurun.",
        );
      } catch (err) {
        setError(authErrorMessage(err instanceof Error ? err.message : "İstek gönderilemedi.", statusOf(err)));
      } finally {
        setBusy(false);
      }
      return;
    }

    if (mode === "signup") {
      if (!firstName.trim()) return setError("Adınızı girin.");
      if (password.length < MIN_PASSWORD_LENGTH) return setError(`Şifre en az ${MIN_PASSWORD_LENGTH} karakter olmalı.`);
      if (password !== password2) return setError("Şifreler birbiriyle aynı değil.");
      if (!accepted) return setError("Devam etmek için Kullanım Şartları'nı ve Gizlilik Politikası'nı kabul etmelisiniz.");
    }

    setBusy(true);
    try {
      if (mode === "login") {
        await login(mail, password);
        await refreshAuth();
      } else {
        await register(mail, password, `${firstName.trim()} ${lastName.trim()}`.trim(), TERMS_VERSION);
        await refreshAuth();
        toast.success("Kaydınız tamamlandı, hoş geldiniz.");
      }
      navigate("/dashboard");
    } catch (err) {
      setError(authErrorMessage(err instanceof Error ? err.message : "Oturum işlemi başarısız oldu.", statusOf(err)));
    } finally {
      setBusy(false);
    }
  };

  const title = mode === "login" ? "Avukat Paneli" : mode === "signup" ? "Ücretsiz hesap oluşturun" : "Şifrenizi mi unuttunuz?";
  const subtitle =
    mode === "login"
      ? "Hesabınıza giriş yapın"
      : mode === "signup"
        ? "Ad, e-posta ve şifre ile 30 saniyede kayıt olun"
        : "Hesabınızın e-posta adresini yazın; şifre sıfırlama bağlantısı gönderelim.";

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-10">
      <Link to="/" className="mb-8">
        <Logo />
      </Link>

      <div className="w-full max-w-sm rounded-2xl border border-border bg-card p-7 shadow-card-elite">
        <h1 className="text-xl font-bold tracking-tight">{title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>

        {error && (
          <div role="alert" className="mt-5 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm text-destructive">
            {error}
          </div>
        )}
        {notice && (
          <div role="status" className="mt-5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2.5 text-sm">
            {notice}
          </div>
        )}

        <form onSubmit={submit} className="mt-6 space-y-4">
          {mode === "signup" && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="first-name">Ad</Label>
                <Input id="first-name" autoComplete="given-name" value={firstName} onChange={(e) => setFirstName(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="last-name">Soyad</Label>
                <Input id="last-name" autoComplete="family-name" value={lastName} onChange={(e) => setLastName(e.target.value)} />
              </div>
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="email">E-posta</Label>
            <Input
              id="email"
              type="email"
              required
              inputMode="email"
              autoCapitalize="none"
              autoComplete="email"
              placeholder="ornek@buro.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          {mode !== "forgot" && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="password">Şifre</Label>
                {mode === "login" && (
                  <button type="button" className="text-xs font-medium text-primary hover:underline" onClick={() => switchMode("forgot")}>
                    Şifremi unuttum
                  </button>
                )}
              </div>
              <div className="relative">
                <Input
                  id="password"
                  type={showPass ? "text" : "password"}
                  required
                  minLength={mode === "signup" ? MIN_PASSWORD_LENGTH : 1}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="pr-10"
                />
                <button
                  type="button"
                  aria-label={showPass ? "Şifreyi gizle" : "Şifreyi göster"}
                  onClick={() => setShowPass((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  {showPass ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              {mode === "signup" && <p className="text-xs text-muted-foreground">En az {MIN_PASSWORD_LENGTH} karakter olmalı.</p>}
            </div>
          )}

          {mode === "signup" && (
            <>
              <div className="space-y-2">
                <Label htmlFor="password2">Şifre (tekrar)</Label>
                <Input
                  id="password2"
                  type={showPass ? "text" : "password"}
                  required
                  minLength={MIN_PASSWORD_LENGTH}
                  autoComplete="new-password"
                  value={password2}
                  onChange={(e) => setPassword2(e.target.value)}
                />
              </div>
              <label className="flex items-start gap-2 text-xs leading-relaxed text-muted-foreground">
                <input
                  type="checkbox"
                  id="accept-terms"
                  className="mt-0.5 h-4 w-4 shrink-0"
                  checked={accepted}
                  onChange={(e) => setAccepted(e.target.checked)}
                />
                <span>
                  <a href="/kullanim-sartlari" target="_blank" rel="noreferrer" className="font-medium text-primary underline">
                    Kullanım Şartları
                  </a>
                  'nı ve{" "}
                  <a href="/gizlilik" target="_blank" rel="noreferrer" className="font-medium text-primary underline">
                    Gizlilik Politikası / KVKK Aydınlatma Metni
                  </a>
                  'ni okudum, kabul ediyorum.
                </span>
              </label>
            </>
          )}

          <Button type="submit" className="w-full rounded-full" disabled={busy}>
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : mode === "login" ? (
              "Giriş Yap"
            ) : mode === "signup" ? (
              "Hesap Oluştur"
            ) : (
              "Sıfırlama bağlantısı gönder"
            )}
          </Button>
        </form>

        {mode !== "forgot" && (
          <>
            <div className="my-5 flex items-center gap-3 text-[11px] uppercase tracking-widest text-muted-foreground">
              <span className="h-px flex-1 bg-border" /> veya <span className="h-px flex-1 bg-border" />
            </div>

            <Button
              variant="outline"
              className="w-full rounded-full"
              type="button"
              disabled={!googleAvailable || busy}
              title={googleAvailable ? undefined : "Google OAuth yapılandırması henüz tamamlanmadı"}
              onClick={() => beginGoogleLogin(false, TERMS_VERSION)}
            >
              Google ile devam et
            </Button>
            {googleAvailable ? (
              <p className="mt-2 text-center text-[11px] text-muted-foreground">
                Google ile ilk kez devam ederseniz{" "}
                <a href="/kullanim-sartlari" target="_blank" rel="noreferrer" className="underline">
                  Kullanım Şartları
                </a>
                'nı ve{" "}
                <a href="/gizlilik" target="_blank" rel="noreferrer" className="underline">
                  Gizlilik Politikası
                </a>
                'nı kabul etmiş olursunuz.
              </p>
            ) : (
              <p className="mt-2 text-center text-xs text-muted-foreground">Google girişi bu ortamda henüz yapılandırılmadı.</p>
            )}
          </>
        )}

        <p className="mt-6 text-center text-sm text-muted-foreground">
          {mode === "login" ? "Hesabınız yok mu? " : mode === "signup" ? "Zaten hesabınız var mı? " : "Şifrenizi hatırladınız mı? "}
          <button
            type="button"
            className="font-medium text-primary hover:underline"
            onClick={() => switchMode(mode === "login" ? "signup" : "login")}
          >
            {mode === "login" ? "Kayıt olun" : "Giriş yapın"}
          </button>
        </p>
      </div>

      <Link to="/" className="mt-6 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> Ana sayfaya dön
      </Link>
    </div>
  );
}

/**
 * `/auth/callback` bu rotanın alt rotasıdır. Giriş formu `<Outlet>` çizmediği için Google dönüş sayfası hiç görünmüyor, Google'ın
 * döndürdüğü hata ("bu e-postayla hesap var" vb.) kullanıcıya gösterilmiyordu. Alt rotada form yerine alt sayfa çizilir.
 */
function AuthRoute() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  return pathname.replace(/\/+$/, "") === "/auth" ? <AuthPage /> : <Outlet />;
}

export const Route = createFileRoute("/auth")({
  head: () => ({
    meta: [
      { title: "Avukat Girişi ve Kayıt — JurisAI" },
      {
        name: "description",
        content: "JurisAI avukat paneline ücretsiz kayıt olun veya giriş yapın; başvuruları, dosyaları ve AI araçlarını yönetin.",
      },
      { property: "og:title", content: "Avukat Girişi ve Kayıt — JurisAI" },
      { property: "og:description", content: "Ücretsiz kayıt olun veya avukat panelinize giriş yapın." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: AuthRoute,
});

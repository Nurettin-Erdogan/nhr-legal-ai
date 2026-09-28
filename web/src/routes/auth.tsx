import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "@/lib/router-compat";
import { beginGoogleLogin, googleLoginAvailable, login, register } from "@/lib/auth-api";
import { useAuth } from "@/components/AuthProvider";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { ArrowLeft, Eye, EyeOff, Loader2 } from "lucide-react";

function trError(message: string): string {
  const m = message.toLowerCase();
  if (
    m.includes("already registered") ||
    m.includes("already exists") ||
    m.includes("user already")
  )
    return "Bu e-posta ile zaten bir hesap var. Giriş yapmayı deneyin.";
  if (m.includes("invalid login")) return "E-posta veya şifre hatalı.";
  if (m.includes("password") || m.includes("parola")) return "Şifre en az 10 karakter olmalı.";
  if (m.includes("weak") || m.includes("pwned"))
    return "Şifre çok zayıf, daha güçlü bir şifre seçin.";
  if (m.includes("invalid email") || m.includes("email address"))
    return "Geçerli bir e-posta adresi girin.";
  if (m.includes("rate limit") || m.includes("too many"))
    return "Çok fazla deneme yapıldı, birkaç dakika sonra tekrar deneyin.";
  if (m.includes("email not confirmed"))
    return "E-postanız doğrulanmamış. Gelen kutunuzu kontrol edin.";
  return message;
}

function AuthPage() {
  const { user, loading: authLoading, refreshAuth } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [googleAvailable, setGoogleAvailable] = useState(false);

  useEffect(() => {
    void googleLoginAvailable()
      .then(setGoogleAvailable)
      .catch(() => setGoogleAvailable(false));
  }, []);

  useEffect(() => {
    if (!authLoading && user) navigate("/dashboard");
  }, [user, authLoading, navigate]);

  const switchMode = (next: "login" | "signup") => {
    setMode(next);
    setError(null);
    setPassword2("");
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setError(null);

    const mail = email.trim().toLowerCase();
    if (!mail.includes("@") || mail.length < 5)
      return setError("Geçerli bir e-posta adresi girin.");
    if (mode === "signup" && password.length < 10)
      return setError("Şifre en az 10 karakter olmalı.");

    if (mode === "signup") {
      if (!firstName.trim()) return setError("Adınızı girin.");
      if (password !== password2) return setError("Şifreler birbiriyle aynı değil.");
    }

    setBusy(true);

    try {
      if (mode === "login") {
        await login(mail, password);
        await refreshAuth();
      } else {
        await register(mail, password, `${firstName.trim()} ${lastName.trim()}`.trim());
        await refreshAuth();
        toast.success("Kaydınız tamamlandı, hoş geldiniz.");
      }
      navigate("/dashboard");
    } catch (err) {
      setError(trError(err instanceof Error ? err.message : "Oturum işlemi başarısız oldu."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-10">
      <Link to="/" className="mb-8">
        <Logo />
      </Link>

      <div className="w-full max-w-sm rounded-2xl border border-border bg-card p-7 shadow-card-elite">
        <h1 className="text-xl font-bold tracking-tight">
          {mode === "login" ? "Avukat Paneli" : "Ücretsiz hesap oluşturun"}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {mode === "login"
            ? "Hesabınıza giriş yapın"
            : "Ad, e-posta ve şifre ile 30 saniyede kayıt olun"}
        </p>

        {error && (
          <div className="mt-5 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm text-destructive">
            {error}
          </div>
        )}

        <form onSubmit={submit} className="mt-6 space-y-4">
          {mode === "signup" && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="first-name">Ad</Label>
                <Input
                  id="first-name"
                  autoComplete="given-name"
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="last-name">Soyad</Label>
                <Input
                  id="last-name"
                  autoComplete="family-name"
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                />
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

          <div className="space-y-2">
            <Label htmlFor="password">Şifre</Label>
            <div className="relative">
              <Input
                id="password"
                type={showPass ? "text" : "password"}
                required
                minLength={mode === "signup" ? 10 : 1}
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
            {mode === "signup" && (
              <p className="text-xs text-muted-foreground">En az 10 karakter olmalı.</p>
            )}
          </div>

          {mode === "signup" && (
            <div className="space-y-2">
              <Label htmlFor="password2">Şifre (tekrar)</Label>
              <Input
                id="password2"
                type={showPass ? "text" : "password"}
                required
                minLength={10}
                autoComplete="new-password"
                value={password2}
                onChange={(e) => setPassword2(e.target.value)}
              />
            </div>
          )}

          <Button type="submit" className="w-full rounded-full" disabled={busy}>
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : mode === "login" ? (
              "Giriş Yap"
            ) : (
              "Hesap Oluştur"
            )}
          </Button>
        </form>

        <div className="my-5 flex items-center gap-3 text-[11px] uppercase tracking-widest text-muted-foreground">
          <span className="h-px flex-1 bg-border" /> veya <span className="h-px flex-1 bg-border" />
        </div>

        <Button
          variant="outline"
          className="w-full rounded-full"
          type="button"
          disabled={!googleAvailable || busy}
          title={googleAvailable ? undefined : "Google OAuth yapılandırması henüz tamamlanmadı"}
          onClick={() => beginGoogleLogin()}
        >
          Google ile devam et
        </Button>
        {!googleAvailable && (
          <p className="mt-2 text-center text-xs text-muted-foreground">
            Google girişi bu ortamda henüz yapılandırılmadı.
          </p>
        )}

        <p className="mt-6 text-center text-sm text-muted-foreground">
          {mode === "login" ? "Hesabınız yok mu? " : "Zaten hesabınız var mı? "}
          <button
            type="button"
            className="font-medium text-primary hover:underline"
            onClick={() => switchMode(mode === "login" ? "signup" : "login")}
          >
            {mode === "login" ? "Kayıt olun" : "Giriş yapın"}
          </button>
        </p>
      </div>

      <Link
        to="/"
        className="mt-6 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> Ana sayfaya dön
      </Link>
    </div>
  );
}

export const Route = createFileRoute("/auth")({
  head: () => ({
    meta: [
      { title: "Avukat Girişi ve Kayıt — JURISAI" },
      {
        name: "description",
        content:
          "JURISAI avukat paneline ücretsiz kayıt olun veya giriş yapın; başvuruları, dosyaları ve AI araçlarını yönetin.",
      },
      { property: "og:title", content: "Avukat Girişi ve Kayıt — JURISAI" },
      {
        property: "og:description",
        content: "Ücretsiz kayıt olun veya avukat panelinize giriş yapın.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: AuthPage,
});

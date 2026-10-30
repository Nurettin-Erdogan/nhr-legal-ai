import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Link } from "@/lib/router-compat";
import { confirmPasswordReset } from "@/lib/auth-api";
import { MIN_PASSWORD_LENGTH, validateNewPassword } from "@/lib/account-forms";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ArrowLeft, Loader2 } from "lucide-react";

/** Sıfırlama bağlantısıyla açılan sayfa: bağlantıdaki tek kullanımlık anahtarla yeni şifre belirlenir. */
function PasswordResetPage() {
  // Anahtar yalnız tarayıcıda okunur: sunucu taslağı ile istemci aynı (boş) durumu çizer, sonra bağlantıdaki anahtar yüklenir
  // (aksi halde sunucu "bağlantı yok" uyarısını, istemci formu çizer ve sayfa yeniden kurulur).
  const [token, setToken] = useState<string | null>(null);
  useEffect(() => setToken(new URLSearchParams(window.location.search).get("token") ?? ""), []);
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setError(null);
    const problem = validateNewPassword(password, repeat);
    if (problem) return setError(problem);
    setBusy(true);
    try {
      await confirmPasswordReset(token ?? "", password);
      setDone(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Şifre sıfırlanamadı.");
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
        <h1 className="text-xl font-bold tracking-tight">Yeni şifre belirleyin</h1>
        {token === null ? (
          <p className="mt-4 text-sm text-muted-foreground">Bağlantı denetleniyor…</p>
        ) : !token ? (
          <p className="mt-4 text-sm text-destructive" role="alert">
            Bu sayfa yalnız sıfırlama bağlantısıyla açılır. Giriş sayfasından yeni bir bağlantı
            isteyin.
          </p>
        ) : done ? (
          <>
            <p className="mt-4 text-sm" role="status">
              Şifreniz değişti. Eski şifreyle açılmış bütün oturumlar kapatıldı; yeni şifrenizle
              giriş yapabilirsiniz.
            </p>
            <Button asChild className="mt-5 w-full rounded-full">
              <Link to="/auth">Giriş yap</Link>
            </Button>
          </>
        ) : (
          <form onSubmit={submit} className="mt-6 space-y-4">
            {error && (
              <div
                className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm text-destructive"
                role="alert"
              >
                {error}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="reset-password">Yeni şifre</Label>
              <Input
                id="reset-password"
                type="password"
                required
                minLength={MIN_PASSWORD_LENGTH}
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                En az {MIN_PASSWORD_LENGTH} karakter olmalı.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="reset-password-repeat">Yeni şifre (tekrar)</Label>
              <Input
                id="reset-password-repeat"
                type="password"
                required
                autoComplete="new-password"
                value={repeat}
                onChange={(event) => setRepeat(event.target.value)}
              />
            </div>
            <Button type="submit" className="w-full rounded-full" disabled={busy}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Şifreyi kaydet"}
            </Button>
          </form>
        )}
      </div>
      <Link
        to="/auth"
        className="mt-6 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> Giriş sayfasına dön
      </Link>
    </div>
  );
}

export const Route = createFileRoute("/sifre-sifirla")({
  head: () => ({
    meta: [{ title: "Şifre sıfırlama — JurisAI" }, { name: "robots", content: "noindex" }],
  }),
  component: PasswordResetPage,
});

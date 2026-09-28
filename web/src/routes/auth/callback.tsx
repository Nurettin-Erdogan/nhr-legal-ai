import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { currentUser } from "@/lib/auth-api";
import { Logo } from "@/components/Logo";
import { Loader2 } from "lucide-react";

function AuthCallbackPage() {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      const params = new URLSearchParams(window.location.search);
      const oauthError = params.get("error");
      if (oauthError) {
        setError(
          oauthError === "account_exists"
            ? "Bu e-posta ile mevcut hesap var. Önce şifrenizle giriş yapıp Ayarlar'dan Google hesabınızı bağlayın."
            : oauthError === "cancelled"
              ? "Google girişi iptal edildi."
              : "Google hesabı doğrulanamadı. Lütfen tekrar deneyin.",
        );
        return;
      }
      try {
        const user = await currentUser();
        if (cancelled) return;
        if (user) {
          window.location.replace(
            params.get("linked") === "1" ? "/dashboard/settings" : "/dashboard",
          );
        } else setError("Oturum doğrulanamadı. Lütfen tekrar deneyin.");
      } catch {
        if (!cancelled) setError("Oturum sunucusuna ulaşılamadı. Lütfen tekrar deneyin.");
      }
    };
    void check();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4">
      <Logo />
      <div className="mt-8 flex items-center gap-3 text-muted-foreground">
        {error ? (
          <div className="space-y-3 text-center">
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
            <Link to="/auth" className="text-sm text-primary underline">
              Giriş ekranına dön
            </Link>
          </div>
        ) : (
          <>
            <Loader2 className="h-5 w-5 animate-spin" />
            <p className="text-sm">Google hesabınız doğrulanıyor…</p>
          </>
        )}
      </div>
    </div>
  );
}

export const Route = createFileRoute("/auth/callback")({
  head: () => ({
    meta: [{ title: "Giriş Doğrulanıyor — JURISAI" }],
  }),
  component: AuthCallbackPage,
});

import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { Logo } from "@/components/Logo";
import { Loader2 } from "lucide-react";

function AuthCallbackPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      // Wait for the OAuth session to hydrate, then go to the dashboard.
      for (let i = 0; i < 20; i++) {
        const { data } = await supabase.auth.getSession();
        if (cancelled) return;
        if (data.session) {
          navigate({ to: "/dashboard", replace: true });
          return;
        }
        await new Promise((r) => setTimeout(r, 500));
      }
      if (!cancelled) setError("Oturum doğrulanamadı. Lütfen tekrar deneyin.");
    };
    void check();
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4">
      <Logo />
      <div className="mt-8 flex items-center gap-3 text-muted-foreground">
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
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

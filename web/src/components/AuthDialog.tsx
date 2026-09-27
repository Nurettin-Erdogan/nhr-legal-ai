import { useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultMode?: "signup" | "login";
};

export function AuthDialog({ open, onOpenChange, defaultMode = "signup" }: Props) {
  const [mode, setMode] = useState<"signup" | "login">(defaultMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    if (mode === "login") {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      setBusy(false);
      if (error) return toast.error("Giriş yapılamadı: e-posta veya şifre hatalı");
      toast.success("Giriş yapıldı, sorunuzu sorabilirsiniz");
      onOpenChange(false);
    } else {
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: window.location.origin },
      });
      setBusy(false);
      if (error) return toast.error(error.message);
      if (data.session) {
        toast.success("Kaydınız tamamlandı, sorunuzu sorabilirsiniz");
        onOpenChange(false);
      } else {
        toast.success("Kayıt alındı. E-postanızdaki doğrulama bağlantısına tıklayın.");
        setMode("login");
      }
    }
  };

  const google = async () => {
    try {
      const { lovable } = await import("@/integrations/lovable");
      await lovable.auth.signInWithOAuth("google", {
        redirect_uri: `${window.location.origin}/auth/callback`,
      });
    } catch {
      toast.error("Google ile giriş başlatılamadı");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{mode === "signup" ? "Ücretsiz kayıt olun" : "Giriş yapın"}</DialogTitle>
          <DialogDescription>
            Soru sormak ve belge yüklemek için hesabınızla devam edin.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="auth-dialog-email">E-posta</Label>
            <Input
              id="auth-dialog-email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="auth-dialog-password">Şifre</Label>
            <Input
              id="auth-dialog-password"
              type="password"
              required
              minLength={6}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <Button type="submit" className="w-full rounded-full" disabled={busy}>
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : mode === "signup" ? (
              "Kayıt Ol"
            ) : (
              "Giriş Yap"
            )}
          </Button>
        </form>

        <div className="flex items-center gap-3 text-[11px] uppercase tracking-widest text-muted-foreground">
          <span className="h-px flex-1 bg-border" /> veya <span className="h-px flex-1 bg-border" />
        </div>

        <Button variant="outline" className="w-full rounded-full" onClick={google}>
          Google ile devam et
        </Button>

        <p className="text-center text-sm text-muted-foreground">
          {mode === "signup" ? "Zaten hesabınız var mı? " : "Hesabınız yok mu? "}
          <button
            type="button"
            className="font-medium text-primary hover:underline"
            onClick={() => setMode(mode === "signup" ? "login" : "signup")}
          >
            {mode === "signup" ? "Giriş yapın" : "Kayıt olun"}
          </button>
        </p>
      </DialogContent>
    </Dialog>
  );
}

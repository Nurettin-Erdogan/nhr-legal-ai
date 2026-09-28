import { useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { beginGoogleLogin, googleLoginAvailable, login, register } from "@/lib/auth-api";
import { useEffect } from "react";
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
  const { refreshAuth } = useAuth();
  const [mode, setMode] = useState<"signup" | "login">(defaultMode);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [googleAvailable, setGoogleAvailable] = useState(false);

  useEffect(() => {
    if (!open) return;
    void googleLoginAvailable()
      .then(setGoogleAvailable)
      .catch(() => setGoogleAvailable(false));
  }, [open]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      if (mode === "login") await login(email.trim().toLowerCase(), password);
      else {
        if (fullName.trim().length < 2) throw new Error("Ad ve soyadınızı girin.");
        await register(email.trim().toLowerCase(), password, fullName.trim());
      }
      await refreshAuth();
      toast.success(mode === "login" ? "Giriş yapıldı" : "Kaydınız tamamlandı");
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Oturum işlemi başarısız oldu");
    } finally {
      setBusy(false);
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
          {mode === "signup" && (
            <div className="space-y-2">
              <Label htmlFor="auth-dialog-name">Ad soyad</Label>
              <Input
                id="auth-dialog-name"
                required
                minLength={2}
                autoComplete="name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
              />
            </div>
          )}
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
              minLength={mode === "signup" ? 10 : 1}
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

        <Button
          variant="outline"
          className="w-full rounded-full"
          disabled={!googleAvailable || busy}
          onClick={() => beginGoogleLogin()}
        >
          Google ile devam et
        </Button>
        {!googleAvailable && (
          <p className="text-center text-xs text-muted-foreground">
            Google girişi bu ortamda henüz yapılandırılmadı.
          </p>
        )}

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

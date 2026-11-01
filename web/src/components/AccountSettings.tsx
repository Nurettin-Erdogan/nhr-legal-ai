import { useEffect, useState } from "react";
import { useAuth } from "@/components/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { changePassword, deleteAccount, updateProfile, type AccountSecurity } from "@/lib/auth-api";
import {
  DELETE_PHRASE,
  MIN_PASSWORD_LENGTH,
  validateAccountDeletion,
  validateFullName,
  validatePasswordChange,
} from "@/lib/account-forms";

function Feedback({ error, notice }: { error: string; notice: string }) {
  if (error)
    return (
      <p role="alert" className="text-sm text-destructive">
        {error}
      </p>
    );
  if (notice)
    return (
      <p role="status" className="text-sm text-emerald-700 dark:text-emerald-400">
        {notice}
      </p>
    );
  return null;
}

const messageOf = (cause: unknown, fallback: string) =>
  cause instanceof Error ? cause.message : fallback;

function ProfileSection() {
  const { user, refreshAuth } = useAuth();
  const [name, setName] = useState(user?.full_name ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => setName(user?.full_name ?? ""), [user?.full_name]);

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setNotice("");
    const problem = validateFullName(name);
    if (problem) return setError(problem);
    setBusy(true);
    try {
      await updateProfile(name.trim());
      await refreshAuth();
      setNotice("Profil güncellendi.");
    } catch (cause) {
      setError(messageOf(cause, "Profil güncellenemedi."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="space-y-4 rounded-xl border border-border bg-card p-6"
      data-testid="profile-section"
    >
      <h2 className="text-xl font-semibold">Profil</h2>
      <form onSubmit={save} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="profile-name">Ad soyad</Label>
            <Input
              id="profile-name"
              value={name}
              maxLength={150}
              autoComplete="name"
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="profile-email">E-posta</Label>
            <Input id="profile-email" value={user?.email ?? ""} readOnly disabled />
            <p className="text-xs text-muted-foreground">
              E-posta adresi giriş kimliğinizdir ve buradan değiştirilemez.
            </p>
          </div>
        </div>
        <Feedback error={error} notice={notice} />
        <Button type="submit" disabled={busy || name.trim() === (user?.full_name ?? "")}>
          {busy ? "Kaydediliyor…" : "Profili kaydet"}
        </Button>
      </form>
    </section>
  );
}

function PasswordSection({ security }: { security: AccountSecurity | null }) {
  const { refreshAuth } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const hasPassword = security?.has_password ?? true;

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setNotice("");
    const problem = validatePasswordChange(current, next, repeat, hasPassword);
    if (problem) return setError(problem);
    setBusy(true);
    try {
      await changePassword(current, next);
      await refreshAuth();
      setCurrent("");
      setNext("");
      setRepeat("");
      setNotice("Şifreniz değişti. Diğer cihazlardaki oturumlar kapatıldı.");
    } catch (cause) {
      setError(messageOf(cause, "Şifre değiştirilemedi."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="space-y-4 rounded-xl border border-border bg-card p-6"
      data-testid="password-section"
    >
      <h2 className="text-xl font-semibold">Şifre</h2>
      {!hasPassword && (
        <p className="text-sm text-muted-foreground">
          Hesabınız Google ile açıldığı için şifreniz yok. Buradan bir şifre belirlerseniz e-posta
          ve şifreyle de giriş yapabilirsiniz.
        </p>
      )}
      <form onSubmit={save} className="space-y-4">
        {hasPassword && (
          <div className="space-y-2 sm:max-w-sm">
            <Label htmlFor="current-password">Mevcut şifre</Label>
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
            />
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="new-password">Yeni şifre</Label>
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              minLength={MIN_PASSWORD_LENGTH}
              value={next}
              onChange={(event) => setNext(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">En az {MIN_PASSWORD_LENGTH} karakter.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-password-repeat">Yeni şifre (tekrar)</Label>
            <Input
              id="new-password-repeat"
              type="password"
              autoComplete="new-password"
              value={repeat}
              onChange={(event) => setRepeat(event.target.value)}
            />
          </div>
        </div>
        <Feedback error={error} notice={notice} />
        <Button type="submit" disabled={busy}>
          {busy ? "Kaydediliyor…" : hasPassword ? "Şifreyi değiştir" : "Şifre belirle"}
        </Button>
      </form>
    </section>
  );
}

function DeleteSection({ security }: { security: AccountSecurity | null }) {
  const [open, setOpen] = useState(false);
  const [phrase, setPhrase] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const hasPassword = security?.has_password ?? true;

  const remove = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    const problem = validateAccountDeletion(phrase, password, hasPassword);
    if (problem) return setError(problem);
    setBusy(true);
    try {
      await deleteAccount(password, phrase.trim());
      window.location.assign("/?hesap=silindi");
    } catch (cause) {
      setError(messageOf(cause, "Hesap silinemedi."));
      setBusy(false);
    }
  };

  return (
    <section
      className="space-y-3 rounded-xl border border-destructive/40 bg-card p-6"
      data-testid="delete-account-section"
    >
      <h2 className="text-xl font-semibold text-destructive">Hesabı sil</h2>
      <p className="text-sm">
        Hesabınız ve içindeki her şey <strong>kalıcı olarak</strong> silinir: müvekkiller, davalar,
        görevler, takvim, yüklediğiniz ve UYAP'tan aktardığınız belgeler (dosyalarıyla birlikte),
        sohbet geçmişi ve yapay zekâ çıktıları. Bu işlem geri alınamaz. Silmeden önce yukarıdaki{" "}
        <em>Verilerimi indir</em> düğmesiyle bir kopya alabilirsiniz.
      </p>
      {!open ? (
        <Button
          type="button"
          variant="outline"
          className="border-destructive/50 text-destructive"
          onClick={() => setOpen(true)}
        >
          Hesabımı silmek istiyorum
        </Button>
      ) : (
        <form onSubmit={remove} className="space-y-4">
          <div className="space-y-2 sm:max-w-sm">
            <Label htmlFor="delete-phrase">
              Onaylamak için <span className="font-mono">{DELETE_PHRASE}</span> yazın
            </Label>
            <Input
              id="delete-phrase"
              value={phrase}
              autoComplete="off"
              onChange={(event) => setPhrase(event.target.value)}
            />
          </div>
          {hasPassword && (
            <div className="space-y-2 sm:max-w-sm">
              <Label htmlFor="delete-password">Şifreniz</Label>
              <Input
                id="delete-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
          )}
          <Feedback error={error} notice="" />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="destructive" disabled={busy}>
              {busy ? "Siliniyor…" : "Hesabımı kalıcı olarak sil"}
            </Button>
            <Button type="button" variant="ghost" disabled={busy} onClick={() => setOpen(false)}>
              Vazgeç
            </Button>
          </div>
        </form>
      )}
    </section>
  );
}

/** Ayarlar sayfasının hesap bölümleri: profil ve şifre üstte, hesabı silme en altta ayrı gösterilir. */

export function AccountProfile({ security }: { security: AccountSecurity | null }) {
  return (
    <>
      <ProfileSection />
      <PasswordSection security={security} />
    </>
  );
}

export function AccountDeletion({ security }: { security: AccountSecurity | null }) {
  return <DeleteSection security={security} />;
}

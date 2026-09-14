"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppSidebar, { Icon } from "@/app/ui/app-sidebar";
import { API_URL } from "@/lib/api";

type Mode = "login" | "register";
type AuthStatus = { configured: boolean; registration_enabled: boolean };
type User = { id: string; email: string; full_name: string | null; roles: string[] };

export default function AuthPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API_URL}/api/auth/status`, { credentials: "include" })
      .then((response) => response.json())
      .then(setStatus)
      .catch(() => setError("Kimlik servisine ulaşılamadı."));
    fetch(`${API_URL}/api/auth/me`, { credentials: "include" })
      .then((response) => response.ok ? response.json() : null)
      .then(setUser)
      .catch(() => null);
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const payload = mode === "register"
        ? { email, password, full_name: fullName }
        : { email, password };
      const response = await fetch(`${API_URL}/api/auth/${mode}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? "Oturum işlemi tamamlanamadı");
      setUser(result.user);
      setPassword("");
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Oturum işlemi tamamlanamadı");
    } finally {
      setLoading(false);
    }
  }

  async function logout() {
    await fetch(`${API_URL}/api/auth/logout`, { method: "POST", credentials: "include" });
    setUser(null);
  }

  return (
    <main className="app-shell">
      <AppSidebar active="auth" />
      <section className="workspace">
        <header className="topbar">
          <div><span className="eyebrow">GÜVENLİ ÇALIŞMA ALANI</span><h1>Hesap</h1></div>
          <div className={`ai-status ${status?.configured ? "ready" : "waiting"}`}>
            <i/><span>{status?.configured ? "Kimlik servisi hazır" : "JWT ayarı bekleniyor"}</span>
          </div>
        </header>

        <div className="auth-content">
          <section className="auth-copy">
            <div className="assistant-symbol"><Icon name="user"/></div>
            <span className="section-kicker">NHR LEGAL AI</span>
            <h2>Hukuk çalışmalarınız size özel kalsın.</h2>
            <p>Projeler, belgeler ve konuşmalar kullanıcı hesabınıza bağlanacak; parolalar Argon2 ile tek yönlü olarak korunur.</p>
          </section>

          {!status?.configured && status && (
            <div className="setup-banner">
              <div><strong>Kimlik doğrulama için son bir ayar gerekiyor</strong><span>Proje `.env` dosyasına en az 32 karakterlik rastgele JWT_SECRET ekleyip API’yi yeniden başlatın.</span></div>
              <code>JWT_SECRET=...</code>
            </div>
          )}

          {user ? (
            <section className="auth-card signed-in">
              <span className="section-kicker">OTURUM AÇIK</span>
              <h3>{user.full_name ?? user.email}</h3>
              <p>{user.email}</p>
              <div className="role-row">{user.roles.map((role) => <span key={role}>{role}</span>)}</div>
              <button onClick={logout}>Oturumu kapat</button>
            </section>
          ) : (
            <section className="auth-card">
              <div className="auth-tabs">
                <button className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>Giriş yap</button>
                <button className={mode === "register" ? "active" : ""} onClick={() => setMode("register")} disabled={status?.registration_enabled === false}>Hesap oluştur</button>
              </div>
              <form onSubmit={submit}>
                {mode === "register" && <label>Ad soyad<input value={fullName} onChange={(event) => setFullName(event.target.value)} minLength={2} required autoComplete="name"/></label>}
                <label>E-posta<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required autoComplete="email"/></label>
                <label>Parola<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={mode === "register" ? 10 : 1} required autoComplete={mode === "register" ? "new-password" : "current-password"}/></label>
                {error && <div className="error-banner">{error}</div>}
                <button className="auth-submit" disabled={loading || !status?.configured}>{loading ? "İşleniyor…" : mode === "login" ? "Giriş yap" : "Hesap oluştur"}</button>
              </form>
            </section>
          )}
        </div>
      </section>
    </main>
  );
}

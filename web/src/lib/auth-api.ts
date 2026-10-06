const API_BASE_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export interface AuthUser {
  id: string;
  email: string;
  full_name: string | null;
  status: string;
  roles: string[];
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
}

let accessToken = "";

async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string | Array<{ msg?: string }> };
    if (typeof payload.detail === "string") return payload.detail;
    if (Array.isArray(payload.detail)) {
      return (
        payload.detail
          .map((item) => item.msg)
          .filter(Boolean)
          .join("; ") || "İstek doğrulanamadı."
      );
    }
  } catch {
    // Sunucu JSON döndürmediyse aşağıdaki genel mesaj kullanılır.
  }
  return `Sunucu isteği başarısız oldu (${response.status}).`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new Error(
      "Kimlik doğrulama sunucusuna ulaşılamadı. API servisinin çalıştığını kontrol edin.",
    );
  }

  if (!response.ok) {
    const error = new Error(await errorMessage(response));
    Object.assign(error, { status: response.status });
    throw error;
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function currentUser(): Promise<AuthUser | null> {
  try {
    return await request<AuthUser>("/api/auth/me");
  } catch (error) {
    if (error instanceof Error && "status" in error && error.status === 401) return null;
    throw error;
  }
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const result = await request<AuthResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  accessToken = result.access_token;
  return result;
}

/**
 * `termsVersion`: kullanıcının kayıt formunda işaretleyerek kabul ettiği Kullanım Şartları / KVKK aydınlatma metninin sürümü.
 * Boşsa onay verilmemiş sayılır ve sunucu kaydı reddeder.
 */
export async function register(
  email: string,
  password: string,
  fullName: string,
  termsVersion = "",
): Promise<AuthResponse> {
  const result = await request<AuthResponse>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({
      email,
      password,
      full_name: fullName,
      terms_accepted: Boolean(termsVersion),
      terms_version: termsVersion || null,
    }),
  });
  accessToken = result.access_token;
  return result;
}

// --- Hesap: profil, parola, şifre sıfırlama, hesabı silme ------------------------------------------------------------------

export interface AccountSecurity {
  has_password: boolean;
  email_delivery: boolean;
}

export const accountSecurity = () => request<AccountSecurity>("/api/account/security");

export const updateProfile = (fullName: string) =>
  request<AuthUser>("/api/account/profile", { method: "POST", body: JSON.stringify({ full_name: fullName }) });

export async function changePassword(currentPassword: string, newPassword: string): Promise<AuthResponse> {
  const result = await request<AuthResponse>("/api/account/password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword || null, new_password: newPassword }),
  });
  accessToken = result.access_token; // diğer oturumlar kapandı; bu oturum yeni jetonla sürer
  return result;
}

export async function deleteAccount(password: string, confirm: string): Promise<void> {
  await request<void>("/api/account/delete", {
    method: "POST",
    body: JSON.stringify({ password: password || null, confirm }),
  });
  accessToken = "";
}

/** `delivery`: "email" ise bağlantı e-postayla gönderilir; "manual" ise bu kurulumda e-posta gönderilemez. */
export const requestPasswordReset = (email: string) =>
  request<{ ok: boolean; delivery: "email" | "manual" }>("/api/auth/password-reset/request", {
    method: "POST",
    body: JSON.stringify({ email }),
  });

export const confirmPasswordReset = (token: string, newPassword: string) =>
  request<void>("/api/auth/password-reset/confirm", {
    method: "POST",
    body: JSON.stringify({ token, new_password: newPassword }),
  });

export async function logout(): Promise<void> {
  try {
    await request<void>("/api/auth/logout", { method: "POST" });
  } finally {
    // Sunucu yanıt vermese bile bellekteki oturum anahtarı atılır.
    accessToken = "";
  }
}

export function inMemoryAccessToken(): string {
  return accessToken;
}

export async function googleLoginAvailable(): Promise<boolean> {
  const status = await request<{ configured: boolean }>("/api/auth/google/status");
  return status.configured;
}

export async function googleAccountLinked(): Promise<boolean> {
  const connection = await request<{ linked: boolean }>("/api/auth/google/connection");
  return connection.linked;
}

/** `termsVersion`: Google ile yeni hesap açılırsa, sayfada gösterilen şartların sürümü hesaba yazılır. */
export function beginGoogleLogin(linkAccount = false, termsVersion = ""): void {
  const params = new URLSearchParams();
  if (linkAccount) params.set("link", "true");
  if (termsVersion && !linkAccount) params.set("terms", termsVersion);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  window.location.assign(`${API_BASE_URL}/api/auth/google/start${suffix}`);
}

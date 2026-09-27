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

export async function register(
  email: string,
  password: string,
  fullName: string,
): Promise<AuthResponse> {
  const result = await request<AuthResponse>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, full_name: fullName }),
  });
  accessToken = result.access_token;
  return result;
}

export async function logout(): Promise<void> {
  await request<void>("/api/auth/logout", { method: "POST" });
  accessToken = "";
}

export function inMemoryAccessToken(): string {
  return accessToken;
}

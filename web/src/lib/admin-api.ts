/** Yönetici paneli API'si (`/api/admin/*`). Oturum çerezle gider; yetki sunucuda denetlenir. */
const API_BASE_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export interface AdminSummary {
  users_total: number;
  users_active: number;
  users_suspended: number;
  users_new_7d: number;
  users_seen_7d: number;
  ai_answers_24h: number;
  ai_answers_7d: number;
  feedback_7d: number;
  feedback_total: number;
  cases_total: number;
  documents_total: number;
}

export interface AdminOverview {
  summary: AdminSummary;
  health: {
    database: boolean;
    local_model: { reachable: boolean; model: string; installed: boolean };
    cloud: {
      provider: string | null;
      model: string | null;
      usage_usd?: number | null;
      limit_usd?: number | null;
      remaining_usd?: number | null;
      error?: string;
    };
    backup: {
      found: boolean;
      created_at?: string;
      rows?: number;
      database_bytes?: number;
      uploads_included?: boolean;
    };
  };
  corpus: {
    decisions?: number;
    pending_verification?: number;
    legislation?: number | null;
    latest_decision_date?: string | null;
  };
}

export interface AdminUser {
  user_id: string;
  email: string;
  full_name: string | null;
  status: "active" | "inactive" | "suspended";
  created_at: string;
  last_login_at: string | null;
  roles: string[];
  cases: number;
  clients: number;
  documents: number;
  conversations: number;
  ai_answers_30d: number;
  last_activity_at: string | null;
  /** E-postası erişim listesinde mi. */
  listed: boolean;
  /** Şu an girebilir mi (aktif + erişim modu/listesi; yöneticiler her zaman). */
  has_access: boolean;
}

export interface AdminFeedback {
  id: string;
  created_at: string;
  category: "hata" | "oneri" | "begeni";
  page: string | null;
  message: string;
  user_id: string;
  user_email: string;
  user_name: string | null;
}

export interface AdminAccessEntry {
  id: string;
  email: string;
  note: string | null;
  added_at: string;
  /** Bu e-postayla açılmış hesabın durumu; henüz hesap yoksa null. */
  account_status: "active" | "inactive" | "suspended" | null;
}

export interface AdminAccess {
  mode: "open" | "allowlist";
  /** Sunucu ayarı (ALLOW_REGISTRATION); kapalıysa listedekiler de yeni hesap açamaz. */
  registration_allowed: boolean;
  /** Listede olmayan aktif hesaplar (yöneticiler hariç): "yalnız liste" modunda bunlar giremez. */
  unlisted_accounts: number;
  entries: AdminAccessEntry[];
}

export interface AdminAuditEntry {
  id: string;
  created_at: string;
  actor_user_id: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  ip_address: string | null;
  metadata: Record<string, unknown>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      credentials: "include",
      headers: { ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
    });
  } catch {
    throw new Error("Sunucuya ulaşılamadı. API servisinin çalıştığını kontrol edin.");
  }
  if (!response.ok) {
    let detail = `İstek başarısız oldu (${response.status}).`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // JSON olmayan hata gövdesi: genel mesaj kalır
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export const adminApi = {
  overview: () => request<AdminOverview>("/api/admin/overview"),
  users: (q = "", status = "") => {
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q.trim());
    if (status) params.set("status", status);
    const suffix = params.toString() ? `?${params}` : "";
    return request<AdminUser[]>(`/api/admin/users${suffix}`);
  },
  // API'nin CORS listesi PUT/PATCH'e izin vermez; değişiklikler POST ile gider.
  setStatus: (userId: string, status: "active" | "suspended") =>
    request(`/api/admin/users/${userId}/status`, { method: "POST", ...json({ status }) }),
  grantRole: (userId: string, role: string) =>
    request(`/api/admin/users/${userId}/roles/${role}`, { method: "POST" }),
  revokeRole: (userId: string, role: string) =>
    request(`/api/admin/users/${userId}/roles/${role}`, { method: "DELETE" }),
  feedback: (category = "") =>
    request<AdminFeedback[]>(
      `/api/admin/feedback${category ? `?category=${encodeURIComponent(category)}` : ""}`,
    ),
  access: () => request<AdminAccess>("/api/admin/access"),
  setAccessMode: (mode: AdminAccess["mode"]) =>
    request("/api/admin/access", { method: "POST", ...json({ mode }) }),
  addAccess: (email: string, note: string) =>
    request("/api/admin/access/entries", {
      method: "POST",
      ...json({ email, note: note || null }),
    }),
  removeAccess: (entryId: string) =>
    request(`/api/admin/access/entries/${entryId}`, { method: "DELETE" }),
  audit: (limit = 100) => request<AdminAuditEntry[]>(`/api/admin/audit?limit=${limit}`),
};

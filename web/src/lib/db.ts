/**
 * Büro verisi istemcisi. Arayüzün `supabase.from(...)` / `supabase.storage` çağrıları aynı sözleşmeyle
 * çalışmaya devam eder, ama istekler bulut yerine kendi FastAPI arka ucumuza (`/api/office/*`) gider.
 * Veri kendi PostgreSQL'imizde, kullanıcı başına RLS altında tutulur.
 *
 * Desteklenen sorgu dili: select/insert/update/upsert/delete, eq/neq/gt/gte/lt/lte/in/is/like/ilike/
 * not/match/filter, order/limit/range, single/maybeSingle, count. `or()` ve tam metin arama
 * desteklenmez (kullanılırsa açık bir hata döner).
 */
import { currentUser, inMemoryAccessToken, login, logout, register } from "@/lib/auth-api";

const API_BASE_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(/\/$/, "");

export interface DbError {
  message: string;
  status?: number;
  code?: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
type DbResult = { data: Any; error: DbError | null; count?: number | null };

type FilterOp = "eq" | "neq" | "gt" | "gte" | "lt" | "lte" | "in" | "is" | "like" | "ilike";
interface Filter {
  col: string;
  op: FilterOp;
  val: unknown;
  negate?: boolean;
}

function authHeaders(): Record<string, string> {
  const token = inMemoryAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function errorFrom(response: Response): Promise<DbError> {
  let message = `Sunucu isteği başarısız oldu (${response.status}).`;
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") message = payload.detail;
  } catch {
    /* JSON değil */
  }
  return {
    message,
    status: response.status,
    code: response.status === 406 ? "PGRST116" : undefined,
  };
}

class QueryBuilder implements PromiseLike<DbResult> {
  private op: "select" | "insert" | "update" | "upsert" | "delete" = "select";
  private columns = "*";
  private filters: Filter[] = [];
  private orderBy: Array<{ col: string; ascending: boolean }> = [];
  private limitN?: number;
  private offsetN = 0;
  private values?: unknown;
  private conflict?: string;
  private singleMode?: "one" | "maybe";
  private wantCount = false;
  private head = false;
  private returning = false;
  private unsupported?: string;

  constructor(private readonly table: string) {}

  select(columns = "*", options?: { count?: string; head?: boolean }) {
    this.columns = columns;
    if (this.op !== "select") this.returning = true;
    if (options?.count) this.wantCount = true;
    if (options?.head) {
      this.head = true;
      this.limitN = 1;
    }
    return this;
  }
  insert(values: unknown) {
    this.op = "insert";
    this.values = values;
    return this;
  }
  update(values: unknown) {
    this.op = "update";
    this.values = values;
    return this;
  }
  upsert(values: unknown, options?: { onConflict?: string }) {
    this.op = "upsert";
    this.values = values;
    this.conflict = options?.onConflict;
    return this;
  }
  delete() {
    this.op = "delete";
    return this;
  }

  private add(col: string, op: FilterOp, val: unknown, negate = false) {
    this.filters.push({ col, op, val, negate });
    return this;
  }
  eq(col: string, val: unknown) {
    return this.add(col, "eq", val);
  }
  neq(col: string, val: unknown) {
    return this.add(col, "neq", val);
  }
  gt(col: string, val: unknown) {
    return this.add(col, "gt", val);
  }
  gte(col: string, val: unknown) {
    return this.add(col, "gte", val);
  }
  lt(col: string, val: unknown) {
    return this.add(col, "lt", val);
  }
  lte(col: string, val: unknown) {
    return this.add(col, "lte", val);
  }
  in(col: string, val: unknown[]) {
    return this.add(col, "in", val);
  }
  is(col: string, val: unknown) {
    return this.add(col, "is", val);
  }
  like(col: string, val: string) {
    return this.add(col, "like", val);
  }
  ilike(col: string, val: string) {
    return this.add(col, "ilike", val);
  }
  not(col: string, op: string, val: unknown) {
    return this.add(col, op as FilterOp, val, true);
  }
  filter(col: string, op: string, val: unknown) {
    return this.add(col, op as FilterOp, val);
  }
  match(query: Record<string, unknown>) {
    for (const [col, val] of Object.entries(query)) this.add(col, "eq", val);
    return this;
  }
  or(_expression: string) {
    this.unsupported = "or() desteklenmiyor";
    return this;
  }
  textSearch(_col: string, _query: string, _options?: unknown) {
    this.unsupported = "Tam metin arama bu tabloda desteklenmiyor";
    return this;
  }
  order(col: string, options?: { ascending?: boolean }) {
    this.orderBy.push({ col, ascending: options?.ascending ?? true });
    return this;
  }
  limit(n: number) {
    this.limitN = n;
    return this;
  }
  range(from: number, to: number) {
    this.offsetN = from;
    this.limitN = to - from + 1;
    return this;
  }
  single() {
    this.singleMode = "one";
    return this;
  }
  maybeSingle() {
    this.singleMode = "maybe";
    return this;
  }

  private async execute(): Promise<DbResult> {
    if (this.unsupported) return { data: null, error: { message: this.unsupported } };
    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/api/office/${this.table}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({
          op: this.op,
          columns: this.columns,
          filters: this.filters,
          order: this.orderBy,
          limit: this.limitN,
          offset: this.offsetN,
          values: this.values,
          on_conflict: this.conflict,
          single: this.singleMode,
          count: this.wantCount,
        }),
      });
    } catch {
      return {
        data: null,
        error: { message: "Sunucuya ulaşılamadı. API servisinin çalıştığını kontrol edin." },
      };
    }
    if (!response.ok) return { data: null, error: await errorFrom(response) };
    const payload = (await response.json()) as { data: Any; count: number | null };
    // Supabase davranışı: yazma işlemleri satır döndürmez, `.select()` zincirlenmedikçe.
    const hideRows = this.op !== "select" && !this.returning;
    return {
      data: hideRows || this.head ? null : payload.data,
      error: null,
      count: payload.count,
    };
  }

  then<R1 = DbResult, R2 = never>(
    onfulfilled?: ((value: DbResult) => R1 | PromiseLike<R1>) | null,
    onrejected?: ((reason: unknown) => R2 | PromiseLike<R2>) | null,
  ): PromiseLike<R1 | R2> {
    return this.execute().then(onfulfilled, onrejected);
  }
}

// --- Dosya deposu ---------------------------------------------------------------------------------

async function storageFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API_BASE_URL}/api/office/storage/${path}`, {
    ...init,
    credentials: "include",
    headers: { ...authHeaders(), ...init?.headers },
  });
}

const storageBucket = () => ({
  async upload(
    path: string,
    file: Blob,
    _options?: unknown,
  ): Promise<{ data: Any; error: DbError | null }> {
    const form = new FormData();
    form.append("file", file, (file as File).name ?? "dosya");
    const response = await storageFetch(`upload?key=${encodeURIComponent(path)}`, {
      method: "POST",
      body: form,
    });
    if (!response.ok) return { data: null, error: await errorFrom(response) };
    return { data: { path }, error: null };
  },
  async download(path: string): Promise<{ data: Blob | null; error: DbError | null }> {
    const response = await storageFetch(`download?key=${encodeURIComponent(path)}`);
    if (!response.ok) return { data: null, error: await errorFrom(response) };
    return { data: await response.blob(), error: null };
  },
  async remove(paths: string[]): Promise<{ data: Any; error: DbError | null }> {
    const response = await storageFetch("remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keys: paths }),
    });
    if (!response.ok) return { data: null, error: await errorFrom(response) };
    return { data: await response.json(), error: null };
  },
  /** Kimlik başlığı gerektiren indirme için dosyayı çekip geçici bir tarayıcı bağlantısı üretir. */
  async createSignedUrl(path: string, _expiresIn?: number, _options?: unknown) {
    const { data, error } = await this.download(path);
    if (error || !data) return { data: null, error: error ?? { message: "Dosya bulunamadı" } };
    return { data: { signedUrl: URL.createObjectURL(data) }, error: null };
  },
});

// --- Oturum (kimlik doğrulama FastAPI'de; bu yalnızca eski çağrılar için uyumluluk katmanı) -----------

const authShim = {
  async getSession() {
    const user = await currentUser().catch(() => null);
    return {
      data: { session: user ? { access_token: inMemoryAccessToken(), user } : null },
      error: null,
    };
  },
  async getUser() {
    const user = await currentUser().catch(() => null);
    return { data: { user }, error: user ? null : { message: "Oturum yok" } };
  },
  async signInWithPassword(credentials: { email: string; password: string }) {
    try {
      const result = await login(credentials.email, credentials.password);
      return {
        data: { user: result.user, session: { access_token: result.access_token } },
        error: null,
      };
    } catch (error) {
      return {
        data: null,
        error: { message: error instanceof Error ? error.message : "Giriş başarısız" },
      };
    }
  },
  async signUp(credentials: {
    email: string;
    password: string;
    options?: { emailRedirectTo?: string; data?: { first_name?: string; last_name?: string } };
  }) {
    const name = [credentials.options?.data?.first_name, credentials.options?.data?.last_name]
      .filter(Boolean)
      .join(" ");
    try {
      const result = await register(credentials.email, credentials.password, name);
      return {
        data: { user: result.user, session: { access_token: result.access_token } },
        error: null,
      };
    } catch (error) {
      return {
        data: null,
        error: { message: error instanceof Error ? error.message : "Kayıt başarısız" },
      };
    }
  },
  async signOut() {
    await logout().catch(() => undefined);
    return { error: null };
  },
  async setSession(_session: unknown) {
    return { data: null, error: { message: "Bu giriş yöntemi desteklenmiyor" } };
  },
  onAuthStateChange() {
    return { data: { subscription: { unsubscribe() {} } } };
  },
};

export const db = {
  from: (table: string) => new QueryBuilder(table),
  storage: { from: (_bucket: string) => storageBucket() },
  auth: authShim,
};

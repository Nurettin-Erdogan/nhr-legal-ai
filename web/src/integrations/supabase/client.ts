// Eskiden Supabase istemcisiydi. Artık aynı arayüzü kendi FastAPI arka ucumuza (`/api/office/*`)
// bağlayan uyumluluk katmanıdır; bkz. `@/lib/db`. Mevcut `supabase.from(...)` çağrıları değişmeden çalışır.
import { db } from "@/lib/db";

export const supabase = db;

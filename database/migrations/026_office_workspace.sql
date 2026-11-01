-- Büro çalışma alanı: müvekkil, dava, görev, takvim, hatırlatma, arama, belge, UYAP ve AI çıktıları.
-- Web arayüzünün Supabase'te tuttuğu tablolar burada, kendi veritabanımızda ve RLS altında yaşar.
--
-- Erişim kuralı: her satır yalnız sahibine (owner_id) görünür. Eski Supabase şemasındaki
-- "admin her şeyi görür" istisnası bilerek kaldırıldı; müvekkil verisine yönetici de dokunamaz.
-- `office_basvurular` tek istisna: sahibi olmayan (siteden gelen) başvuruları yalnız admin görür.
-- Tablolar `office_` önekiyle açılır; mevcut `projects`/`clients`/`documents` (RAG çalışma alanı)
-- ile karışmaz. Kimlikler uygulamada üretilir (RETURNING id kullanılmaz), DEFAULT yalnız yedektir.
BEGIN;

CREATE OR REPLACE FUNCTION office_set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS office_clients (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  full_name TEXT NOT NULL,
  client_type TEXT NOT NULL DEFAULT 'individual',
  national_id TEXT,
  tax_id TEXT,
  email TEXT,
  phone TEXT,
  address TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS office_cases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  client_id UUID REFERENCES office_clients(id) ON DELETE SET NULL,
  case_no TEXT,
  title TEXT NOT NULL,
  court TEXT,
  esas_no TEXT,
  case_type TEXT,
  opponent TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  opened_at DATE,
  next_hearing TIMESTAMPTZ,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS office_tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  assignee_id UUID REFERENCES users(id) ON DELETE SET NULL,
  case_id UUID REFERENCES office_cases(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  description TEXT,
  priority TEXT NOT NULL DEFAULT 'medium',
  status TEXT NOT NULL DEFAULT 'todo',
  due_date TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS office_calendar_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT,
  event_type TEXT NOT NULL DEFAULT 'meeting',
  start_at TIMESTAMPTZ NOT NULL,
  end_at TIMESTAMPTZ,
  all_day BOOLEAN NOT NULL DEFAULT false,
  location TEXT,
  case_id UUID REFERENCES office_cases(id) ON DELETE SET NULL,
  client_id UUID REFERENCES office_clients(id) ON DELETE SET NULL,
  color TEXT,
  reminder_minutes INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS office_reminders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  note TEXT,
  remind_at TIMESTAMPTZ NOT NULL,
  channel TEXT NOT NULL DEFAULT 'in_app',
  status TEXT NOT NULL DEFAULT 'pending',
  event_id UUID REFERENCES office_calendar_events(id) ON DELETE SET NULL,
  case_id UUID REFERENCES office_cases(id) ON DELETE SET NULL,
  task_id UUID REFERENCES office_tasks(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS office_projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  case_id UUID REFERENCES office_cases(id) ON DELETE SET NULL,
  client_id UUID REFERENCES office_clients(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'active',
  color TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS office_project_notes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES office_projects(id) ON DELETE CASCADE,
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS office_ai_outputs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  module TEXT NOT NULL,
  title TEXT NOT NULL,
  prompt TEXT NOT NULL,
  output TEXT,
  sources JSONB,
  model TEXT,
  tokens_used INTEGER,
  case_id UUID REFERENCES office_cases(id) ON DELETE SET NULL,
  project_id UUID REFERENCES office_projects(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS office_calls (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  direction TEXT NOT NULL DEFAULT 'inbound',
  phone TEXT NOT NULL,
  caller_name TEXT,
  client_id UUID REFERENCES office_clients(id) ON DELETE SET NULL,
  case_id UUID REFERENCES office_cases(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'answered',
  duration_sec INTEGER NOT NULL DEFAULT 0,
  recording_url TEXT,
  ai_summary TEXT,
  ai_sentiment TEXT,
  tags TEXT[],
  notes TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS office_call_settings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  greeting TEXT DEFAULT 'Merhaba, hukuk büromuzu aradığınız için teşekkürler. Talebinizi kısaca iletin, sizi en kısa sürede arayacağız.',
  voicemail_enabled BOOLEAN NOT NULL DEFAULT true,
  ai_summary_enabled BOOLEAN NOT NULL DEFAULT true,
  business_hours_start TIME DEFAULT '09:00',
  business_hours_end TIME DEFAULT '18:00',
  after_hours_message TEXT DEFAULT 'Şu an mesai dışındayız. Mesajınızı bırakın, mesai başlangıcında dönüş yapacağız.',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS office_legal_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  doc_type TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  parties JSONB DEFAULT '[]'::jsonb,
  metadata JSONB DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS office_risk_analyses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  source_text TEXT NOT NULL,
  risk_score INTEGER NOT NULL DEFAULT 0,
  risk_level TEXT NOT NULL DEFAULT 'unknown',
  findings JSONB NOT NULL DEFAULT '[]'::jsonb,
  recommendations JSONB NOT NULL DEFAULT '[]'::jsonb,
  summary TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Siteden gelen vatandaş başvuruları. owner_id boşsa henüz kimseye atanmamıştır.
CREATE TABLE IF NOT EXISTS office_basvurular (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID REFERENCES users(id) ON DELETE SET NULL,
  ad_soyad TEXT NOT NULL,
  telefon TEXT,
  eposta TEXT,
  hukuk_alani TEXT,
  konu TEXT NOT NULL,
  sohbet_ozeti TEXT,
  durum TEXT NOT NULL DEFAULT 'yeni',
  atanan_id UUID REFERENCES users(id) ON DELETE SET NULL,
  notlar TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS office_uyap_sync_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'running',
  archive_name TEXT,
  found_count INTEGER NOT NULL DEFAULT 0,
  inserted_count INTEGER NOT NULL DEFAULT 0,
  skipped_count INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  duration_ms INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS office_case_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  case_id UUID REFERENCES office_cases(id) ON DELETE SET NULL,
  client_id UUID REFERENCES office_clients(id) ON DELETE SET NULL,
  file_name TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  mime_type TEXT,
  size_bytes BIGINT,
  source TEXT NOT NULL DEFAULT 'manual',
  uyap_file_no TEXT,
  uyap_birim TEXT,
  doc_date DATE,
  doc_type TEXT,
  tags TEXT[],
  notes TEXT,
  content_excerpt TEXT,
  sync_run_id UUID REFERENCES office_uyap_sync_runs(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- UYAP eklentisinin kullandığı erişim anahtarı. Arayüz anahtarı tekrar gösterdiği için düz saklanır;
-- RLS ile yalnız sahibine görünür, `revoked` ile iptal edilir.
CREATE TABLE IF NOT EXISTS office_uyap_ingest_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token TEXT NOT NULL UNIQUE,
  label TEXT,
  last_used_at TIMESTAMPTZ,
  revoked BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_office_clients_owner ON office_clients (owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_office_cases_owner ON office_cases (owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_office_cases_client ON office_cases (client_id);
CREATE INDEX IF NOT EXISTS idx_office_tasks_owner ON office_tasks (owner_id, due_date);
CREATE INDEX IF NOT EXISTS idx_office_tasks_case ON office_tasks (case_id);
CREATE INDEX IF NOT EXISTS idx_office_events_owner_start ON office_calendar_events (owner_id, start_at);
CREATE INDEX IF NOT EXISTS idx_office_reminders_owner_at ON office_reminders (owner_id, remind_at);
CREATE INDEX IF NOT EXISTS idx_office_projects_owner ON office_projects (owner_id);
CREATE INDEX IF NOT EXISTS idx_office_pnotes_project ON office_project_notes (project_id);
CREATE INDEX IF NOT EXISTS idx_office_ai_outputs_owner ON office_ai_outputs (owner_id, module, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_office_calls_owner ON office_calls (owner_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_office_calls_phone ON office_calls (phone);
CREATE INDEX IF NOT EXISTS idx_office_legal_docs_owner ON office_legal_documents (owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_office_risk_owner ON office_risk_analyses (owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_office_basvurular_created ON office_basvurular (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_office_basvurular_owner ON office_basvurular (owner_id);
CREATE INDEX IF NOT EXISTS idx_office_uyap_runs_owner ON office_uyap_sync_runs (owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_office_case_docs_owner ON office_case_documents (owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_office_case_docs_case ON office_case_documents (case_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_office_case_docs_path ON office_case_documents (storage_path);
CREATE INDEX IF NOT EXISTS idx_office_uyap_tokens_owner ON office_uyap_ingest_tokens (owner_id);

-- Sahibine özel tablolar: RLS + updated_at tetikleyicisi.
DO $$
DECLARE
  tbl TEXT;
BEGIN
  FOREACH tbl IN ARRAY ARRAY[
    'office_clients', 'office_cases', 'office_tasks', 'office_calendar_events',
    'office_reminders', 'office_projects', 'office_project_notes', 'office_ai_outputs',
    'office_calls', 'office_call_settings', 'office_legal_documents', 'office_risk_analyses',
    'office_uyap_sync_runs', 'office_case_documents', 'office_uyap_ingest_tokens'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('DROP POLICY IF EXISTS %I ON %I', tbl || '_owner_select', tbl);
    EXECUTE format('DROP POLICY IF EXISTS %I ON %I', tbl || '_owner_insert', tbl);
    EXECUTE format('DROP POLICY IF EXISTS %I ON %I', tbl || '_owner_update', tbl);
    EXECUTE format('DROP POLICY IF EXISTS %I ON %I', tbl || '_owner_delete', tbl);
    EXECUTE format('CREATE POLICY %I ON %I FOR SELECT USING (owner_id = app_current_user_id())',
                   tbl || '_owner_select', tbl);
    EXECUTE format('CREATE POLICY %I ON %I FOR INSERT WITH CHECK (owner_id = app_current_user_id())',
                   tbl || '_owner_insert', tbl);
    EXECUTE format('CREATE POLICY %I ON %I FOR UPDATE USING (owner_id = app_current_user_id()) '
                   'WITH CHECK (owner_id = app_current_user_id())',
                   tbl || '_owner_update', tbl);
    EXECUTE format('CREATE POLICY %I ON %I FOR DELETE USING (owner_id = app_current_user_id())',
                   tbl || '_owner_delete', tbl);
  END LOOP;

  FOREACH tbl IN ARRAY ARRAY[
    'office_clients', 'office_cases', 'office_tasks', 'office_calendar_events',
    'office_reminders', 'office_projects', 'office_project_notes', 'office_ai_outputs',
    'office_calls', 'office_call_settings', 'office_legal_documents', 'office_risk_analyses',
    'office_basvurular', 'office_uyap_sync_runs', 'office_case_documents'
  ] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', tbl || '_updated_at', tbl);
    EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION office_set_updated_at()',
                   tbl || '_updated_at', tbl);
  END LOOP;
END;
$$;

-- Başvurular: sahibi olan satırı yalnız sahibi, sahipsiz (yeni gelen) satırı yalnız admin görür.
ALTER TABLE office_basvurular ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS office_basvurular_select ON office_basvurular;
DROP POLICY IF EXISTS office_basvurular_insert ON office_basvurular;
DROP POLICY IF EXISTS office_basvurular_update ON office_basvurular;
DROP POLICY IF EXISTS office_basvurular_delete ON office_basvurular;
CREATE POLICY office_basvurular_select ON office_basvurular FOR SELECT USING (
  owner_id = app_current_user_id() OR (owner_id IS NULL AND app_has_global_role('admin'))
);
CREATE POLICY office_basvurular_insert ON office_basvurular FOR INSERT WITH CHECK (
  owner_id = app_current_user_id() OR (owner_id IS NULL AND app_has_global_role('admin'))
);
CREATE POLICY office_basvurular_update ON office_basvurular FOR UPDATE USING (
  owner_id = app_current_user_id() OR (owner_id IS NULL AND app_has_global_role('admin'))
) WITH CHECK (
  owner_id = app_current_user_id() OR (owner_id IS NULL AND app_has_global_role('admin'))
);
CREATE POLICY office_basvurular_delete ON office_basvurular FOR DELETE USING (
  owner_id = app_current_user_id() OR (owner_id IS NULL AND app_has_global_role('admin'))
);

-- Siteden gelen başvuru: oturumsuz (`app.user_id` boş) bağlantı yalnız sahipsiz satır ekleyebilir.
DROP POLICY IF EXISTS office_basvurular_public_insert ON office_basvurular;
CREATE POLICY office_basvurular_public_insert ON office_basvurular FOR INSERT
  WITH CHECK (owner_id IS NULL AND app_current_user_id() IS NULL);

-- Yabancı anahtar denetimi RLS'i atlar: başka kullanıcının kimliği verilerek onun kaydına bağlanılabilirdi.
-- Bu tetikleyici bağlanan satırın çağıran kullanıcıya görünür (yani kendisine ait) olmasını şart koşar.
-- Argümanlar `sütun:tablo` çiftleridir.
CREATE OR REPLACE FUNCTION office_require_own_references()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  pair TEXT;
  ref_column TEXT;
  ref_table TEXT;
  ref_value UUID;
  found BOOLEAN;
BEGIN
  FOREACH pair IN ARRAY TG_ARGV LOOP
    ref_column := split_part(pair, ':', 1);
    ref_table := split_part(pair, ':', 2);
    ref_value := NULLIF(to_jsonb(NEW) ->> ref_column, '')::uuid;
    IF ref_value IS NULL THEN
      CONTINUE;
    END IF;
    EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I WHERE id = $1)', ref_table) INTO found USING ref_value;
    IF NOT found THEN
      RAISE EXCEPTION 'ilişkili kayıt bulunamadı: %', ref_column USING ERRCODE = '23503';
    END IF;
  END LOOP;
  RETURN NEW;
END;
$$;

DO $$
DECLARE
  spec TEXT;
  tbl TEXT;
  refs TEXT[];
BEGIN
  FOREACH spec IN ARRAY ARRAY[
    'office_cases=client_id:office_clients',
    'office_tasks=case_id:office_cases',
    'office_calendar_events=case_id:office_cases,client_id:office_clients',
    'office_reminders=event_id:office_calendar_events,case_id:office_cases,task_id:office_tasks',
    'office_projects=case_id:office_cases,client_id:office_clients',
    'office_project_notes=project_id:office_projects',
    'office_ai_outputs=case_id:office_cases,project_id:office_projects',
    'office_calls=client_id:office_clients,case_id:office_cases',
    'office_case_documents=case_id:office_cases,client_id:office_clients,sync_run_id:office_uyap_sync_runs'
  ] LOOP
    tbl := split_part(spec, '=', 1);
    refs := string_to_array(split_part(spec, '=', 2), ',');
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', tbl || '_own_refs', tbl);
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION office_require_own_references(%s)',
      tbl || '_own_refs', tbl,
      (SELECT string_agg(quote_literal(a), ', ') FROM unnest(refs) AS a)
    );
  END LOOP;
END;
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON
  office_clients, office_cases, office_tasks, office_calendar_events, office_reminders,
  office_projects, office_project_notes, office_ai_outputs, office_calls, office_call_settings,
  office_legal_documents, office_risk_analyses, office_basvurular, office_uyap_sync_runs,
  office_case_documents, office_uyap_ingest_tokens
TO nhr_runtime;

COMMIT;

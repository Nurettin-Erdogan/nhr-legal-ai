-- Roles enum
CREATE TYPE public.app_role AS ENUM ('admin','lawyer','intern','secretary');

CREATE TABLE public.profiles (
  id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  first_name text,
  last_name text,
  phone text,
  office_name text,
  avatar_url text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.profiles TO authenticated;
GRANT ALL ON public.profiles TO service_role;
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

CREATE TABLE public.user_roles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role public.app_role NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(user_id, role)
);
GRANT SELECT ON public.user_roles TO authenticated;
GRANT ALL ON public.user_roles TO service_role;
ALTER TABLE public.user_roles ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.has_role(_user_id uuid, _role public.app_role)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.user_roles WHERE user_id = _user_id AND role = _role)
$$;

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$;

CREATE TABLE public.clients (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  full_name text NOT NULL,
  client_type text NOT NULL DEFAULT 'individual',
  national_id text,
  tax_id text,
  email text,
  phone text,
  address text,
  notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.clients TO authenticated;
GRANT ALL ON public.clients TO service_role;
ALTER TABLE public.clients ENABLE ROW LEVEL SECURITY;

CREATE TABLE public.cases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  client_id uuid REFERENCES public.clients(id) ON DELETE SET NULL,
  case_no text,
  title text NOT NULL,
  court text,
  esas_no text,
  case_type text,
  opponent text,
  status text NOT NULL DEFAULT 'active',
  opened_at date,
  next_hearing timestamptz,
  notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.cases TO authenticated;
GRANT ALL ON public.cases TO service_role;
ALTER TABLE public.cases ENABLE ROW LEVEL SECURITY;

CREATE TABLE public.tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  assignee_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  case_id uuid REFERENCES public.cases(id) ON DELETE SET NULL,
  title text NOT NULL,
  description text,
  priority text NOT NULL DEFAULT 'medium',
  status text NOT NULL DEFAULT 'todo',
  due_date timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.tasks TO authenticated;
GRANT ALL ON public.tasks TO service_role;
ALTER TABLE public.tasks ENABLE ROW LEVEL SECURITY;

CREATE TRIGGER trg_profiles_updated BEFORE UPDATE ON public.profiles FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_clients_updated BEFORE UPDATE ON public.clients FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_cases_updated BEFORE UPDATE ON public.cases FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_tasks_updated BEFORE UPDATE ON public.tasks FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  INSERT INTO public.profiles (id, first_name, last_name)
  VALUES (
    NEW.id,
    COALESCE(NEW.raw_user_meta_data->>'first_name', split_part(NEW.email,'@',1)),
    COALESCE(NEW.raw_user_meta_data->>'last_name','')
  );
  INSERT INTO public.user_roles (user_id, role) VALUES (NEW.id, 'lawyer');
  RETURN NEW;
END; $$;

CREATE TRIGGER on_auth_user_created
AFTER INSERT ON auth.users FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

CREATE POLICY profiles_select_own ON public.profiles FOR SELECT TO authenticated USING (auth.uid() = id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY profiles_update_own ON public.profiles FOR UPDATE TO authenticated USING (auth.uid() = id);
CREATE POLICY profiles_insert_own ON public.profiles FOR INSERT TO authenticated WITH CHECK (auth.uid() = id);

CREATE POLICY roles_select_self_or_admin ON public.user_roles FOR SELECT TO authenticated
  USING (user_id = auth.uid() OR public.has_role(auth.uid(),'admin'));
CREATE POLICY roles_admin_manage ON public.user_roles FOR ALL TO authenticated
  USING (public.has_role(auth.uid(),'admin')) WITH CHECK (public.has_role(auth.uid(),'admin'));

CREATE POLICY clients_select_own ON public.clients FOR SELECT TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY clients_insert_own ON public.clients FOR INSERT TO authenticated WITH CHECK (auth.uid() = owner_id);
CREATE POLICY clients_update_own_or_admin ON public.clients FOR UPDATE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY clients_delete_own_or_admin ON public.clients FOR DELETE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));

CREATE POLICY cases_select_own ON public.cases FOR SELECT TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY cases_insert_own ON public.cases FOR INSERT TO authenticated WITH CHECK (auth.uid() = owner_id);
CREATE POLICY cases_update_own_or_admin ON public.cases FOR UPDATE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY cases_delete_own_or_admin ON public.cases FOR DELETE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));

CREATE POLICY tasks_select_own ON public.tasks FOR SELECT TO authenticated USING (auth.uid() = owner_id OR auth.uid() = assignee_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY tasks_insert_own ON public.tasks FOR INSERT TO authenticated WITH CHECK (auth.uid() = owner_id);
CREATE POLICY tasks_update_own_assignee_admin ON public.tasks FOR UPDATE TO authenticated USING (auth.uid() = owner_id OR auth.uid() = assignee_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY tasks_delete_own_or_admin ON public.tasks FOR DELETE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));

-- Calendar events
CREATE TABLE public.calendar_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL,
  title text NOT NULL,
  description text,
  event_type text NOT NULL DEFAULT 'meeting',
  start_at timestamptz NOT NULL,
  end_at timestamptz,
  all_day boolean NOT NULL DEFAULT false,
  location text,
  case_id uuid,
  client_id uuid,
  color text,
  reminder_minutes integer,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.calendar_events TO authenticated;
GRANT ALL ON public.calendar_events TO service_role;
ALTER TABLE public.calendar_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY events_select_own ON public.calendar_events FOR SELECT TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY events_insert_own ON public.calendar_events FOR INSERT TO authenticated WITH CHECK (auth.uid() = owner_id);
CREATE POLICY events_update_own_or_admin ON public.calendar_events FOR UPDATE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY events_delete_own_or_admin ON public.calendar_events FOR DELETE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE TRIGGER trg_events_updated_at BEFORE UPDATE ON public.calendar_events FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE INDEX idx_events_start_at ON public.calendar_events(start_at);
CREATE INDEX idx_events_owner ON public.calendar_events(owner_id);

CREATE TABLE public.reminders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL,
  title text NOT NULL,
  note text,
  remind_at timestamptz NOT NULL,
  channel text NOT NULL DEFAULT 'in_app',
  status text NOT NULL DEFAULT 'pending',
  event_id uuid,
  case_id uuid,
  task_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.reminders TO authenticated;
GRANT ALL ON public.reminders TO service_role;
ALTER TABLE public.reminders ENABLE ROW LEVEL SECURITY;
CREATE POLICY reminders_select_own ON public.reminders FOR SELECT TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY reminders_insert_own ON public.reminders FOR INSERT TO authenticated WITH CHECK (auth.uid() = owner_id);
CREATE POLICY reminders_update_own_or_admin ON public.reminders FOR UPDATE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY reminders_delete_own_or_admin ON public.reminders FOR DELETE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE TRIGGER trg_reminders_updated_at BEFORE UPDATE ON public.reminders FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE INDEX idx_reminders_remind_at ON public.reminders(remind_at);
CREATE INDEX idx_reminders_owner ON public.reminders(owner_id);

-- AI outputs
CREATE TABLE public.ai_outputs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL,
  module text NOT NULL,
  title text NOT NULL,
  prompt text NOT NULL,
  output text,
  sources jsonb,
  model text,
  tokens_used integer,
  case_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.ai_outputs TO authenticated;
GRANT ALL ON public.ai_outputs TO service_role;
ALTER TABLE public.ai_outputs ENABLE ROW LEVEL SECURITY;
CREATE POLICY ai_outputs_select_own ON public.ai_outputs FOR SELECT TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY ai_outputs_insert_own ON public.ai_outputs FOR INSERT TO authenticated WITH CHECK (auth.uid() = owner_id);
CREATE POLICY ai_outputs_update_own_or_admin ON public.ai_outputs FOR UPDATE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY ai_outputs_delete_own_or_admin ON public.ai_outputs FOR DELETE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE TRIGGER trg_ai_outputs_updated_at BEFORE UPDATE ON public.ai_outputs FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE INDEX idx_ai_outputs_module ON public.ai_outputs(module);
CREATE INDEX idx_ai_outputs_owner ON public.ai_outputs(owner_id);
CREATE INDEX idx_ai_outputs_created ON public.ai_outputs(created_at DESC);

-- Calls
CREATE TABLE public.calls (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL,
  direction text NOT NULL DEFAULT 'inbound',
  phone text NOT NULL,
  caller_name text,
  client_id uuid,
  case_id uuid,
  status text NOT NULL DEFAULT 'answered',
  duration_sec integer NOT NULL DEFAULT 0,
  recording_url text,
  ai_summary text,
  ai_sentiment text,
  tags text[],
  notes text,
  started_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.calls TO authenticated;
GRANT ALL ON public.calls TO service_role;
ALTER TABLE public.calls ENABLE ROW LEVEL SECURITY;
CREATE POLICY calls_select_own ON public.calls FOR SELECT TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY calls_insert_own ON public.calls FOR INSERT TO authenticated WITH CHECK (auth.uid() = owner_id);
CREATE POLICY calls_update_own_or_admin ON public.calls FOR UPDATE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY calls_delete_own_or_admin ON public.calls FOR DELETE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE TRIGGER trg_calls_updated_at BEFORE UPDATE ON public.calls FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE INDEX idx_calls_started ON public.calls(started_at DESC);
CREATE INDEX idx_calls_owner ON public.calls(owner_id);
CREATE INDEX idx_calls_phone ON public.calls(phone);

CREATE TABLE public.call_settings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL UNIQUE,
  greeting text DEFAULT 'Merhaba, hukuk büromuzu aradığınız için teşekkürler. Talebinizi kısaca iletin, sizi en kısa sürede arayacağız.',
  voicemail_enabled boolean NOT NULL DEFAULT true,
  ai_summary_enabled boolean NOT NULL DEFAULT true,
  business_hours_start time DEFAULT '09:00',
  business_hours_end time DEFAULT '18:00',
  after_hours_message text DEFAULT 'Şu an mesai dışındayız. Mesajınızı bırakın, mesai başlangıcında dönüş yapacağız.',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.call_settings TO authenticated;
GRANT ALL ON public.call_settings TO service_role;
ALTER TABLE public.call_settings ENABLE ROW LEVEL SECURITY;
CREATE POLICY call_settings_select_own ON public.call_settings FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY call_settings_insert_own ON public.call_settings FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY call_settings_update_own ON public.call_settings FOR UPDATE TO authenticated USING (auth.uid() = user_id);
CREATE TRIGGER trg_call_settings_updated_at BEFORE UPDATE ON public.call_settings FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- Projects
CREATE TABLE public.projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL,
  name text NOT NULL,
  description text,
  case_id uuid REFERENCES public.cases(id) ON DELETE SET NULL,
  client_id uuid REFERENCES public.clients(id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'active',
  color text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.projects TO authenticated;
GRANT ALL ON public.projects TO service_role;
ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
CREATE POLICY projects_select_own ON public.projects FOR SELECT TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY projects_insert_own ON public.projects FOR INSERT TO authenticated WITH CHECK (auth.uid() = owner_id);
CREATE POLICY projects_update_own_or_admin ON public.projects FOR UPDATE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY projects_delete_own_or_admin ON public.projects FOR DELETE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE TRIGGER projects_set_updated_at BEFORE UPDATE ON public.projects FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TABLE public.project_notes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  owner_id uuid NOT NULL,
  title text,
  content text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.project_notes TO authenticated;
GRANT ALL ON public.project_notes TO service_role;
ALTER TABLE public.project_notes ENABLE ROW LEVEL SECURITY;
CREATE POLICY pnotes_select_own ON public.project_notes FOR SELECT TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY pnotes_insert_own ON public.project_notes FOR INSERT TO authenticated WITH CHECK (auth.uid() = owner_id);
CREATE POLICY pnotes_update_own_or_admin ON public.project_notes FOR UPDATE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE POLICY pnotes_delete_own_or_admin ON public.project_notes FOR DELETE TO authenticated USING (auth.uid() = owner_id OR public.has_role(auth.uid(),'admin'));
CREATE TRIGGER pnotes_set_updated_at BEFORE UPDATE ON public.project_notes FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.ai_outputs ADD COLUMN project_id uuid REFERENCES public.projects(id) ON DELETE SET NULL;
CREATE INDEX idx_projects_owner ON public.projects(owner_id);
CREATE INDEX idx_pnotes_project ON public.project_notes(project_id);
CREATE INDEX idx_ai_outputs_project ON public.ai_outputs(project_id);

-- Legal documents
CREATE TABLE public.legal_documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  doc_type text NOT NULL,
  title text NOT NULL,
  content text NOT NULL,
  parties jsonb DEFAULT '[]'::jsonb,
  metadata jsonb DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'draft',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.legal_documents TO authenticated;
GRANT ALL ON public.legal_documents TO service_role;
ALTER TABLE public.legal_documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY legal_documents_select_own ON public.legal_documents FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY legal_documents_insert_own ON public.legal_documents FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY legal_documents_update_own ON public.legal_documents FOR UPDATE TO authenticated USING (auth.uid() = user_id);
CREATE POLICY legal_documents_delete_own ON public.legal_documents FOR DELETE TO authenticated USING (auth.uid() = user_id);
CREATE TRIGGER trg_legal_documents_updated_at BEFORE UPDATE ON public.legal_documents FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE INDEX idx_legal_documents_user ON public.legal_documents(user_id, created_at DESC);

-- Chat
CREATE TABLE public.chat_conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  title text NOT NULL DEFAULT 'Yeni Sohbet',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.chat_conversations TO authenticated;
GRANT ALL ON public.chat_conversations TO service_role;
ALTER TABLE public.chat_conversations ENABLE ROW LEVEL SECURITY;
CREATE POLICY chat_conversations_select_own ON public.chat_conversations FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY chat_conversations_insert_own ON public.chat_conversations FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY chat_conversations_update_own ON public.chat_conversations FOR UPDATE TO authenticated USING (auth.uid() = user_id);
CREATE POLICY chat_conversations_delete_own ON public.chat_conversations FOR DELETE TO authenticated USING (auth.uid() = user_id);
CREATE TRIGGER trg_chat_conversations_updated_at BEFORE UPDATE ON public.chat_conversations FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE INDEX idx_chat_conversations_user ON public.chat_conversations(user_id, updated_at DESC);

CREATE TABLE public.chat_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL REFERENCES public.chat_conversations(id) ON DELETE CASCADE,
  user_id uuid NOT NULL,
  role text NOT NULL,
  content text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.chat_messages TO authenticated;
GRANT ALL ON public.chat_messages TO service_role;
ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY chat_messages_select_own ON public.chat_messages FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY chat_messages_insert_own ON public.chat_messages FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY chat_messages_delete_own ON public.chat_messages FOR DELETE TO authenticated USING (auth.uid() = user_id);
CREATE INDEX idx_chat_messages_conv ON public.chat_messages(conversation_id, created_at ASC);

-- Risk analyses
CREATE TABLE public.risk_analyses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  title text NOT NULL,
  source_text text NOT NULL,
  risk_score int NOT NULL DEFAULT 0,
  risk_level text NOT NULL DEFAULT 'unknown',
  findings jsonb NOT NULL DEFAULT '[]'::jsonb,
  recommendations jsonb NOT NULL DEFAULT '[]'::jsonb,
  summary text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.risk_analyses TO authenticated;
GRANT ALL ON public.risk_analyses TO service_role;
ALTER TABLE public.risk_analyses ENABLE ROW LEVEL SECURITY;
CREATE POLICY risk_analyses_select_own ON public.risk_analyses FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY risk_analyses_insert_own ON public.risk_analyses FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY risk_analyses_update_own ON public.risk_analyses FOR UPDATE TO authenticated USING (auth.uid() = user_id);
CREATE POLICY risk_analyses_delete_own ON public.risk_analyses FOR DELETE TO authenticated USING (auth.uid() = user_id);
CREATE TRIGGER trg_risk_analyses_updated_at BEFORE UPDATE ON public.risk_analyses FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE INDEX idx_risk_analyses_user ON public.risk_analyses(user_id, created_at DESC);

-- Yargitay case law
CREATE TABLE public.yargitay_cases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  daire text NOT NULL,
  esas_no text NOT NULL,
  karar_no text NOT NULL,
  karar_tarihi date,
  title text,
  excerpt text,
  full_text text,
  keywords text[] DEFAULT '{}',
  hukuk_dali text,
  source text NOT NULL DEFAULT 'ai_profile',
  source_url text,
  verified boolean NOT NULL DEFAULT false,
  metadata jsonb DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(daire, esas_no, karar_no)
);
GRANT SELECT ON public.yargitay_cases TO authenticated;
GRANT ALL ON public.yargitay_cases TO service_role;
ALTER TABLE public.yargitay_cases ENABLE ROW LEVEL SECURITY;
CREATE POLICY yargitay_cases_select_auth ON public.yargitay_cases FOR SELECT TO authenticated USING (true);
CREATE INDEX idx_yargitay_keywords ON public.yargitay_cases USING GIN(keywords);
CREATE INDEX idx_yargitay_hukuk_dali ON public.yargitay_cases(hukuk_dali);
CREATE INDEX idx_yargitay_fts ON public.yargitay_cases USING GIN(to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(excerpt,'') || ' ' || coalesce(full_text,'')));
CREATE TRIGGER yargitay_cases_updated_at BEFORE UPDATE ON public.yargitay_cases FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TABLE public.case_search_queries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  query_hash text NOT NULL UNIQUE,
  query_text text NOT NULL,
  result_case_ids uuid[] DEFAULT '{}',
  result_payload jsonb,
  hit_count integer NOT NULL DEFAULT 1,
  last_used_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);
GRANT ALL ON public.case_search_queries TO service_role;
ALTER TABLE public.case_search_queries ENABLE ROW LEVEL SECURITY;
CREATE POLICY case_search_queries_no_direct_access ON public.case_search_queries FOR SELECT USING (false);
CREATE INDEX idx_case_search_last_used ON public.case_search_queries(last_used_at DESC);

REVOKE EXECUTE ON FUNCTION public.has_role(uuid, public.app_role) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.has_role(uuid, public.app_role) TO authenticated;
REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.set_updated_at() FROM PUBLIC, anon, authenticated;
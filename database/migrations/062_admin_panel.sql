\set ON_ERROR_STOP on
-- Platform yönetici paneli (2026-10-24): uygulamaya kimlerin girebileceği (erişim listesi) ve yalnız SAYI döndüren
-- yönetici işlevleri.
--
-- KVKK sınırı: platform yöneticisi (NHR Yazılım) avukatların müvekkil, dava, belge ve sohbet İÇERİĞİNİ görmez. Yönetici
-- işlevleri yalnız hesap bilgisi (e-posta, ad, durum, roller, tarihler) ve sayılar döndürür. Geri bildirim metni istisnadır:
-- kullanıcı onu doğrudan platform ekibine yazar ("Geri bildirim" düğmesi; aynı metin `scripts/list_feedback.py` ile okunuyordu).
--
-- Erişim modu (`platform_settings.access_mode`): open = herkes hesap açıp giriş yapabilir; allowlist = yalnız
-- `access_allowlist`teki e-postalar hesap açabilir ve giriş yapabilir (kullanıcı kararı 2026-10-24: "bu uygulamaya sadece
-- benim mailini eklediğim kişiler girmesi lazım"). Yöneticiler listede olmasa da girer; askıdaki ya da silinmiş hesap hiçbir
-- modda giremez. Kural tek yerdedir (`app_user_access_allowed`, `app_email_access_allowed`) ve uygulama her girişte onu sorar:
-- kayıt, parola ve Google ile giriş, açık oturumun her isteği, UYAP eklentisinin bağlantı anahtarı (api/access.py).
-- Varsayılan 'open': yeni kurulumda ilk hesap açılabilsin; yönetici sonra panelden ya da `scripts/set_access_mode.py` ile
-- listeyi açar.
--
-- Erişim: tablolar RLS ile yalnız yöneticiye açıktır; kimlik doğrulama öncesi denetim nhr_app (tablo sahibi) ile yapılır.
-- Erişim işlevleri nhr_runtime'a açık değildir (listede kimin olduğu dışarıdan sınanamasın). Yönetici işlevleri SECURITY
-- DEFINER'dır ve ilk satırda yönetici rolünü denetler; nhr_runtime yalnız EXECUTE alır.

BEGIN;

CREATE TABLE IF NOT EXISTS public.platform_settings (
  key TEXT PRIMARY KEY CHECK (key IN ('access_mode')),
  value TEXT NOT NULL,
  updated_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT platform_settings_access_mode_check
    CHECK (key <> 'access_mode' OR value IN ('open', 'allowlist'))
);
INSERT INTO public.platform_settings (key, value) VALUES ('access_mode', 'open') ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.access_allowlist (
  id UUID PRIMARY KEY,
  email TEXT NOT NULL UNIQUE CHECK (email = lower(btrim(email)) AND char_length(email) BETWEEN 3 AND 320),
  note TEXT CHECK (note IS NULL OR char_length(note) <= 200),
  added_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
  added_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.platform_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.access_allowlist ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS platform_settings_admin ON public.platform_settings;
CREATE POLICY platform_settings_admin ON public.platform_settings
  USING (app_has_global_role('admin')) WITH CHECK (app_has_global_role('admin'));
DROP POLICY IF EXISTS access_allowlist_admin ON public.access_allowlist;
CREATE POLICY access_allowlist_admin ON public.access_allowlist
  USING (app_has_global_role('admin')) WITH CHECK (app_has_global_role('admin'));
REVOKE ALL ON public.platform_settings, public.access_allowlist FROM PUBLIC;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nhr_runtime') THEN
    GRANT SELECT, INSERT, UPDATE ON public.platform_settings TO nhr_runtime;
    REVOKE DELETE, TRUNCATE ON public.platform_settings FROM nhr_runtime;
    -- Listeden çıkarmak satırı siler (iz denetim kaydında kalır); RLS bunu yalnız yöneticiye açar.
    GRANT SELECT, INSERT, UPDATE, DELETE ON public.access_allowlist TO nhr_runtime;
    REVOKE TRUNCATE ON public.access_allowlist FROM nhr_runtime;
  END IF;
END $$;

-- Erişim kuralı. Yalnız tablo sahibi çağırır: kimlik doğrulama öncesi uygulama ve aşağıdaki yönetici işlevleri.
CREATE OR REPLACE FUNCTION public.app_access_mode()
RETURNS TEXT
LANGUAGE sql
STABLE
SET search_path TO 'pg_catalog', 'public'
AS $function$
  SELECT COALESCE((SELECT value FROM public.platform_settings WHERE key = 'access_mode'), 'open')
$function$;

CREATE OR REPLACE FUNCTION public.app_email_access_allowed(p_email TEXT)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SET search_path TO 'pg_catalog', 'public'
AS $function$
  SELECT public.app_access_mode() <> 'allowlist'
      OR EXISTS (SELECT 1 FROM public.access_allowlist a WHERE a.email = lower(btrim(p_email)))
$function$;

CREATE OR REPLACE FUNCTION public.app_user_access_allowed(p_user_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SET search_path TO 'pg_catalog', 'public'
AS $function$
  SELECT COALESCE((
    SELECT u.status = 'active' AND u.deleted_at IS NULL AND (
             public.app_email_access_allowed(u.email)
             OR EXISTS (SELECT 1 FROM public.user_roles ur JOIN public.roles r ON r.id = ur.role_id
                        WHERE ur.user_id = u.id AND r.code = 'admin'))
    FROM public.users u
    WHERE u.id = p_user_id), false)
$function$;

REVOKE ALL ON FUNCTION public.app_access_mode(), public.app_email_access_allowed(TEXT),
  public.app_user_access_allowed(UUID) FROM PUBLIC;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nhr_runtime') THEN
    REVOKE ALL ON FUNCTION public.app_access_mode(), public.app_email_access_allowed(TEXT),
      public.app_user_access_allowed(UUID) FROM nhr_runtime;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.admin_require()
RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $function$
BEGIN
  IF NOT public.app_has_global_role('admin') THEN
    RAISE EXCEPTION 'Bu işlem yalnız yöneticiye açıktır' USING ERRCODE = '42501';
  END IF;
END;
$function$;

CREATE OR REPLACE FUNCTION public.admin_user_overview()
RETURNS TABLE (
  user_id UUID, email TEXT, full_name TEXT, status TEXT, created_at TIMESTAMPTZ, last_login_at TIMESTAMPTZ,
  roles TEXT[], cases BIGINT, clients BIGINT, documents BIGINT, conversations BIGINT, ai_answers_30d BIGINT,
  last_activity_at TIMESTAMPTZ, listed BOOLEAN, has_access BOOLEAN
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $function$
BEGIN
  PERFORM public.admin_require();
  RETURN QUERY
  SELECT u.id, u.email, u.full_name, u.status, u.created_at, u.last_login_at,
         COALESCE((SELECT array_agg(r.code ORDER BY r.code) FROM public.user_roles ur
                   JOIN public.roles r ON r.id = ur.role_id WHERE ur.user_id = u.id), ARRAY[]::TEXT[]),
         (SELECT count(*) FROM public.office_cases c WHERE c.owner_id = u.id),
         (SELECT count(*) FROM public.office_clients c WHERE c.owner_id = u.id),
         (SELECT count(*) FROM public.office_case_documents d WHERE d.owner_id = u.id AND d.deleted_at IS NULL),
         (SELECT count(*) FROM public.conversations c WHERE c.created_by = u.id AND c.deleted_at IS NULL),
         (SELECT count(*) FROM public.activity_logs a
           WHERE a.actor_user_id = u.id AND a.action = 'ai.answer' AND a.created_at > now() - interval '30 days'),
         (SELECT max(a.created_at) FROM public.activity_logs a WHERE a.actor_user_id = u.id),
         EXISTS (SELECT 1 FROM public.access_allowlist l WHERE l.email = lower(u.email)),
         public.app_user_access_allowed(u.id)
  FROM public.users u
  WHERE u.deleted_at IS NULL
  ORDER BY u.created_at DESC;
END;
$function$;

CREATE OR REPLACE FUNCTION public.admin_platform_summary()
RETURNS TABLE (
  users_total BIGINT, users_active BIGINT, users_suspended BIGINT, users_new_7d BIGINT, users_seen_7d BIGINT,
  ai_answers_24h BIGINT, ai_answers_7d BIGINT, feedback_7d BIGINT, feedback_total BIGINT,
  cases_total BIGINT, documents_total BIGINT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $function$
BEGIN
  PERFORM public.admin_require();
  RETURN QUERY
  SELECT (SELECT count(*) FROM public.users WHERE deleted_at IS NULL),
         (SELECT count(*) FROM public.users WHERE deleted_at IS NULL AND status = 'active'),
         (SELECT count(*) FROM public.users WHERE deleted_at IS NULL AND status = 'suspended'),
         (SELECT count(*) FROM public.users WHERE deleted_at IS NULL AND created_at > now() - interval '7 days'),
         (SELECT count(*) FROM public.users WHERE deleted_at IS NULL AND last_login_at > now() - interval '7 days'),
         (SELECT count(*) FROM public.activity_logs WHERE action = 'ai.answer' AND created_at > now() - interval '1 day'),
         (SELECT count(*) FROM public.activity_logs WHERE action = 'ai.answer' AND created_at > now() - interval '7 days'),
         (SELECT count(*) FROM public.office_feedback WHERE created_at > now() - interval '7 days'),
         (SELECT count(*) FROM public.office_feedback),
         (SELECT count(*) FROM public.office_cases),
         (SELECT count(*) FROM public.office_case_documents WHERE deleted_at IS NULL);
END;
$function$;

CREATE OR REPLACE FUNCTION public.admin_feedback_list(p_limit INTEGER, p_category TEXT)
RETURNS TABLE (
  id UUID, created_at TIMESTAMPTZ, category TEXT, page TEXT, message TEXT,
  user_id UUID, user_email TEXT, user_name TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $function$
BEGIN
  PERFORM public.admin_require();
  RETURN QUERY
  SELECT f.id, f.created_at, f.category, f.page, f.message, u.id, u.email, u.full_name
  FROM public.office_feedback f
  JOIN public.users u ON u.id = f.owner_id
  WHERE p_category IS NULL OR f.category = p_category
  ORDER BY f.created_at DESC
  LIMIT LEAST(GREATEST(COALESCE(p_limit, 100), 1), 500);
END;
$function$;

REVOKE ALL ON FUNCTION public.admin_require(), public.admin_user_overview(), public.admin_platform_summary(),
  public.admin_feedback_list(INTEGER, TEXT) FROM PUBLIC;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nhr_runtime') THEN
    GRANT EXECUTE ON FUNCTION public.admin_require(), public.admin_user_overview(), public.admin_platform_summary(),
      public.admin_feedback_list(INTEGER, TEXT) TO nhr_runtime;
  END IF;
END $$;

COMMIT;

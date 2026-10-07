\set ON_ERROR_STOP on

-- UYAP dosya penceresinin evrak dışı bilgileri (dosya bilgileri, dosya hesabı, taraflar, safahat, tahsilat/reddiyat): dosya başına tek satır.
--
-- Eklenti sekmeleri salt okunur okur; değerler UYAP'ın yazdığı METİN olarak saklanır, yorumlanmaz. `tabs`, sekme listesidir:
--   [{key, label, pairs:[{label,value}], tables:[{title, headers, rows, declared, complete}], complete}]
-- `complete` yalnız her sekme tamamsa ve her tabloda okunan satır sayısı UYAP'ın "N Kayıttan" sayısıyla tutuyorsa true yazılır
-- (sunucu bunu istemcinin iddiasına bakmadan kendisi yeniden hesaplar). Bu satır kişisel veri içerir (taraf adları): yalnız sahibine
-- görünür (RLS), hesap silinince ya da dava silinince silinir, KVKK dışa aktarımına dahildir.
BEGIN;

CREATE TABLE IF NOT EXISTS office_uyap_case_detail (
  case_id UUID PRIMARY KEY REFERENCES office_cases(id) ON DELETE CASCADE,
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tabs JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(tabs) = 'array'),
  complete BOOLEAN NOT NULL DEFAULT false,
  problems JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(problems) = 'array'),
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_office_uyap_case_detail_owner ON office_uyap_case_detail (owner_id, fetched_at DESC);

ALTER TABLE office_uyap_case_detail ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS office_uyap_case_detail_owner_select ON office_uyap_case_detail;
DROP POLICY IF EXISTS office_uyap_case_detail_owner_insert ON office_uyap_case_detail;
DROP POLICY IF EXISTS office_uyap_case_detail_owner_update ON office_uyap_case_detail;
DROP POLICY IF EXISTS office_uyap_case_detail_owner_delete ON office_uyap_case_detail;
CREATE POLICY office_uyap_case_detail_owner_select ON office_uyap_case_detail FOR SELECT USING (owner_id = app_current_user_id());
CREATE POLICY office_uyap_case_detail_owner_insert ON office_uyap_case_detail FOR INSERT WITH CHECK (owner_id = app_current_user_id());
CREATE POLICY office_uyap_case_detail_owner_update ON office_uyap_case_detail FOR UPDATE
  USING (owner_id = app_current_user_id()) WITH CHECK (owner_id = app_current_user_id());
CREATE POLICY office_uyap_case_detail_owner_delete ON office_uyap_case_detail FOR DELETE USING (owner_id = app_current_user_id());

DROP TRIGGER IF EXISTS office_uyap_case_detail_updated_at ON office_uyap_case_detail;
CREATE TRIGGER office_uyap_case_detail_updated_at BEFORE UPDATE ON office_uyap_case_detail
  FOR EACH ROW EXECUTE FUNCTION office_set_updated_at();

-- Yabancı anahtar denetimi RLS'i atlar: bağlanan dava çağıranın kendi davası olmalıdır.
DROP TRIGGER IF EXISTS office_uyap_case_detail_own_refs ON office_uyap_case_detail;
CREATE TRIGGER office_uyap_case_detail_own_refs BEFORE INSERT OR UPDATE ON office_uyap_case_detail
  FOR EACH ROW EXECUTE FUNCTION office_require_own_references('case_id:office_cases');

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nhr_runtime') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON office_uyap_case_detail TO nhr_runtime;
  END IF;
END
$$;

COMMIT;

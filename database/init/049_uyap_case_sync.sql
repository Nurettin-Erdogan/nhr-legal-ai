\set ON_ERROR_STOP on

-- UYAP dosyasının son eşitleme doğrulaması ve UYAP dosya listesindeki üst veri (dosya başına tek satır).
--
-- "Tüm dosyaları aktar" koşusu her dosya için UYAP evrak ağacını aktarımdan SONRA yeniden okur ve ağaçtaki her evrakın
-- JurisAI'da kayıtlı olup olmadığını denetler. Sonuç burada tutulur: sayfa kapansa da "bu dosya şu tarihte eksiksiz
-- doğrulandı / şu kadar evrak eksik" bilgisi kalır. Sayılar tarayıcıdan gelir (sunucu UYAP'ı göremez); `server_documents`
-- sunucunun o anda kendi saydığı evrak sayısıdır ve `complete` ancak ikisi tutarlıysa true yazılır.
-- Üst veri (yargı türü, dosya türü, durum, taraf rolü, açılış) UYAP'ın gösterdiği metindir; yorumlanmaz.
BEGIN;

CREATE TABLE IF NOT EXISTS office_uyap_case_sync (
  case_id UUID PRIMARY KEY REFERENCES office_cases(id) ON DELETE CASCADE,
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  yargi_turu TEXT CHECK (yargi_turu IS NULL OR char_length(yargi_turu) <= 80),
  dosya_turu TEXT CHECK (dosya_turu IS NULL OR char_length(dosya_turu) <= 80),
  dosya_durumu TEXT CHECK (dosya_durumu IS NULL OR char_length(dosya_durumu) <= 80),
  taraf_rolu TEXT CHECK (taraf_rolu IS NULL OR char_length(taraf_rolu) <= 60),
  acilis TEXT CHECK (acilis IS NULL OR char_length(acilis) <= 40),
  declared_count INTEGER NOT NULL DEFAULT 0 CHECK (declared_count >= 0),
  found_count INTEGER NOT NULL DEFAULT 0 CHECK (found_count >= 0),
  missing_count INTEGER NOT NULL DEFAULT 0 CHECK (missing_count >= 0),
  server_documents INTEGER NOT NULL DEFAULT 0 CHECK (server_documents >= 0),
  complete BOOLEAN NOT NULL DEFAULT false,
  problems JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(problems) = 'array'),
  checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_office_uyap_case_sync_owner ON office_uyap_case_sync (owner_id, checked_at DESC);

ALTER TABLE office_uyap_case_sync ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS office_uyap_case_sync_owner_select ON office_uyap_case_sync;
DROP POLICY IF EXISTS office_uyap_case_sync_owner_insert ON office_uyap_case_sync;
DROP POLICY IF EXISTS office_uyap_case_sync_owner_update ON office_uyap_case_sync;
DROP POLICY IF EXISTS office_uyap_case_sync_owner_delete ON office_uyap_case_sync;
CREATE POLICY office_uyap_case_sync_owner_select ON office_uyap_case_sync FOR SELECT USING (owner_id = app_current_user_id());
CREATE POLICY office_uyap_case_sync_owner_insert ON office_uyap_case_sync FOR INSERT WITH CHECK (owner_id = app_current_user_id());
CREATE POLICY office_uyap_case_sync_owner_update ON office_uyap_case_sync FOR UPDATE
  USING (owner_id = app_current_user_id()) WITH CHECK (owner_id = app_current_user_id());
CREATE POLICY office_uyap_case_sync_owner_delete ON office_uyap_case_sync FOR DELETE USING (owner_id = app_current_user_id());

DROP TRIGGER IF EXISTS office_uyap_case_sync_updated_at ON office_uyap_case_sync;
CREATE TRIGGER office_uyap_case_sync_updated_at BEFORE UPDATE ON office_uyap_case_sync
  FOR EACH ROW EXECUTE FUNCTION office_set_updated_at();

-- Yabancı anahtar denetimi RLS'i atlar: bağlanan dava çağıranın kendi davası olmalıdır.
DROP TRIGGER IF EXISTS office_uyap_case_sync_own_refs ON office_uyap_case_sync;
CREATE TRIGGER office_uyap_case_sync_own_refs BEFORE INSERT OR UPDATE ON office_uyap_case_sync
  FOR EACH ROW EXECUTE FUNCTION office_require_own_references('case_id:office_cases');

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nhr_runtime') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON office_uyap_case_sync TO nhr_runtime;
  END IF;
END
$$;

COMMIT;

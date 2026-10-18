\set ON_ERROR_STOP on
BEGIN;
-- UYAP sayfası tanınmadığında (liste/ağaç okunamadı) eklentinin ürettiği YAPI özeti. Avukat Portalı gibi canlıda hiç
-- görülmemiş sayfaların ilk gerçek kullanımda düzeltilebilmesi için (2026-10-18). İçerik, ad, dosya numarası, kimlik ya da
-- bağlantı değeri taşımaz: eklenti değerleri maskeler (content.js `diagnose`), sunucu ayrıca uzun rakam dizisi ve e-posta
-- benzeri metni reddeder (api/uyap_diagnostics.py). Sahip başına en çok 50 kayıt tutulur.
CREATE TABLE IF NOT EXISTS office_uyap_diagnostics (
  id UUID PRIMARY KEY,
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code TEXT NOT NULL CHECK (code ~ '^[a-z_]{2,40}$'),
  context JSONB NOT NULL CHECK (jsonb_typeof(context) = 'object' AND octet_length(context::text) <= 4096),
  reports JSONB NOT NULL CHECK (jsonb_typeof(reports) = 'array' AND octet_length(reports::text) <= 65536),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS idx_office_uyap_diagnostics_owner ON office_uyap_diagnostics(owner_id, created_at DESC);
ALTER TABLE office_uyap_diagnostics ENABLE ROW LEVEL SECURITY;
ALTER TABLE office_uyap_diagnostics FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS office_uyap_diagnostics_select ON office_uyap_diagnostics;
DROP POLICY IF EXISTS office_uyap_diagnostics_insert ON office_uyap_diagnostics;
DROP POLICY IF EXISTS office_uyap_diagnostics_delete ON office_uyap_diagnostics;
CREATE POLICY office_uyap_diagnostics_select ON office_uyap_diagnostics FOR SELECT USING (owner_id=app_current_user_id());
CREATE POLICY office_uyap_diagnostics_insert ON office_uyap_diagnostics FOR INSERT WITH CHECK (owner_id=app_current_user_id());
CREATE POLICY office_uyap_diagnostics_delete ON office_uyap_diagnostics FOR DELETE USING (owner_id=app_current_user_id());
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nhr_runtime') THEN
    GRANT SELECT, INSERT, DELETE ON office_uyap_diagnostics TO nhr_runtime;
  END IF;
END $$;
COMMIT;

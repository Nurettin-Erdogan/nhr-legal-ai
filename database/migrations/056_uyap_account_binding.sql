\set ON_ERROR_STOP on
BEGIN;
-- Dosyalar kimin UYAP'ından geldiyse onun altında dursun (kullanıcı kararı 2026-10-16). Bir JurisAI hesabına birden çok
-- kişinin UYAP'ından aktarım yapılabilir; her evrak, aktarıldığı UYAP kişisiyle işaretlenir ve Belgeler'de buna göre ayrılır.
-- Kimse engellenmez.
--
-- KVKK: kimlik numarası saklanmaz. Eklenti numarayı tarayıcıda SHA-256 parmak izine çevirir; sunucu bunu ayrıca gizli bir
-- anahtarla HMAC'ler (`identity_digest`). `display_name`, UYAP'ın üst köşesinde yazan ad soyaddır (hesap sahibinin kendi
-- çalışma alanında, dosyaları ayırt etmek için); yalnız sahibi görür (RLS).
-- `kind = 'tc'`: kimlik numarasından; `kind = 'name'`: numara okunamayan portallarda addan.
CREATE TABLE IF NOT EXISTS office_uyap_accounts (
  id UUID PRIMARY KEY,
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  identity_digest TEXT NOT NULL CHECK (identity_digest ~ '^[0-9a-f]{64}$'),
  kind TEXT NOT NULL CHECK (kind IN ('tc', 'name')),
  portal TEXT NOT NULL CHECK (portal IN ('vatandas', 'avukat', 'diger')),
  display_name TEXT NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 120),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (owner_id, identity_digest)
);
ALTER TABLE office_uyap_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE office_uyap_accounts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS office_uyap_accounts_select ON office_uyap_accounts;
DROP POLICY IF EXISTS office_uyap_accounts_insert ON office_uyap_accounts;
DROP POLICY IF EXISTS office_uyap_accounts_update ON office_uyap_accounts;
DROP POLICY IF EXISTS office_uyap_accounts_delete ON office_uyap_accounts;
CREATE POLICY office_uyap_accounts_select ON office_uyap_accounts FOR SELECT USING (owner_id=app_current_user_id());
CREATE POLICY office_uyap_accounts_insert ON office_uyap_accounts FOR INSERT WITH CHECK (owner_id=app_current_user_id());
CREATE POLICY office_uyap_accounts_update ON office_uyap_accounts FOR UPDATE
  USING (owner_id=app_current_user_id()) WITH CHECK (owner_id=app_current_user_id());
CREATE POLICY office_uyap_accounts_delete ON office_uyap_accounts FOR DELETE USING (owner_id=app_current_user_id());

-- Evrakın geldiği UYAP kişisi. Eski evraklarda boştur ("kimden geldiği bilinmiyor"); o kişi yeniden UYAP'tan aktarım ya da
-- denetim yaptığında dosyasının evrakları onun adına işaretlenir.
ALTER TABLE office_case_documents ADD COLUMN IF NOT EXISTS uyap_account_id UUID REFERENCES office_uyap_accounts(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_office_case_documents_uyap_account ON office_case_documents(owner_id, uyap_account_id)
  WHERE deleted_at IS NULL;
-- Başka bir sahibin UYAP kişisiyle işaretlenemez.
CREATE OR REPLACE FUNCTION office_case_documents_uyap_account_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
  IF NEW.uyap_account_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM public.office_uyap_accounts a WHERE a.id = NEW.uyap_account_id AND a.owner_id = NEW.owner_id
  ) THEN
    RAISE EXCEPTION 'UYAP kişisi bu belgenin sahibine ait değil' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION office_case_documents_uyap_account_guard() FROM PUBLIC;
DROP TRIGGER IF EXISTS office_case_documents_uyap_account_guard ON office_case_documents;
CREATE TRIGGER office_case_documents_uyap_account_guard BEFORE INSERT OR UPDATE OF uyap_account_id, owner_id ON office_case_documents
  FOR EACH ROW EXECUTE FUNCTION office_case_documents_uyap_account_guard();

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nhr_runtime') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON office_uyap_accounts TO nhr_runtime;
  END IF;
END $$;
COMMIT;

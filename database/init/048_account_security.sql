\set ON_ERROR_STOP on

-- Hesap güvenliği ve KVKK kayıtları:
--  * Kayıtta kullanım şartları / aydınlatma metni onayının zamanı ve metnin sürümü (eski hesaplar NULL kalır: onay kaydı yoktur,
--    sonradan uydurulmaz).
--  * Şifre sıfırlama: tek kullanımlık, süreli bağlantı anahtarı. Anahtarın kendisi saklanmaz, yalnız SHA-256 özeti. Tabloya
--    uygulama rolü (nhr_runtime) erişemez; yalnız kimlik doğrulama öncesi sorguları yapan yönetici bağlantısı (nhr_app) okur/yazar.
--  * Hatırlatmanın kullanıcıya gösterildiği/e-postayla gönderildiği an (`notified_at`): aynı hatırlatma iki kez bildirilmez.
BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_version TEXT;
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_terms_version_check;
ALTER TABLE users ADD CONSTRAINT users_terms_version_check CHECK (terms_version IS NULL OR char_length(terms_version) <= 40);

CREATE TABLE IF NOT EXISTS auth_password_resets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE CHECK (char_length(token_hash) = 64),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_auth_password_resets_user ON auth_password_resets (user_id, created_at DESC);

ALTER TABLE auth_password_resets ENABLE ROW LEVEL SECURITY;
-- Politika yok: RLS açıkken politikasız tablo, sahibi dışındaki rollere hiçbir satır göstermez.
REVOKE ALL ON auth_password_resets FROM PUBLIC;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nhr_runtime') THEN
    REVOKE ALL ON auth_password_resets FROM nhr_runtime;
  END IF;
END
$$;

ALTER TABLE office_reminders ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_office_reminders_due
  ON office_reminders (remind_at) WHERE status = 'pending' AND notified_at IS NULL;

COMMIT;

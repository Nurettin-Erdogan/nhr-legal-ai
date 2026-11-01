\set ON_ERROR_STOP on

-- Vatandaş başvuru formu (office_basvurular): KVKK aydınlatma metninin okunduğunun kaydı.
-- Kişisel veri (ad, telefon, e-posta, uyuşmazlık konusu) toplayan formun aydınlatma metni onayı yoktu. Onay zamanı ve metnin sürümü
-- saklanır; eski satırlar NULL kalır (onay kaydı yok demektir, sonradan uydurulmaz).
BEGIN;

ALTER TABLE office_basvurular
  ADD COLUMN IF NOT EXISTS kvkk_aydinlatma_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS kvkk_aydinlatma_surum TEXT;

COMMIT;

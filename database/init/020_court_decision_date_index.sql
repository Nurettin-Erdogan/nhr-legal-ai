\set ON_ERROR_STOP on

BEGIN;

-- Üçüncü taraf kayıt doğrulayıcısı (scripts/verify_seeds.py) kararları tarihe göre en yeniden
-- eskiye, imleçle (decision_date, legal_source_id) dolaşır; indeks olmadan 10M satırda sıralama
-- her turda tam tarama yapar. Var olan büyük veritabanında CONCURRENTLY ile elle oluşturuldu.
CREATE INDEX IF NOT EXISTS idx_court_decision_date_desc
  ON court_decision_details (decision_date DESC, legal_source_id DESC)
  WHERE decision_date IS NOT NULL;

COMMIT;

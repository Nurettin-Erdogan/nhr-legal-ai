\set ON_ERROR_STOP on
BEGIN;

-- Giriş denemesi sınırlaması (api/auth/routes.py) son 15 dakikadaki başarısız girişleri sayar.
-- Kısmi indeks yalnız bu olayları kapsar; sayım, activity_logs ne kadar büyürse büyüsün küçük bir
-- aralık taramasıdır. Yeni tablo veya yetki yok: okuma yalnız kimlik doğrulama öncesi (nhr_app) yolundadır.
CREATE INDEX IF NOT EXISTS idx_activity_logs_login_failed_recent
  ON activity_logs (created_at DESC)
  WHERE action = 'auth.login_failed';

COMMIT;

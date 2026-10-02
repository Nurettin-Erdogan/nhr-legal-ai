\set ON_ERROR_STOP on
BEGIN;

-- Çıkışta oturum iptali: bu zamandan ÖNCE verilmiş jetonlar (JWT `iat`) geçersizdir. Jetonlar
-- durumsuz olduğundan çerezi silmek tek başına çalınmış bir jetonu iptal etmez.
-- Satır düzeyi güvenlik (`users_update_policy`) kullanıcıyı yalnız kendi satırıyla sınırlar; en kötü
-- ihtimalle kendi oturumlarını kapatabilir. Yazma kimlik doğrulama yolundan (nhr_app) yapılır.
ALTER TABLE users ADD COLUMN IF NOT EXISTS sessions_valid_after TIMESTAMPTZ;

COMMIT;

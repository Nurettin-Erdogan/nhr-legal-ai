\set ON_ERROR_STOP on
BEGIN;

-- UYAP dosya penceresindeki klasör ağacı yolu ("<dosya> / <evrak türü> / <evrak> / <ek>"). Eklenti
-- evrakları klasör yapısıyla çeker; arayüz evrakları bu yola göre gruplayabilir. RLS değişmez
-- (office_case_documents zaten sahibine özel).
ALTER TABLE office_case_documents ADD COLUMN IF NOT EXISTS uyap_path TEXT;

COMMIT;

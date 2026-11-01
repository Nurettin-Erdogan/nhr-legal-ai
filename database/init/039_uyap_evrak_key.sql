-- Evrak kimliği, dosya adındaki tirelerden tahmin edilmez. Eski kayıtlar güvenle NULL kalır;
-- tekrar indirildiklerinde aynı içerik normal yinelenen-belge denetiminden geçer.
ALTER TABLE office_case_documents ADD COLUMN IF NOT EXISTS uyap_evrak_key TEXT;

CREATE INDEX IF NOT EXISTS idx_office_case_documents_uyap_evrak_key
    ON office_case_documents (owner_id, uyap_file_no, uyap_evrak_key)
    WHERE deleted_at IS NULL AND uyap_evrak_key IS NOT NULL;

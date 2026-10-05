-- Aynı adlı/aynı boyutlu ama farklı içerikli evraklar ayrı tutulur; eşzamanlı tekrar
-- yükleme de tek kayıt üretir. Mevcut kayıtlar NULL kalır ve ilk tekrarda diskten doğrulanır.
ALTER TABLE office_case_documents ADD COLUMN IF NOT EXISTS checksum_sha256 TEXT;

ALTER TABLE office_case_documents
  ADD CONSTRAINT office_case_documents_checksum_sha256_format
  CHECK (checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$');

CREATE UNIQUE INDEX IF NOT EXISTS uq_office_case_documents_active_content
  ON office_case_documents (owner_id, COALESCE(uyap_file_no, ''), file_name, source, checksum_sha256)
  WHERE deleted_at IS NULL AND checksum_sha256 IS NOT NULL;

-- Mevcut kurulumlar: database/init/047_uyap_court_identity.sql ile aynı koruma.
BEGIN;
DROP INDEX IF EXISTS uq_office_case_documents_active_content;
DROP INDEX IF EXISTS uq_office_case_documents_uyap_identity;
CREATE UNIQUE INDEX uq_office_case_documents_active_content
  ON office_case_documents (
    owner_id, COALESCE(uyap_file_no, ''),
    COALESCE(lower(regexp_replace(translate(btrim(uyap_birim), 'İı', 'Ii'), '\s+', ' ', 'g')), ''),
    COALESCE(uyap_evrak_key, ''), file_name, source, checksum_sha256
  ) WHERE deleted_at IS NULL AND checksum_sha256 IS NOT NULL;
CREATE UNIQUE INDEX uq_office_case_documents_uyap_identity
  ON office_case_documents (
    owner_id, COALESCE(uyap_file_no, ''),
    COALESCE(lower(regexp_replace(translate(btrim(uyap_birim), 'İı', 'Ii'), '\s+', ' ', 'g')), ''),
    source, uyap_evrak_key
  ) WHERE deleted_at IS NULL AND uyap_evrak_key IS NOT NULL;
COMMIT;

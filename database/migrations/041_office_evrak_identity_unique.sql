-- İçeriği birebir aynı olsa da farklı UYAP evrak kimlikleri farklı belgelerdir.
DROP INDEX IF EXISTS uq_office_case_documents_active_content;
CREATE UNIQUE INDEX uq_office_case_documents_active_content
  ON office_case_documents (
    owner_id, COALESCE(uyap_file_no, ''), COALESCE(uyap_evrak_key, ''),
    file_name, source, checksum_sha256
  )
  WHERE deleted_at IS NULL AND checksum_sha256 IS NOT NULL;

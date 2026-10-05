-- Aynı kullanıcının aynı UYAP evrakı, ZIP paketinin baytları değişse bile tek aktif kayıt olur.
-- Metin gerçekten değişirse API 409 döndürür; yeni sürüm sessizce eski kaydı ezmez.
CREATE UNIQUE INDEX IF NOT EXISTS uq_office_case_documents_uyap_identity
  ON office_case_documents (
    owner_id, COALESCE(uyap_file_no, ''), source, uyap_evrak_key
  )
  WHERE deleted_at IS NULL AND uyap_evrak_key IS NOT NULL;
